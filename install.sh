#!/usr/bin/env bash
# BoxBench Skill 一键安装 / 升级（GitHub + Gitee 双源，自动切换）
# 用法:
#   curl -fsSL https://raw.githubusercontent.com/huzhiqin/boxbench-skill/main/install.sh | bash
#   国内网络差时: curl -fsSL https://gitee.com/huzhiqin/boxbench-skill/raw/main/install.sh | bash
#   或: git clone 后 bash install.sh（本地文件优先，不联网）
set -euo pipefail

huzhiqin="${BOXBENCH_huzhiqin:-huzhiqin}"
REPO_NAME="boxbench-skill"
BRANCH="main"
# 源列表：按顺序尝试，环境变量 BOXBENCH_SOURCE=gitee/github 可强制指定
if [[ -n "${BOXBENCH_SOURCE:-}" ]]; then
  SOURCES=("BOXBENCH_SOURCE_FORCE")
else
  SOURCES=("github" "gitee")
fi
FORCE_SOURCE="${BOXBENCH_SOURCE:-}"

source_url() { # $1=source $2=文件相对路径 -> 输出 URL
  case "$1" in
    github) echo "https://raw.githubusercontent.com/${huzhiqin}/${REPO_NAME}/${BRANCH}/$2" ;;
    gitee)  echo "https://gitee.com/${huzhiqin}/${REPO_NAME}/raw/${BRANCH}/$2" ;;
    *)      return 1 ;;
  esac
}

# 取单个文件：依次尝试各源，连接 5s 超时、总 30s 超时
fetch() { # $1=相对路径 $2=目标路径
  local rel="$1" dest="$2"
  # 本地仓库场景：同目录存在该文件则直接用（git clone 后 bash install.sh）
  if [[ -f "$(dirname "${BASH_SOURCE[0]}")/skill/${rel}" ]]; then
    cp "$(dirname "${BASH_SOURCE[0]}")/skill/${rel}" "$dest"; return 0
  fi
  if [[ -f "skill/${rel}" ]]; then
    cp "skill/${rel}" "$dest"; return 0
  fi
  local s url
  for s in "${SOURCES[@]}"; do
    [[ "$s" == "BOXBENCH_SOURCE_FORCE" ]] && s="$FORCE_SOURCE"
    url="$(source_url "$s" "$rel")" || continue
    if curl -fsSL --connect-timeout 5 --max-time 30 "$url" -o "$dest" 2>/dev/null; then
      [ -s "$dest" ] && return 0
    fi
    rm -f "$dest"
  done
  echo "❌ 拉取失败: $rel（GitHub/Gitee 均不可达，检查网络或用 BOXBENCH_SOURCE=gitee 强制指定）" >&2
  return 1
}

FILES=(
  "SKILL.md"
  "SPEC.md"
  "HARDWARE_MODEL_MATRIX.md"
  "PLATFORM_NOTES.md"
  "README.md"
  "scripts/boxbench.sh"
  "scripts/render_report.py"
  "scripts/vendor/chart.umd.min.js"
)

# 自身更新：curl|bash 场景下重新拉取最新 install.sh 逻辑已内含（每次 fetch 都走最新远端）；
# 本地场景文件即最新。

# ---- 检测目标 skills 目录（可 BOXBENCH_TARGET 覆盖）----
detect_target() {
  if [[ -n "${BOXBENCH_TARGET:-}" ]]; then echo "$BOXBENCH_TARGET"; return; fi
  local candidates=(
    "${HOME}/.workbuddy/skills"
    "${HOME}/.claude/skills"
    "${HOME}/.cursor/skills"
    "${HOME}/.continue/skills"
  )
  local d
  for d in "${candidates[@]}"; do
    [[ -d "$d" ]] && { echo "$d"; return; }
  done
  echo "${HOME}/.workbuddy/skills"
}

TARGET_ROOT="$(detect_target)"
TARGET_DIR="${TARGET_ROOT}/box-bench"
IS_UPDATE=0
[[ -f "${TARGET_DIR}/SKILL.md" ]] && IS_UPDATE=1

