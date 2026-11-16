#!/usr/bin/env bash
# BoxBench 维护者发布工具 — 本地改完文件后一键发布，双平台同步（GitHub + Gitee）
# 用法:
#   ./release.sh              # 自动: 算新版本号 -> bump 版本 -> CHANGELOG -> GitHub+Gitee 双平台同步
#   ./release.sh 1.4          # 指定版本号
#   ./release.sh --check      # 只检查差异，不发布
#   ./release.sh --github-only  # 只发 GitHub
#   ./release.sh --gitee-only   # 只发 Gitee
# 依赖: gh CLI（GitHub）；GITEE_TOKEN 环境变量或 ~/.gitee_token（Gitee）
set -uo pipefail

OWNER="huzhiqin"
GITEE_OWNER="276635035"
REPO_NAME="boxbench-skill"
GH_REPO="repos/${OWNER}/${REPO_NAME}"
GITEE_API="https://gitee.com/api/v5/repos/${GITEE_OWNER}/${REPO_NAME}/contents"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="gh api"

# Gitee 令牌：环境变量 > ~/.gitee_token
if [[ -z "${GITEE_TOKEN:-}" && -f "${HOME}/.gitee_token" ]]; then
  GITEE_TOKEN=$(cat "${HOME}/.gitee_token")
fi

# ---- 平台开关 ----
PUBLISH_GITHUB=1
PUBLISH_GITEE=1
for arg in "$@"; do
  case "$arg" in
    --github-only) PUBLISH_GITEE=0 ;;
    --gitee-only)  PUBLISH_GITHUB=0 ;;
  esac
done
MODE="${1:-}"
[[ "$MODE" == "--github-only" || "$MODE" == "--gitee-only" ]] && MODE=""

# 跳过令牌缺失的平台
if [[ "$PUBLISH_GITEE" == 1 && -z "${GITEE_TOKEN:-}" ]]; then
  echo "⚠️  无 Gitee 令牌（GITEE_TOKEN 或 ~/.gitee_token），本次只发 GitHub"
  PUBLISH_GITEE=0
fi

# ---------- GitHub API ----------
gh_version()   { $API "${GH_REPO}/contents/skill/SKILL.md" --jq '.content' 2>/dev/null | base64 -d | grep -m1 '^version:' | awk '{print $2}' || echo "none"; }
gh_files()     { $API "${GH_REPO}/git/trees/main?recursive=1" --jq '.tree[] | select(.type=="blob") | .path' 2>/dev/null; }
gh_content()   { $API "${GH_REPO}/contents/$1" --jq '.content' 2>/dev/null | tr -d '\n'; }
gh_upload()    { # $1=rel
  local sha content
  content=$(base64 < "${ROOT}/$1" | tr -d '\n')
  sha=$($API "${GH_REPO}/contents/$1" --jq '.sha' 2>/dev/null || true)
  local args=(-f "message=release: update $1" -f "content=${content}")
  [[ -n "$sha" ]] && args+=(-f "sha=${sha}")
  $API --method PUT "${GH_REPO}/contents/$1" "${args[@]}" --jq '.commit.sha' >/dev/null 2>&1
}
gh_delete()    { # $1=rel
  local sha; sha=$($API "${GH_REPO}/contents/$1" --jq '.sha' 2>/dev/null) || return 0
  $API --method DELETE "${GH_REPO}/contents/$1" -f "message=release: remove $1" -f "sha=${sha}" --jq '.commit.sha' >/dev/null 2>&1
}

