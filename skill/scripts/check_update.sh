#!/usr/bin/env bash
# BoxBench 版本自检 — 对比本地 SKILL.md 与 GitHub/Gitee 远端版本
# 用法:
#   bash check_update.sh            # 输出: up-to-date | outdated <远端版本> | unknown
#   bash check_update.sh --verbose  # 附带说明文字
#   bash check_update.sh --upgrade  # 发现新版本时自动调 install.sh 升级
# 设计原则: 任何失败都不阻塞测试 —— 版本旧也能跑，只是提醒。
# 网络不可达时输出 unknown（现场内网是常态，不算错误）。
set -uo pipefail

VERBOSE=0; UPGRADE=0
for a in "$@"; do
  case "$a" in
    --verbose) VERBOSE=1 ;;
    --upgrade) UPGRADE=1 ;;
  esac
done

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-}")/.." && pwd)"   # scripts/ 的上一级 = skill/
SKILL_MD="${DIR}/SKILL.md"

local_version() { grep -m1 '^version:' "${SKILL_MD}" 2>/dev/null | awk '{print $2}' || echo "none"; }

remote_version() {
  # GitHub -> Gitee 依次尝试, 5s 连接超时, 总预算 ~10s
  local urls=(
    "https://raw.githubusercontent.com/huzhiqin/boxbench-skill/main/skill/SKILL.md"
    "https://gitee.com/276635035/boxbench-skill/raw/main/skill/SKILL.md"
  )
  local u v
  for u in "${urls[@]}"; do
    v=$(curl -fsSL --connect-timeout 4 --max-time 8 "${u}" 2>/dev/null | grep -m1 '^version:' | awk '{print $2}')
    [ -n "${v:-}" ] && { echo "$v"; return; }
  done
  echo "unknown"
}

vcmp() { # $1 $2 -> echo "gt"|"lt"|"eq" (语义化比较 a.b.c)
  python3 - "$1" "$2" <<'PY'
import sys
def t(v):
    try: return tuple(int(x) for x in v.split("."))
    except Exception: return None
a, b = t(sys.argv[1]), t(sys.argv[2])
if a is None or b is None: print("eq"); raise SystemExit
print("gt" if a > b else "lt" if a < b else "eq")
PY
}

LV="$(local_version)"
RV="$(remote_version)"

if [[ "$RV" == "unknown" || "$LV" == "none" ]]; then
  [[ "$VERBOSE" == 1 ]] && echo "⚠️  无法确认远端版本（本地 v${LV}，网络不可达或文件缺失）— 不阻塞测试" >&2
  echo "unknown"
  exit 0
fi

case "$(vcmp "$LV" "$RV")" in
  eq)
    [[ "$VERBOSE" == 1 ]] && echo "✅ BoxBench 已是最新版本 v${LV}" >&2
    echo "up-to-date"
    ;;
  lt)
    [[ "$VERBOSE" == 1 ]] && echo "⬆️  BoxBench 有新版本: v${LV} -> v${RV}。升级: bash $(dirname "${BASH_SOURCE[0]:-}")/install.sh 或 boxbench-update" >&2
    echo "outdated ${RV}"
    if [[ "$UPGRADE" == 1 ]]; then
      local_upd="${DIR}/../boxbench-update"
      if [[ -f "$(dirname "${DIR}")/boxbench-skill/install.sh" ]]; then
        bash "$(dirname "${DIR}")/boxbench-skill/install.sh"
      elif [[ -f "${DIR}/install.sh" ]]; then
        bash "${DIR}/install.sh"
      elif [[ -x "${local_upd}" ]]; then
        bash "${local_upd}"
      else
        echo "⚠️  未找到 install.sh / boxbench-update，请手动从 GitHub/Gitee 重新安装" >&2
        exit 1
      fi
    fi
    ;;
  gt)
    [[ "$VERBOSE" == 1 ]] && echo "ℹ️  本地 v${LV} 比远端 v${RV} 新（可能是未发布的开发版）— 不阻塞测试" >&2
    echo "up-to-date"
    ;;
esac