# ---- 版本对比（远端不可达时不阻塞安装）----
local_version() { grep -m1 '^version:' "${TARGET_DIR}/SKILL.md" 2>/dev/null | awk '{print $2}' || echo "none"; }
remote_version() {
  local s url v
  for s in "${SOURCES[@]}"; do
    [[ "$s" == "BOXBENCH_SOURCE_FORCE" ]] && s="$FORCE_SOURCE"
    url="$(source_url "$s" "skill/SKILL.md")" || continue
    v=$(curl -fsSL --connect-timeout 5 --max-time 15 "$url" 2>/dev/null | grep -m1 '^version:' | awk '{print $2}') && [ -n "$v" ] && { echo "$v"; return; }
  done
  echo "unknown"
}

if [[ "$IS_UPDATE" == 1 ]]; then
  LV="$(local_version)"; RV="$(remote_version)"
  if [[ "$LV" == "$RV" ]]; then
    echo "✅ BoxBench 已是最新版本 v${LV}（${TARGET_DIR}），无需升级。"
    exit 0
  fi
  if [[ "$RV" == "unknown" ]]; then
    echo "⚠️  无法获取远端版本（网络不可达），仍尝试强制刷新文件..."
    RV_MSG="✅ 已刷新文件（远端版本无法确认，当前 v${LV}）"
  else
    echo "⬆️  发现新版本: v${LV} -> v${RV}，开始升级..."
    RV_MSG="✅ 升级完成: v${LV} -> v${RV}"
  fi
else
  RV_MSG=""
  echo "📦 安装 BoxBench Skill 到 ${TARGET_DIR} ..."
fi

# ---- 下载全部文件 ----
mkdir -p "${TARGET_DIR}/scripts/vendor"
for f in "${FILES[@]}"; do
  echo "  ↓ $f"
  fetch "$f" "${TARGET_DIR}/$f"
done
chmod +x "${TARGET_DIR}/scripts/boxbench.sh" "${TARGET_DIR}/scripts/render_report.py"
# vendor 完整性校验: 缺失则渲染器会降级 CDN (离线不可用), 提醒用户
if [ ! -s "${TARGET_DIR}/scripts/vendor/chart.umd.min.js" ]; then
  echo "⚠️  Chart.js vendor 下载失败——报告仍可渲染, 但离线环境图表不可用。可手动执行:" >&2
  echo "    curl -fsSL https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js -o ${TARGET_DIR}/scripts/vendor/chart.umd.min.js" >&2
fi

# ---- 写入升级命令 ----
cat > "${TARGET_DIR}/boxbench-update" <<UPD
#!/usr/bin/env bash
# BoxBench 升级：优先本地仓库，否则 GitHub -> Gitee 依次尝试
SRC_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "\${SRC_DIR}/../../boxbench-skill/install.sh" ]]; then
  exec bash "\${SRC_DIR}/../../boxbench-skill/install.sh"
fi
for BASE in "https://raw.githubusercontent.com/${huzhiqin}/${REPO_NAME}/${BRANCH}" "https://gitee.com/${huzhiqin}/${REPO_NAME}/raw/${BRANCH}"; do
  if curl -fsSL --connect-timeout 5 --max-time 30 "\${BASE}/install.sh" -o /tmp/boxbench-install.sh 2>/dev/null && [ -s /tmp/boxbench-install.sh ]; then
    exec bash /tmp/boxbench-install.sh
  fi
done
echo "❌ 升级失败：GitHub/Gitee 均不可达" >&2
exit 1
UPD
chmod +x "${TARGET_DIR}/boxbench-update"

if [[ "$IS_UPDATE" == 1 ]]; then
  echo "$RV_MSG"
else
  echo "✅ 安装完成: ${TARGET_DIR}"
fi
echo "   升级: ${TARGET_DIR}/boxbench-update"
echo "   使用: 对 AI 工具说「测这台盒子: IP x.x.x.x, 账号 xx, 密码 xx」即可触发。"