# ---------- Gitee API ----------
gt_req() { # $1=method $2=url $3=json-body(可选) -> stdout body
  local m="$1" u="$2" b="${3:-}"
  curl -fsS --max-time 25 -X "$m" "$u" -H "Content-Type: application/json" ${b:+-d "$b"} 2>/dev/null
}
gt_version() {
  [[ "$PUBLISH_GITEE" == 1 ]] || { echo "none"; return; }
  gt_req GET "${GITEE_API}/skill/SKILL.md?access_token=${GITEE_TOKEN}&ref=main" | python3 -c "import base64,json,sys; print([l.split()[1] for l in base64.b64decode(json.load(sys.stdin)['content']).decode().splitlines() if l.startswith('version:')][0])" 2>/dev/null || echo "none"
}
gt_files() {
  [[ "$PUBLISH_GITEE" == 1 ]] || return
  gt_req GET "https://gitee.com/api/v5/repos/${GITEE_OWNER}/${REPO_NAME}/git/trees/main?access_token=${GITEE_TOKEN}&recursive=1" \
    | python3 -c "import json,sys; [print(t['path']) for t in json.load(sys.stdin).get('tree',[]) if t['type']=='blob']" 2>/dev/null
}
gt_sha() { # $1=rel -> blob sha or empty
  gt_req GET "${GITEE_API}/$1?access_token=${GITEE_TOKEN}&ref=main" | python3 -c "import json,sys; print(json.load(sys.stdin).get('sha',''))" 2>/dev/null
}
gt_upload() { # $1=rel
  local rel="$1" sha body method url
  sha=$(gt_sha "$rel")
  local content; content=$(base64 < "${ROOT}/${rel}" | tr -d '\n')
  if [[ -n "$sha" ]]; then
    body=$(python3 -c "import json,sys; print(json.dumps({'access_token':'${GITEE_TOKEN}','content':'${content}','sha':'${sha}','message':'release: update ${rel}','branch':'main'}))")
    method="PUT"
  else
    body=$(python3 -c "import json,sys; print(json.dumps({'access_token':'${GITEE_TOKEN}','content':'${content}','message':'release: add ${rel}','branch':'main'}))")
    method="POST"
  fi
  gt_req "$method" "${GITEE_API}/${rel}" "$body" >/dev/null
}
gt_delete() { # $1=rel
  local sha; sha=$(gt_sha "$1")
  [[ -n "$sha" ]] || return 0
  gt_req DELETE "${GITEE_API}/$1" "$(python3 -c "import json,sys; print(json.dumps({'access_token':'${GITEE_TOKEN}','sha':'${sha}','message':'release: remove ${rel_dummy:-$1}','branch':'main'}))")" >/dev/null
}

local_version() { grep -m1 '^version:' "${ROOT}/skill/SKILL.md" | awk '{print $2}' || echo "none"; }
local_files() {
  (cd "${ROOT}" && find . -type f ! -path './.git/*' ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name 'PUBLISH.md' ! -name 'release.sh' ! -name '.gitignore' ! -name '.DS_Store' | sed 's|^\./||' | sort)
}

bump_version() { # $1=新版本号：同步更新 SKILL.md 与两处 README 的版本字段
  local v="$1" today; today=$(date +%Y-%m-%d)
  perl -pi -e "s/^version: .*/version: ${v}/" "${ROOT}/skill/SKILL.md"
  perl -pi -e "s/^> 版本 .*/> 版本 ${v} ｜ SPEC 1.4 ｜ ${today}/" "${ROOT}/skill/README.md"
  perl -pi -e "s/^> v.* ｜ 工具无关 ｜ MIT License/> v${v} ｜ 工具无关 ｜ MIT License/" "${ROOT}/README.md"
}

# ---- 主流程 ----
MODE="${1:-}"
LV="$(local_version)"
GH_RV="none"; GT_RV="none"
[[ "$PUBLISH_GITHUB" == 1 ]] && GH_RV="$(gh_version)"
[[ "$PUBLISH_GITEE" == 1 ]] && GT_RV="$(gt_version)"
echo "本地: v${LV} ｜ GitHub: v${GH_RV} ｜ Gitee: v${GT_RV}"

# 差异预览（先算再 bump）
LOCAL_LIST="$(local_files)"
GH_CHANGED=""; GT_CHANGED=""
GH_LIST="$( [[ "$PUBLISH_GITHUB" == 1 ]] && gh_files || echo "$LOCAL_LIST" )"
GT_LIST="$( [[ "$PUBLISH_GITEE" == 1 ]] && gt_files || echo "$LOCAL_LIST" )"

if [[ "$PUBLISH_GITHUB" == 1 ]]; then
  for f in $LOCAL_LIST; do
    # 远端不存在的新文件：gh_content 为空 != base64 -> 自动纳入上传（新增文件也发布）
    [[ "$(gh_content "$f")" != "$(base64 < "${ROOT}/${f}" | tr -d '\n')" ]] && GH_CHANGED="$GH_CHANGED $f"
  done
fi
if [[ "$PUBLISH_GITEE" == 1 ]]; then
  for f in $LOCAL_LIST; do
    if gt_req GET "${GITEE_API}/${f}?access_token=${GITEE_TOKEN}&ref=main" >/dev/null 2>&1; then
      rmt=$(gt_req GET "${GITEE_API}/${f}?access_token=${GITEE_TOKEN}&ref=main" | python3 -c "import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)['content']).decode())" 2>/dev/null)
      [[ "$rmt" != "$(cat "${ROOT}/${f}")" ]] && GT_CHANGED="$GT_CHANGED $f"
    else
      GT_CHANGED="$GT_CHANGED $f"   # 远端不存在的新文件 -> 上传
    fi
  done
fi

if [[ "$MODE" == "--check" ]]; then
  echo "--- GitHub 差异: ${GH_CHANGED:-无} ｜ Gitee 差异:${GT_CHANGED:-无} ---"
  exit 0
fi

NEW_VER="${2:-}"
[[ -z "$NEW_VER" || "$NEW_VER" == --* ]] && NEW_VER="$(echo "$LV" | awk -F. '{printf "%d.%d.%d", $1, $2, $3+1}')"

# 强制重发同一版本（FORCE=1 或第三参 --force）：不 bump、不追加占位，只同步差异文件
FORCE_SYNC=0
[[ "${3:-}" == "--force" || "${FORCE:-}" == 1 ]] && FORCE_SYNC=1

if [[ "$FORCE_SYNC" == 0 && "$NEW_VER" == "$LV" ]]; then
  { echo "⚠️  新版本号与本地相同（${LV}），强制同步请用: FORCE=1 ./release.sh ${NEW_VER}"; exit 1; }
fi

echo "发布版本: v${LV} -> v${NEW_VER}$([[ "$FORCE_SYNC" == 1 ]] && echo '（强制同步，不 bump）')"
if [[ "$FORCE_SYNC" == 0 ]]; then
  bump_version "$NEW_VER"
  echo "✏️  skill/SKILL.md + 两处 README version -> ${NEW_VER}"
  # bump 涉及的 4 个文件强制纳入
  for vf in "skill/SKILL.md" "skill/README.md" "README.md" "CHANGELOG.md"; do
    case " $GH_CHANGED $GT_CHANGED " in
      *" $vf "*) ;;
      *) GH_CHANGED="$GH_CHANGED $vf"; GT_CHANGED="$GT_CHANGED $vf" ;;
    esac
  done
fi

# CHANGELOG 追加（仅正常发布时；强制同步不追加占位）
if [[ "$FORCE_SYNC" == 0 ]] && ! grep -q "^\#\# \[${NEW_VER}\]" "${ROOT}/CHANGELOG.md" 2>/dev/null; then
  { echo -e "\n## [${NEW_VER}] - $(date +%Y-%m-%d)\n\n### Changed\n- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）"; } >> "${ROOT}/CHANGELOG.md"
  echo "✏️  CHANGELOG.md 追加 [${NEW_VER}] 条目（记得补充明细）"
fi

# ---- 上传 GitHub ----
FAIL=0
if [[ "$PUBLISH_GITHUB" == 1 ]]; then
  echo "--- GitHub ---"
  for f in $GH_CHANGED; do echo "  ↑ $f"; gh_upload "$f" || { echo "  ❌ $f"; FAIL=1; }; done
fi
# ---- 上传 Gitee ----
if [[ "$PUBLISH_GITEE" == 1 ]]; then
  echo "--- Gitee ---"
  for f in $GT_CHANGED; do echo "  ↑ $f"; gt_upload "$f" || { echo "  ❌ $f"; FAIL=1; }; done
fi
[[ "$FAIL" == 1 ]] && { echo "部分文件失败，修正后重跑 ./release.sh"; exit 1; }

# 本地 git 记录（push 需邮箱验证，失败不阻塞）
git -C "${ROOT}" add -A 2>/dev/null && git -C "${ROOT}" commit -q -m "release v${NEW_VER}" 2>/dev/null || true

echo ""
echo "✅ v${NEW_VER} 发布完成（GitHub: $([ "$PUBLISH_GITHUB" == 1 ] && echo ✅ || echo 跳过) ｜ Gitee: $([ "$PUBLISH_GITEE" == 1 ] && echo ✅ || echo 跳过)）"
echo "   验证: gh api ${GH_REPO}/contents/skill/SKILL.md --jq '.content' | base64 -d | grep version"
