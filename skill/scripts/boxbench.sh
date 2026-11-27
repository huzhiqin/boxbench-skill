#!/bin/bash
# =============================================================
# BoxBench v1.1 — 工控算力盒子标准化测试采集脚本
# 依据: SPEC v1.1 (2026-11-11)
# 用法: bash boxbench.sh [phase] [model_spec ...]
#   phase = fingerprint  仅阶段A硬件指纹+阶段B环境盘点
#           collect      阶段A+B + 单模型测试(需服务已启动)
#           multi        多模型顺序测试: 每模型起服务→C1~C12→停服务→下一个
#           classify     硬件分档 + 推荐模型清单
#           (默认)       自动: fingerprint + 检测推理服务,有则collect
#
#   model_spec 格式 (multi 模式): "模型名|模型文件绝对路径"
#   例: bash boxbench.sh multi \
#         "Qwen3.6-35B-A3B(W4A8)|/home/dev/houmoAI/houmo/1_model/HiModel_xh2_qwen3.6-35b-a3b_w4a8_256_256k_b1_1chip_2cores_v1.5.0_20260824.gguf" \
#         "Qwen3.8-27b-mtp(W4A8)|/home/dev/houmoAI/houmo/houmo-HLIELLama-xh2/models/xxx.gguf"
#
#   环境变量:
#     BOX_API       推理服务地址 (默认 http://127.0.0.1:17701)
#     BOX_ENGINE    引擎 llama-server 路径 (默认 /home/dev/houmoAI/houmo/houmo-HLIELLama-xh2/bin/llama-server)
#     BOX_ENGINE_LIB 引擎 lib 目录 (默认 /home/dev/houmoAI/houmo/houmo-HLIELLama-xh2/lib)
#     BOX_PORT      服务端口 (默认 17701)
#     BOX_OPENCLAW       openclaw CLI 路径 (阶段E, 默认自动探测 PATH)
#     BOX_OPENCLAW_PORT  OpenClaw 网关端口 (阶段E, 默认 18789)
#     BOX_AGENT_SKIP=1   强制跳过阶段E Agent 集成测试
#     BOX_AGENT_AUTOINSTALL=0  关闭 OpenClaw 自动安装 (默认: Linux 未装时自动 install.sh 安装)
# 产出: ./boxbench_results_{YYYYMMDD_HHMMSS}.json (stdout 输出路径)
# =============================================================
VERSION="1.9"
SPEC_VERSION="1.7"
OUT="boxbench_results_$(date +%Y%m%d_%H%M%S).json"
# 运行日志落盘 (过程留痕: 每步时间戳, 供复核/复盘/证明真实执行)
RUNLOG="boxbench_run_$(date +%Y%m%d_%H%M%S).log"
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT

API="${BOX_API:-http://127.0.0.1:17701}"
PORT="${BOX_PORT:-17701}"
ENGINE="${BOX_ENGINE:-/home/dev/houmoAI/houmo/houmo-HLIELLama-xh2/bin/llama-server}"
ENGINE_LIB="${BOX_ENGINE_LIB:-/home/dev/houmoAI/houmo/houmo-HLIELLama-xh2/lib}"

log() {
  local ts; ts="$(date '+%H:%M:%S')"
  echo "[$ts] [boxbench] $*" | tee -a "$RUNLOG" >&2
}

# ---------- 版本自检 (后台异步, 24h 缓存, 失败静默; v1.11.0) ----------
# 目的: 设备端跑的是旧版脚本时给 Agent 提示。设计原则: 永不阻塞、永不报错打断测试。
# 缓存: /tmp/.boxbench_vercheck, 86400s 内直接复用结果; BOXBENCH_SKIP_VERCHECK=1 跳过。
version_check_bg() {
  [ "${BOXBENCH_SKIP_VERCHECK:-}" = "1" ] && return 0
  local CACHE="/tmp/.boxbench_vercheck" now
  now=$(date +%s 2>/dev/null) || return 0
  if [ -s "$CACHE" ]; then
    local ts lv rv
    ts=$(cut -d'|' -f1 "$CACHE" 2>/dev/null); lv=$(cut -d'|' -f2 "$CACHE" 2>/dev/null); rv=$(cut -d'|' -f3 "$CACHE" 2>/dev/null)
    if [ -n "$ts" ] && [ $(( now - ts )) -lt 86400 ] 2>/dev/null; then
      [ "$lv" = "$VERSION" ] || { log "⚠ 本地脚本 v${lv:-?} 与运行中 v${VERSION} 不一致 (缓存)"; }
      [ -n "$rv" ] && [ "$rv" != "$lv" ] && log "⬆ 云端已有新版本 v${rv} (本地 v${lv}) — 建议: 把仓库最新 scripts/boxbench.sh 重新分发到设备"
      return 0
    fi
  fi
  (
    local RV=""
    RV=$(curl -fsSL --connect-timeout 4 --max-time 8 "https://raw.githubusercontent.com/huzhiqin/boxbench-skill/main/skill/scripts/boxbench.sh" 2>/dev/null | grep -m1 '^VERSION=' | cut -d'"' -f2) || true
    [ -z "$RV" ] && RV=$(curl -fsSL --connect-timeout 4 --max-time 8 "https://gitee.com/276635035/boxbench-skill/raw/main/skill/scripts/boxbench.sh" 2>/dev/null | grep -m1 '^VERSION=' | cut -d'"' -f2) || true
    echo "${now}|${VERSION}|${RV:-}" > "$CACHE" 2>/dev/null
    [ -n "$RV" ] && [ "$RV" != "$VERSION" ] && log "⬆ 云端已有新版本 v${RV} (设备端 v${VERSION}) — 不影响本次测试, 建议事后升级"
  ) &
}

# Structured events go to stderr, never into result JSON or command substitutions.
# They also travel over SSH, so the viewer runs on the Agent's local machine.
progress() {
  python3 - "$1" "$2" "${3:-}" <<'PYLIVE' >&2
import json, sys
print('@@BOXBENCH_EVENT ' + json.dumps(dict(stage=sys.argv[1], status=sys.argv[2], detail=sys.argv[3]), ensure_ascii=False), flush=True)
PYLIVE
}
progress_model() {
  python3 - "$1" <<'PYLIVE' >&2
import json, sys
print('@@BOXBENCH_EVENT ' + json.dumps(dict(type='model', name=sys.argv[1]), ensure_ascii=False), flush=True)
PYLIVE
}
skip_model_steps() {
  local step
  for step in decode context concurrency tools memory resources latency agent; do
    progress "$step" skipped "$1"
  done
}

# ---------- NPU/加速卡利用率采样器 ----------
# 后台进程: 每1s读一次 mthreads-gmi -q (或 nvidia-smi), 追加 "epoch util% mem% temp clk_MHz" 到采样文件
# 用法: util_start  (启动, $UTILF 为采样文件) ... util_stop  (停止, 打印采样文件路径)
UTILF=""
util_reader_available() {
  command -v mthreads-gmi >/dev/null 2>&1 && return 0
  command -v nvidia-smi >/dev/null 2>&1 && return 0
  return 1
}
util_start() {
  util_reader_available || return 1
  UTILF="$TMPD/util_samples.txt"; : > "$UTILF"
  (
    while true; do
      if command -v mthreads-gmi >/dev/null 2>&1; then
        LINE=$(mthreads-gmi -q 2>/dev/null | awk '
          /^ *Gpu:/{gsub(/%/,"");u=($2 ~ /^[0-9.]+$/)?$2:-1}
          /^ *Memory:/{gsub(/%/,"");m=($2 ~ /^[0-9.]+$/)?$2:-1}
          /GPU Current Temp/{gsub(/C$/,"");t=($4 ~ /^[0-9.]+$/)?$4:-1}
          /^ *Graphics:/{clk=($2 ~ /^[0-9]+$/)?$2/1000000:0}
          END{printf "%.0f %s %s %.0f", u+0, (m==""?-1:m), (t==""?-1:t), clk+0}')
        # Memory: 行在 Utilization 段外也可能匹配到 % 值; Gpu 为空时放弃该样本
        [ -z "$(echo "$LINE" | awk '{print $1}')" ] && LINE="-1 -1 -1 0"
      else
        LINE=$(nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,clocks.sm --format=csv,noheader,nounits 2>/dev/null | awk -F', ' '{printf "%s %.0f %s %.0f", $1, ($3>0?$2*100/$3:0), $4, $5}')
      fi
      echo "$(date +%s.%N) $LINE" >> "$UTILF"
      sleep 1
    done
  ) > /dev/null 2>&1 &
  UTIL_PID=$!
}
util_stop() {
  [ -n "$UTIL_PID" ] && kill "$UTIL_PID" 2>/dev/null; wait "$UTIL_PID" 2>/dev/null
  echo "$UTILF"
}
# 汇总一段时间窗的采样 → JSON 片段 {"samples":N,"util_avg":x,"util_peak":y,"mem_pct_avg":z,"temp_max":t}
# $1=起始epoch $2=结束epoch $3=采样文件 (mem 为显存占用百分比)
util_summarize() {
  python3 - "$1" "$2" "$3" << 'PYEOF'
import sys, json
t0, t1, path = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
us, ms, ts = [], [], []
try:
    for line in open(path):
        p = line.split()
        if len(p) < 5: continue
        t = float(p[0])
        if t < t0 - 0.5 or t > t1 + 1.5: continue
        try:
            u, m, temp = float(p[1]), float(p[2]), float(p[3])
        except ValueError:
            continue
        if u >= 0: us.append(u)
        if m >= 0: ms.append(m)
        if temp >= 0: ts.append(temp)
except FileNotFoundError:
    pass
def r(x, n=1): return round(x, n) if x is not None else None
u_avg = r(sum(us)/len(us)) if us else None
u_pk  = r(max(us)) if us else None
m_avg = r(sum(ms)/len(ms)) if ms else None
t_max = r(max(ts)) if ts else None
print(json.dumps({"samples": len(us), "util_avg": u_avg, "util_peak": u_pk,
                  "mem_pct_avg": m_avg, "temp_max": t_max}))
PYEOF
}

# ---------- 阶段 A: 硬件指纹 ----------
phase_fingerprint() {
  progress hardware running "采集芯片、内存、存储与加速器"
  log "阶段A: 硬件指纹采集"
  {
    echo "{"
    echo "\"boxbench_version\":\"$VERSION\",\"spec_version\":\"$SPEC_VERSION\",\"timestamp\":\"$(date -Iseconds)\""
    echo ",\"phase_a\":{"
    echo "\"hostname\":\"$(hostname)\""
    IP=$(ip -br a 2>/dev/null | awk '$1!="lo" && NF>=3{print $1"="$3}' | paste -sd' ' -)
    echo ",\"interfaces\":\"$IP\""
    echo ",\"os\":\"$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}")\""
    echo ",\"kernel\":\"$(uname -r)\""
    CPU_MODEL=$(LANG=C lscpu 2>/dev/null | awk -F: '/Model name/{gsub(/^ +/,"");print $2;exit}')
    echo ",\"cpu_model\":\"$CPU_MODEL\""
    echo ",\"cpu_arch\":\"$(uname -m)\""
    echo ",\"cpu_cores\":\"$(nproc)\""
    echo ",\"cpu_max_mhz\":\"$(LANG=C lscpu 2>/dev/null | awk -F: '/CPU max MHz/{gsub(/^ +/,"");print $2;exit}')\""
    echo ",\"mem_total\":\"$(LANG=C free -h | awk '/Mem:/{print $2}')\""
    echo ",\"mem_available\":\"$(LANG=C free -h | awk '/Mem:/{print $7}')\""
    ROOT_DF=$(df -h / | awk 'NR==2{print $2"/"$3" ("$5" used)"}')
    echo ",\"root_disk\":\"$ROOT_DF\""
    echo ",\"blocks\":\"$(lsblk -dn -o NAME,SIZE,TYPE 2>/dev/null | awk '{print $1"="$2"("$3")"}' | paste -sd' ' - | tr -d '\n\r')\""
    # 加速卡
    ACC=""
    if command -v mthreads-gmi >/dev/null 2>&1; then
      # 跳过表头行(NR>2), 拼产品名+显存
      ACC=$(mthreads-gmi 2>/dev/null | awk 'NR>2 && NF>4 {print $2" mem="$5}' | grep -vE '^Name|^Type|^mem= *$' | paste -sd' ' -)
    fi
    [ -z "$ACC" ] && ACC=$(ls /dev/dri 2>/dev/null | paste -sd' ' -)
    ACC=$(echo "$ACC" | tr -d '\t\r\n|' | tr -s ' ')
    echo ",\"accelerator\":\"$ACC\""
    echo ",\"accel_tool\":\"$(command -v mthreads-gmi nvidia-smi npu-smi 2>/dev/null | head -1)\""
    echo ",\"load\":\"$(uptime | awk -F'load average:' '{print $2}')\""
    echo "}"
  } >> "$TMPD/out.json"
  progress hardware done "硬件指纹采集结束"
}

# ---------- 阶段 B: 环境盘点 ----------
phase_inventory() {
  progress inventory running "盘点模型、引擎、容器和监听服务，可能需要1–2分钟"
  log "阶段B: 环境盘点(约1-2分钟)"
  echo ",\"phase_b\":{" >> "$TMPD/out.json"
  # 模型权重
  MODELS=$(timeout 90 find /home /opt /data /mnt /media -xdev -type f \
    \( -name '*.gguf' -o -name '*.safetensors' -o -name '*.onnx' \) -size +100M 2>/dev/null | head -30)
  echo "\"model_files\":[" >> "$TMPD/out.json"
  first=1
  for f in $MODELS; do
    sz=$(du -h "$f" 2>/dev/null | cut -f1)
    mt=$(date -r "$f" '+%Y-%m-%d' 2>/dev/null)
    [ $first -eq 1 ] && first=0 || echo "," >> "$TMPD/out.json"
    echo "{\"path\":\"$f\",\"size\":\"$sz\",\"mtime\":\"$mt\"}" >> "$TMPD/out.json"
 done
  echo "]" >> "$TMPD/out.json"
  # 推理引擎
  ENGINES=""
  for e in $(ls -d /usr/local/* /opt/* ~/houmoAI 2>/dev/null); do
    case "$e" in *musa*|*llama*|*vllm*|*ollama*|*tensorrt*|*cann*|*houmoAI*) ENGINES="$ENGINES $e";; esac
  done
  echo ",\"engine_paths\":\"$ENGINES\"" >> "$TMPD/out.json"
  # docker
  DOCKER=$(docker ps -a --format '{{.Names}}:{{.Image}}:{{.Status}}' 2>/dev/null | paste -sd' ' -)
  echo ",\"docker\":\"$DOCKER\"" >> "$TMPD/out.json"
  # 监听端口中的推理服务
  SRV=$(ss -tlnp 2>/dev/null | grep -E ':(8080|8088|11434|17701|8000|9997)' | awk '{print $4}' | paste -sd' ' -)
  echo ",\"ai_services\":\"$SRV\"" >> "$TMPD/out.json"
  echo "}" >> "$TMPD/out.json"
  progress inventory done "环境盘点结束"
}

# ---------- 阶段 C: 单模型测试(需要 API 端点已就绪) ----------
# 输出到 $TMPD/phasec_fragment.json (一个完整 {} 对象)
phase_collect() {
  progress service running "检查推理服务就绪状态"
  log "阶段C: 模型实测采集 (API=$API)"
  if ! curl -s --max-time 5 "$API/health" | grep -q '"ok"'; then
    log "⚠ 服务未就绪($API/health)，跳过阶段C。"
    echo "{\"skipped\":\"service_not_ready\",\"api\":\"$API\"}" > "$TMPD/phasec_fragment.json"
    progress service skipped "推理服务未就绪，本次未运行模型实测"
    skip_model_steps "推理服务未就绪"
    return
  fi
  progress service done "推理服务已就绪"
  {
    echo "{"
    echo "\"api\":\"$API\""
    # 启动整场采样器: 全程 1s 间隔记录 NPU util/mem/temp, 各测试段按时间窗切分汇总
    UTIL_START_TS=$(date +%s.%N)
    util_start
    # 采样器启动缓冲, 保证空闲基线段有几秒样本
    sleep 3
    IDLE_T0=$(date +%s.%N)
    sleep 4
    IDLE_T1=$(date +%s.%N)
    # C2: 解码速度(短输入,关思考) — tok/s 以 API usage.completion_tokens 为准(引擎统计口径)
    # v1.9: 流式 chunk 计时补峰值口径（1s 滑动窗口最大瞬时速度），与 Windows 采集端对齐
    progress decode running "请求短输入生成（流式），采集 usage + 峰值/均值速度"
    T0=$(date +%s.%N)
    curl -s --max-time 300 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"请写一段250字左右的短文，介绍人工智能在工业质检中的应用"}],
      "max_tokens":400,"stream":true,"stream_options":{"include_usage":true},"chat_template_kwargs":{"enable_thinking":false}}' \
      | python3 -c '
import sys, json, time
t0 = time.time()
ts, content, usage = [], [], None
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("data:"):
        continue
    payload = line[5:].strip()
    if payload == "[DONE]":
        break
    try:
        d = json.loads(payload)
        if d.get("usage"):
            usage = d["usage"]
        choices = d.get("choices") or []
        delta = (choices[0].get("delta", {}) if choices else {})
        if delta.get("content"):
            ts.append(time.time() - t0)
            content.append(delta["content"])
    except Exception:
        pass
# 瞬时速度: 相邻 content chunk 间推定 1 token（流式解码每 chunk ≈1 token，业界通用口径）,
# 窗口 1s 平滑抑制抖动; 峰值取窗口最大瞬时值; 均值=(chunk 数-1)/首尾跨度（与 usage 互验）
peak = mean = None; chunks = len(ts)
if chunks >= 4:
    t = [0.0] + ts
    span = t[-1] - t[0]
    mean = (chunks - 1) / span if span > 0 else 0
    pk, i = 0.0, 0
    for j in range(len(t)):
        while t[j] - t[i] > 1.0:
            i += 1
        w = t[j] - t[i]
        if w > 0.05 and (j - i) / w > pk:
            pk = (j - i) / w
    peak, mean = round(pk, 1), round(mean, 1)
json.dump({"ts": ts, "content": "".join(content), "peak": peak, "mean": mean, "chunks": chunks, "usage": usage}, open("/dev/stdout","w"))
' > "$TMPD/c2_stream.json"
    T1=$(date +%s.%N)
    # usage 优先取流式响应尾帧真实 usage（include_usage），缺失时回退 chunk 计数
    R1=$(python3 -c "
import json
d = json.load(open('$TMPD/c2_stream.json'))
u = d.get('usage') or {}
print(json.dumps({'usage': {'prompt_tokens': u.get('prompt_tokens', -1), 'completion_tokens': u.get('completion_tokens', d.get('chunks', -1))}, 'choices':[{'message':{'content': d.get('content','')}}]}))
" 2>/dev/null || echo '{"usage":{"prompt_tokens":-1,"completion_tokens":-1},"choices":[{"message":{"content":""}}]}')
    echo ",\"c2_short_decode\":{\"wall_s\":$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}'),$(echo "$R1" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin); u=d.get("usage",{})
    pt=u.get("prompt_tokens",-1); ct=u.get("completion_tokens",-1)
    print("\"prompt_tokens\":%d,\"completion_tokens\":%d"% (pt,ct))
except Exception:
    print("\"prompt_tokens\":-1,\"completion_tokens\":-1")'),\"reply_len\":$(echo "$R1" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["choices"][0]["message"].get("content","")))' 2>/dev/null || echo -1),$(python3 -c "
import json
d = json.load(open('$TMPD/c2_stream.json'))
print('\"speed_peak_tps\":%s,\"speed_mean_tps\":%s,\"speed_method\":\"流式 chunk 计时；峰值=1s 滑动窗口最大瞬时速度，均值=chunk 跨度均速\",\"speed_chunks\":%s' % (d.get('peak'), d.get('mean'), d.get('chunks')))
" 2>/dev/null || echo '\"speed_peak_tps\":null,\"speed_mean_tps\":null'),\"npu\":$(util_summarize "$T0" "$T1" "$UTILF")}"
    # C4/C5: 长上下文
    progress decode done "短输入生成采集结束，结果写入原始 JSON"
    progress context running "执行长输入请求，等待模型响应"
    python3 - > "$TMPD/long.json" << 'PYEOF'
import json
para = '智能制造通过工业物联网、人工智能、大数据分析和数字孪生技术的深度融合，实现生产过程的自主感知、自主决策和自主执行。智能工厂中设备互联产生海量数据，边缘计算节点负责实时预处理，云端平台承担模型训练与全局优化。机器视觉引入质检环节后缺陷识别准确率大幅提升。预测性维护系统通过振动温度等传感器数据判断设备健康状态，显著压缩非计划停机时间。'
open('/dev/stdout','w').write(json.dumps({"messages":[{"role":"user","content":para*12+"，请用50字总结核心"}],"max_tokens":120,"stream":False,"chat_template_kwargs":{"enable_thinking":False}}))
PYEOF
    T0=$(date +%s.%N)
    curl -s --max-time 380 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d @"$TMPD/long.json" > "$TMPD/longr.json"
    T1=$(date +%s.%N)
    echo ",\"c4_long_ctx\":{\"wall_s\":$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}'),\"ok\":$(python3 -c 'import json; d=json.load(open("'$TMPD'/longr.json")); print(1 if d["choices"][0]["message"]["content"] else 0)' 2>/dev/null || echo -1),\"prompt_tokens\":$(python3 -c 'import json; print(json.load(open("'$TMPD'/longr.json")).get("usage",{}).get("prompt_tokens",-1))' 2>/dev/null || echo -1),\"completion_tokens\":$(python3 -c 'import json; print(json.load(open("'$TMPD'/longr.json")).get("usage",{}).get("completion_tokens",-1))' 2>/dev/null || echo -1),\"npu\":$(util_summarize "$T0" "$T1" "$UTILF")}"
    echo ",\"idle_baseline\":$(util_summarize "$IDLE_T0" "$IDLE_T1" "$UTILF")"
    # C5: 长上下文流式分段 (v1.9, 与 Windows 采集端对齐): 首个 content chunk 前=prefill, 其后=decode
    # 同请求内分段, 服务端 prompt cache 不影响 decode 段; 峰值/均值口径同 C2
    progress context running "C5 流式分段: prefill/decode 分离实测 (长上下文)"
    python3 - > "$TMPD/c5_stream_req.json" << 'PYEOF'
import json
para = '智能制造通过工业物联网、人工智能、大数据分析和数字孪生技术的深度融合，实现生产过程的自主感知、自主决策和自主执行。智能工厂中设备互联产生海量数据，边缘计算节点负责实时预处理，云端平台承担模型训练与全局优化。机器视觉引入质检环节后缺陷识别准确率大幅提升。预测性维护系统通过振动温度等传感器数据判断设备健康状态，显著压缩非计划停机时间。'
open('/dev/stdout','w').write(json.dumps({"messages":[{"role":"user","content":para*12+"，请用50字总结核心"}],"max_tokens":120,"stream":True,"stream_options":{"include_usage":True},"chat_template_kwargs":{"enable_thinking":False}}))
PYEOF
    T0=$(date +%s.%N)
    curl -s --max-time 380 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d @"$TMPD/c5_stream_req.json" \
      | python3 -c '
import sys, json, time
t0 = time.time()
first = last = None
ts, usage = [], None
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
        continue
    try:
        d = json.loads(line[5:])
    except Exception:
        continue
    if d.get("usage"):
        usage = d["usage"]
    ch = (d.get("choices") or [{}])[0]
    if (ch.get("delta") or {}).get("content"):
        now = time.time() - t0
        if first is None:
            first = now
        last = now
        ts.append(now - first)
json.dump({"ts": ts, "first": first, "last": last, "usage": usage}, open("/dev/stdout","w"))
' > "$TMPD/c5_stream.json"
    T1=$(date +%s.%N)
    echo ",\"c5_ctx_decode\":$(python3 << PYEOF
import json
d = json.load(open("$TMPD/c5_stream.json"))
ts = d.get("ts", []); first = d.get("first"); last = d.get("last")
usage = d.get("usage") or {}
ct5 = usage.get("completion_tokens", -1)
ct5_src = "流式 usage" if ct5 > 0 else "回退 C4 非流式 usage"
if ct5 < 0:
    try:
        ct5 = json.load(open("$TMPD/longr.json")).get("usage", {}).get("completion_tokens", -1)
    except Exception:
        pass
# C2 单路基准速度 → 衰减判定
try:
    _c2 = json.load(open("$TMPD/c2_stream.json"))
    single_tps = _c2["chunks"] / (_c2["ts"][-1]) if _c2.get("ts") else 0
except Exception:
    single_tps = 0
prefill_s = first if first else 0
decode_s = (last - first) if (first and last and last > first) else 0
dec_tps = ct5 / decode_s if (ct5 > 0 and decode_s > 0) else 0
drop5 = ((single_tps - dec_tps) / single_tps * 100) if (single_tps > 0 and dec_tps > 0) else None
peak = mean = None
if len(ts) >= 4 and decode_s > 0:
    t = [0.0] + ts
    span = t[-1] - t[0]
    mean = (len(t) - 2) / span if span > 0 else 0
    pk, i = 0.0, 0
    for j in range(len(t)):
        while t[j] - t[i] > 1.0:
            i += 1
        w = t[j] - t[i]
        if w > 0.05 and (j - i) / w > pk:
            pk = (j - i) / w
    if mean > 0:
        peak, mean = round(pk, 1), round(mean, 1)
import sys as _s
json.dump({
  "prefill_s": round(prefill_s, 3), "decode_s": round(decode_s, 3),
  "decode_tps": round(dec_tps, 1), "completion_tokens": ct5,
  "speed_peak_tps": peak, "speed_mean_tps": mean,
  "drop_pct": round(drop5, 1) if drop5 is not None else None,
  "ok": (1 if drop5 < 20 else 0) if drop5 is not None else None,
  "method": "流式同请求分段（首 content chunk 前=prefill，其后=decode）；token 源：" + ct5_src + "；服务若有 prompt cache 会影响 prefill 绝对值，不影响 decode 段",
}, _s.stdout, ensure_ascii=False)
PYEOF
)"
    progress context done "长输入+C5 分段采集结束"
    # C6/C7: 并发能力上探 (v1.8): 单路基准 → 2/4/8/16/32 倍增阶梯, 每档全部成功
    # 且单路耗时较基准衰减 <30% 才继续, 首个失败档的前一档 = 最大无衰减并发 (conc_max)
    progress context done "长输入+C5 分段采集完成"
    progress concurrency running "并发阶梯上探: 单路基准 → 2/4/8/16/32 逐档倍增"
    # 单路基准请求 (与阶梯同规格: 200 max_tokens 生成), 作为衰减判定基准
    T0=$(date +%s.%N)
    curl -s --max-time 380 "$API/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"messages":[{"role":"user","content":"请写200字短文，主题编号0：介绍一项工业技术"}],"max_tokens":200,"stream":false,"chat_template_kwargs":{"enable_thinking":false}}' \
      -o "$TMPD/par_0.json"
    T1=$(date +%s.%N)
    BASE_OK=$(python3 -c "import json; json.load(open('$TMPD/par_0.json'))['choices'][0]['message']['content']" 2>/dev/null && echo 1 || echo 0)
    BASE_TOK=$(python3 -c 'import json; print(json.load(open("'$TMPD'/par_0.json")).get("usage",{}).get("completion_tokens",-1))' 2>/dev/null || echo -1)
    BASE_WALL=$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}')
    echo ",\"conc_baseline\":{\"ok\":$BASE_OK,\"wall_s\":$BASE_WALL,\"completion_tokens\":$BASE_TOK,\"npu\":$(util_summarize "$T0" "$T1" "$UTILF")}"
    CONC_MAX=0
    if [ "$BASE_OK" = 1 ]; then
      CONC_MAX=1
      for N in 2 4 8 16 32; do
        progress concurrency running "执行 ${N} 路并发请求"
        T0=$(date +%s.%N)
        CUR_PIDS=""
        for i in $(seq 1 $N); do
          curl -s --max-time 380 "$API/v1/chat/completions" -H 'Content-Type: application/json' \
            -d "{\"messages\":[{\"role\":\"user\",\"content\":\"请写200字短文，主题编号${i}：介绍一项工业技术\"}],\"max_tokens\":200,\"stream\":false,\"chat_template_kwargs\":{\"enable_thinking\":false}}" \
            -o "$TMPD/par_${i}.json" &
          CUR_PIDS="$CUR_PIDS $!"
        done
        wait $CUR_PIDS
        T1=$(date +%s.%N)
        OKN=0; CTOK=0
        for i in $(seq 1 $N); do
          if python3 -c "import json; json.load(open('$TMPD/par_${i}.json'))['choices'][0]['message']['content']" 2>/dev/null; then
            OKN=$((OKN+1))
            T=$(python3 -c 'import json; print(json.load(open("'$TMPD'/par_${i}.json")).get("usage",{}).get("completion_tokens",-1))' 2>/dev/null || echo -1)
            [ "$T" -gt 0 ] 2>/dev/null && CTOK=$((CTOK+T))
          fi
        done
        WALLN=$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}')
        # 衰减判定: 本档耗时 vs 基准。有 usage 时按"本档完成 token 量折算串行基准份数"修正;
        # 无 usage 时退化口径 wall/路数 (已知坑: 引擎并发响应可能不回 usage, 此时判 wall_s)
        VERDICT=$(python3 -c "
ok=$OKN; n=$N; wall=$WALLN; bw=$BASE_WALL; ctok=$CTOK
if ok < n:
    print('fail')
else:
    equiv = (ctok / 200.0) if ctok > 0 else float(n)
    per = wall / equiv if equiv > 0 else wall
    drop = (per - bw) / bw * 100 if bw > 0 else 0
    print('ok' if drop < 30 else 'degraded')")
        echo ",\"c6c7_conc${N}\":{\"ok\":$OKN,\"total\":$N,\"wall_s\":$WALLN,\"completion_tokens\":$CTOK,\"verdict\":\"$VERDICT\",\"npu\":$(util_summarize "$T0" "$T1" "$UTILF")}"
        if [ "$VERDICT" = "ok" ]; then
          CONC_MAX=$N
        else
          if [ "$VERDICT" = "degraded" ]; then
            log "并发 ${N} 路全部成功但单路衰减 ≥30%, 上探终止 (conc_max=$CONC_MAX)"
          else
            log "并发 ${N} 路有失败请求, 上探终止 (conc_max=$CONC_MAX)"
          fi
          break
        fi
      done
    else
      log "⚠ 单路基准请求失败, 并发阶梯跳过"
    fi
    echo ",\"conc_max\":$CONC_MAX"
    progress concurrency done "并发上探结束: 最大无衰减并发 ${CONC_MAX} 路"
    progress tools running "验证 function calling 响应"
    TR=$(curl -s --max-time 100 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"北京现在天气怎么样？请帮我查一下"}],
      "max_tokens":300,"stream":false,
      "tools":[{"type":"function","function":{"name":"get_weather","description":"获取城市实时天气","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],
      "tool_choice":"auto","chat_template_kwargs":{"enable_thinking":false}}')
    TOOK=$(echo "$TR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(1 if d["choices"][0].get("finish_reason")=="tool_calls" else 0)' 2>/dev/null || echo -1)
    echo ",\"c8_toolcall\":{\"ok\":$TOOK}"
    # C9: 多轮对话
    if [ "$TOOK" = 1 ]; then progress tools done "收到工具调用响应"; else progress tools failed "未收到预期工具调用响应，详见原始 JSON"; fi
    progress memory running "验证多轮对话中的设备编号召回"
    MR=$(curl -s --max-time 200 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"我的设备编号是 BX-7788，请记住它"},
                  {"role":"assistant","content":"好的，已记住您的设备编号 BX-7788。"},
                  {"role":"user","content":"我刚才说的设备编号是多少？只回答编号即可"}],
      "max_tokens":50,"stream":false,"chat_template_kwargs":{"enable_thinking":false}}')
    MOK=$(echo "$MR" | python3 -c 'import json,sys; print(1 if "BX-7788" in json.load(sys.stdin)["choices"][0]["message"]["content"] else 0)' 2>/dev/null || echo -1)
    echo ",\"c9_multiturn\":{\"ok\":$MOK}"
    # C10: 加速卡显存
    if [ "$MOK" = 1 ]; then progress memory done "设备编号召回结束"; else progress memory failed "设备编号未正确召回，详见原始 JSON"; fi
    progress resources running "读取加速器显存"
    VMEM=$(mthreads-gmi 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && NF>4 {print $5; exit}')
    echo ",\"c10_vram\":\"$VMEM\""
    # C3: 首字延迟 TTFT
    if [ -n "$VMEM" ]; then progress resources done "显存数据采集结束"; else progress resources skipped "当前管理工具未返回显存数据"; fi
    progress latency running "执行流式短请求，采集原脚本定义的延迟口径"
    T0=$(date +%s.%N)
    curl -sN --max-time 120 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"你好"}],
      "max_tokens":30,"stream":true,"chat_template_kwargs":{"enable_thinking":false}}' | head -c 200 > /dev/null
    T1=$(date +%s.%N)
    echo ",\"c3_ttft\":{\"s\":$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}')}"
    # C12: 输出质量样本
    progress latency done "延迟采集结束；具体计时口径见报告"
    echo "$R1" | python3 -c 'import json,sys
try:
    c=json.load(sys.stdin)["choices"][0]["message"].get("content","")
except Exception:
    c=""
open("'$TMPD'/c12.txt","w").write(c[:80])' 2>/dev/null || : > "$TMPD/c12.txt"
    python3 -c 'import json; open("'$TMPD'/c12j.txt","w").write(json.dumps(open("'$TMPD'/c12.txt").read()))' 2>/dev/null || echo -n '""' > "$TMPD/c12j.txt"
    echo ",\"c12_sample\":$(cat $TMPD/c12j.txt)"
    # 停采样器 + 全场综合利用率(空闲基线之后到测试结束)
    UTIL_END_TS=$(date +%s.%N)
    UTILF=$(util_stop)
    echo ",\"util_overall\":$(util_summarize "$IDLE_T1" "$UTIL_END_TS" "$UTILF")"
    # 温度峰值单独留 (全场含空闲)
    echo ",\"session_temp_max\":$(python3 -c "
import json
try:
    us=[l.split() for l in open('$UTILF')]
    ts=[float(p[3]) for p in us if len(p)>=4 and float(p[3])>=0]
    print(max(ts) if ts else -1)
except Exception: print(-1)")"
    echo "}"
  } > "$TMPD/phasec_fragment.json"
  # Correct execution status when API responses are missing or incomplete.
  python3 - "$TMPD/phasec_fragment.json" <<'PYLIVE' >&2
import json, sys
try:
    c = json.load(open(sys.argv[1]))
    checks = [('decode', c.get('c2_short_decode', {}).get('reply_len', -1) <= 0),
              ('context', c.get('c4_long_ctx', {}).get('ok') != 1),
              ('concurrency', c.get('conc_max', 0) < 1)]
    for stage, bad in checks:
        if bad:
            print('@@BOXBENCH_EVENT ' + json.dumps(dict(stage=stage, status='failed', detail='请求结果不完整或未收到有效响应，详见原始 JSON'), ensure_ascii=False), flush=True)
except (ValueError, OSError):
    pass
PYLIVE
}

# ---------- 服务生命周期 (multi 模式用) ----------
stop_model_service() {
  # 停掉占用 BOX_PORT 的 llama-server
  pkill -f "llama-server.*--port $PORT" 2>/dev/null
  # 等待端口释放 (最多60s)
  for i in $(seq 1 30); do
    ss -tln | grep -q ":$PORT " || break
    sleep 2
  done
  ss -tln | grep -q ":$PORT " && log "⚠ 端口 $PORT 仍被占用" || log "服务已停止(端口 $PORT 释放)"
}

start_model_service() {
  # $1 = 模型文件绝对路径; $2 = ctx-size (默认 8192)
  local MODEL_PATH="$1"
  local SCTX="${2:-8192}"
  export LD_LIBRARY_PATH="$ENGINE_LIB:$LD_LIBRARY_PATH"
  log "启动服务: $MODEL_PATH (端口 $PORT, ctx=$SCTX)"
  setsid "$ENGINE" -m "$MODEL_PATH" -dev 0 -ngl 999 \
    --host 0.0.0.0 --port "$PORT" --jinja --ctx-size "$SCTX" \
    > /tmp/boxbench_server_$PORT.log 2>&1 < /dev/null &
  # 等待 /health 就绪 (最多300s, 每5s探测)
  local T0=$(date +%s)
  for i in $(seq 1 60); do
    if curl -s --max-time 3 "$API/health" 2>/dev/null | grep -q '"ok"'; then
      LOAD_S=$(( $(date +%s) - T0 ))
      log "服务就绪, 加载耗时 ${LOAD_S}s"
      echo "$LOAD_S"
      return 0
    fi
    sleep 5
  done
  log "⚠ 服务启动超时(300s)"
  echo "-1"
  return 1
}

# ---------- 引擎信息采集 (engine 段: 框架/版本/完整启动命令) ----------
collect_engine_info() {
  # $1 = 模型路径(multi 模式); 无参时只记全局信息
  local MPATH="${1:-}"
  # 引擎名与版本: 优先 --version 输出, 退化用二进制名+目录名
  local ENAME EBUILD
  ENAME=$(basename "$ENGINE" 2>/dev/null)
  if command -v "$ENGINE" >/dev/null 2>&1; then
    local VOUT
    VOUT=$(LD_LIBRARY_PATH="$ENGINE_LIB:${LD_LIBRARY_PATH:-}" timeout 10 "$ENGINE" --version 2>&1 | head -2 | tr '\n' ' ')
    [ -n "$VOUT" ] && ENAME="$VOUT"
  fi
  # 构建标识从引擎目录名/版本文件猜
  EBUILD=$(basename "$(dirname "$(dirname "$ENGINE")")" 2>/dev/null)
  [ -s "$(dirname "$ENGINE")/../version.txt" ] && EBUILD=$(cat "$(dirname "$ENGINE")/../version.txt" 2>/dev/null | head -1)
  # 实际启动命令行 (从运行中的 llama-server 进程抓, 最真实)
  local CMDLINE=""
  CMDLINE=$(tr '\0' ' ' < /proc/$(pgrep -f "llama-server.*--port $PORT" | head -1)/cmdline 2>/dev/null | tr -s ' ')
  [ -z "$CMDLINE" ] && CMDLINE="$ENGINE -m ${MPATH:-<model>} -dev 0 -ngl 999 --host 0.0.0.0 --port $PORT --jinja --ctx-size 8192"
  # 从命令行/模型文件名提取关键参数
  local CTX=""
  CTX=$(echo "$CMDLINE" | grep -oE '\-\-ctx-size[= ][0-9]+' | grep -oE '[0-9]+')
  [ -z "$CTX" ] && CTX=$(echo "$CMDLINE" | grep -oE '\-c [0-9]+' | grep -oE '[0-9]+')
  local MFSIZE=""; local MQUANT=""
  if [ -n "$MPATH" ] && [ -f "$MPATH" ]; then
    MFSIZE=$(du -h "$MPATH" 2>/dev/null | cut -f1)
    MQUANT=$(basename "$MPATH" | grep -oE '(w[0-9]a[0-9]+|Q[0-9]_[A-Z_0-9]+|int[0-9]+|iq[0-9]_[a-z0-9_]+)' | head -1)
  fi
  # 模型自报上下文(服务端 /props 或 /v1/models 常含), 尽力取
  local MCTX=""
  MCTX=$(curl -s --max-time 3 "$API/props" 2>/dev/null | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get("default_generation_settings",{}).get("n_ctx") or d.get("total_slots",""))
except Exception: pass' 2>/dev/null)
  # 输出 JSON 片段 (每行 "key":value, 行间逗号由调用方拼; 值均已 json.dumps 转义)
  printf '"engine_name":%s,\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$ENAME")"
  printf '"engine_build":%s,\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$EBUILD")"
  printf '"engine_bin":%s,\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$ENGINE")"
  printf '"engine_cmd":%s,\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$CMDLINE")"
  printf '"ctx_size":%s,\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "${CTX:-$MCTX}")"
  printf '"model_file_size":%s,\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$MFSIZE")"
  printf '"model_quant":%s\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$MQUANT")"
}

# ---------- 分类: 硬件分档 + 推荐模型清单 ----------
phase_classify() {
  log "硬件分档 + 模型区间匹配 (依据 HARDWARE_MODEL_MATRIX v1.0)"
  MEM_GB=$(free -g | awk '/Mem:/{print $2}')
  ACC_MEM_GB=""
  if command -v mthreads-gmi >/dev/null 2>&1; then
    V=$(mthreads-gmi 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && NF>4 && match($5, /\(([0-9]+)MiB\)/) {print substr($5, RSTART+1, RLENGTH-5); exit}')
    [ -n "$V" ] && [ "$V" -gt 0 ] 2>/dev/null && ACC_MEM_GB=$(( V / 1024 ))
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    V=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    [ -n "$V" ] && ACC_MEM_GB=$(( V / 1024 ))
  fi
  INFER_MEM=${ACC_MEM_GB:-$MEM_GB}
  # 62GB 即判 D5：carve-out/系统占用会让 64GB 统一内存报成 60~63GB（百应 395 实测踩中）
  if   [ "$INFER_MEM" -ge 62 ]; then TIER=D5
  elif [ "$INFER_MEM" -ge 28 ]; then TIER=D4
  elif [ "$INFER_MEM" -ge 14 ]; then TIER=D3
  elif [ "$INFER_MEM" -ge 7 ];  then TIER=D2
  else TIER=D1; fi
  {
    if [ -s "$TMPD/out.json" ]; then echo ",\"classification\":{"; else echo "{\"classification\":{"; fi
    echo "\"tier\":\"$TIER\""
    echo ",\"infer_mem_gb\":\"$INFER_MEM\""
    echo ",\"system_mem_gb\":\"$MEM_GB\""
    echo ",\"accel_mem_gb\":\"${ACC_MEM_GB:-N/A}\""
    echo ",\"recommended_models\":["
    case "$TIER" in
      D1) echo '"Qwen3-1.7B(Q4)","MiniCPM-4-2B(int4)","bge-m3-embedding"' ;;
      D2) echo '"Qwen3-4B(Q4)","Qwen3-8B(Q4)","GLM-4-9B(Q4)","PaddleOCR"' ;;
      D3) echo '"Qwen3-14B(Q4)","Qwen3-30B-A3B(Q4)","Qwen3-Coder-30B-A3B(Q4_K_M)","DeepSeek-R1-Distill-32B(Q4)"' ;;
      D4) echo '"Qwen3.6-35B-A3B(W4A8)","Qwen3.8-27b-mtp(W4A8)","GPT-OSS_20b(W4A8)"' ;;
      D5) echo '"Qwen2.5-72B(Q4)","Qwen3-Next-80B-A3B(Q4)","Llama-3.3-70B(Q4)"' ;;
    esac
    echo "]"
    echo ",\"skip_rule\":\"模型档位M vs 设备档位D: M>=D+2→硬件不支持; M<=D-2→不必要验证\""
    echo "}"
  } >> "$TMPD/out.json"
}

# ---------- 资源预检 (multi 模式, 每模型启动前) ----------
# 返回: ok | disk_short:<need>GB,avail:xx | mem_short:...
precheck_resources() {
  local MPATH="$1"
  local FSIZE_MB=$(du -m "$MPATH" 2>/dev/null | cut -f1)
  local DISK_AVAIL_MB=$(df -m / | awk 'NR==2{print $4}')
  # 磁盘预检只针对"还需下载/拷贝"的场景: 模型文件已在盘上时不占用额外磁盘, 只留 2GB 运行缓冲
  if [ "$DISK_AVAIL_MB" -lt 2048 ] 2>/dev/null; then
    echo "disk_short:需~2GB运行缓冲,磁盘可用$(( DISK_AVAIL_MB/1024 ))GB"
    return 1
  fi
  # 内存: W4A8/AWQ 量化权重 ≈ 文件大小×1.15(权重+KV/激活开销), 需 < 推理内存
  local INFER_MEM_MB
  INFER_MEM_MB=$(free -m | awk '/Mem:/{print $2}')
  if command -v mthreads-gmi >/dev/null 2>&1; then
    V=$(mthreads-gmi 2>/dev/null | awk 'NR>2 && match($5,/\(([0-9]+)MiB\)/) {print substr($5,RSTART+1,RLENGTH-5); exit}')
    [ -n "$V" ] && [ "$V" -gt 0 ] 2>/dev/null && INFER_MEM_MB=$V
  fi
  if [ $(( FSIZE_MB * 115 / 100 )) -gt "$INFER_MEM_MB" ] 2>/dev/null; then
    echo "mem_short:需~$(( FSIZE_MB*115/100/1024 ))GB推理内存,实际$(( INFER_MEM_MB/1024 ))GB"
    return 1
  fi
  echo "ok"
  return 0
}

# ---------- multi: 多模型顺序测试 ----------
phase_multi() {
  shift  # 跳过 "multi"
  local SPECS=("$@")
  if [ ${#SPECS[@]} -eq 0 ]; then
    log "用法: boxbench.sh multi \"模型名|模型路径\" [\"模型名2|模型路径2\" ...]"
    exit 1
  fi
  log "多模型顺序测试: ${#SPECS[@]} 个模型"
  # 结果数组
  FIRST=1
  for spec in "${SPECS[@]}"; do
    MNAME="${spec%%|*}"
    MPATH="${spec#*|}"
    log "===== 模型: $MNAME ====="
    progress_model "$MNAME"
    progress service running "模型资源预检与服务加载"
    if [ ! -f "$MPATH" ]; then
      log "⚠ 模型文件不存在: $MPATH, 跳过"
      progress service skipped "模型文件不存在"
      skip_model_steps "模型文件不存在"
      if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
      echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"error\":\"file_not_found\"}"
      continue
    fi
    # 资源预检: 磁盘/内存不足 → 记录并跳过(报告体现"暂未测试")
    PRECHECK=$(precheck_resources "$MPATH")
    if [ "$PRECHECK" != "ok" ]; then
      log "⚠ 资源预检失败: $PRECHECK, 跳过 $MNAME"
      progress service skipped "$PRECHECK"
      skip_model_steps "模型资源预检未通过"
      if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
      echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"error\":\"resource_short\",\"reason\":\"$PRECHECK\"}"
      continue
    fi
    # 停旧服务,起新服务
    stop_model_service
    LOAD_S=$(start_model_service "$MPATH")
    if [ "$LOAD_S" = "-1" ]; then
      log "服务启动失败, 记录并继续"
      progress service failed "服务启动失败或超时"
      skip_model_steps "模型服务启动失败"
      if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
      echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"error\":\"service_start_failed\"}"
      continue
    fi
    # 阶段C测试
    phase_collect
    # 组装该模型的结果 (engine 配置段与测试结果并列; 阶段E Agent 集成与该模型绑定)
    if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
    progress agent running "Agent 框架集成测试 (OpenClaw, 模型: $MNAME)"
    echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"c1_load_s\":$LOAD_S,\"engine\":{$(collect_engine_info "$MPATH")},\"phase_c\":$(cat "$TMPD/phasec_fragment.json"),\"phase_e\":$(phase_agent)}"
  done
  [ $FIRST -eq 0 ] && echo "]"
}

# ---------- ctxtest: 上下文阶梯测试 (验证模型标称窗口) ----------
# 用法: boxbench.sh ctxtest "模型名|模型路径" ["32k,128k,max"]
# 阶梯默认 32k,128k,max(模型自报上限); 每档: 重启服务(ctx=档位) →
# 构造 ~55% 窗口长输入(内嵌暗号 CTXPROBE-XXXX) → prefill速度+暗号召回+显存
# 目的: 8K ctx 的 C1~C12 不涉及大窗口; 标称 128K/256K 是否真实、显存涨多少, 由本测试回答
phase_ctxtest() {
  shift  # 跳过 "ctxtest"
  local SPEC="$1"; local LADDER="${2:-32k,128k,max}"
  MNAME="${SPEC%%|*}"; MPATH="${SPEC#*|}"
  if [ ! -f "$MPATH" ]; then
    echo "{\"error\":\"file_not_found\",\"name\":\"$MNAME\"}"; return
  fi
  # 模型自报窗口上限 (从运行服务的 /props 取; 先用 8192 起服务探一次)
  stop_model_service
  local LOAD_S=$(start_model_service "$MPATH" 8192)
  if [ "$LOAD_S" = "-1" ]; then
    echo "{\"error\":\"service_start_failed\",\"name\":\"$MNAME\"}"; return
  fi
  local MAXCTX
  MAXCTX=$(curl -s --max-time 5 "$API/props" 2>/dev/null | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get("default_generation_settings",{}).get("n_ctx") or 0)
except Exception: print(0)')
  [ -z "$MAXCTX" ] || [ "$MAXCTX" = "0" ] && MAXCTX=8192
  log "模型自报窗口上限: $MAXCTX"

  local FIRST=1
  echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"claimed_max_ctx\":$MAXCTX,\"levels\":["
  IFS=',' read -ra LEVELS <<< "$LADDER"
  for L in "${LEVELS[@]}"; do
    # 解析档位: 32k→32768; max→模型自报上限; 超上限截断为上限
    local N
    if [ "$L" = "max" ]; then N=$MAXCTX
    else N=$((${L%k} * 1024)); fi
    [ "$N" -gt "$MAXCTX" ] && { log "档位 ${L} 超模型上限, 截断为 $MAXCTX"; N=$MAXCTX; }
    # 去重: 与 max 相同的截断档跳过
    local DUP=0
    if [ "$L" != "max" ] && [ "$N" = "$MAXCTX" ] && echo " ${LEVELS[*]} " | grep -q " max "; then DUP=1; fi
    [ "$DUP" = "1" ] && continue
    log "===== ctx 阶梯: $L ($N) ====="
    stop_model_service
    local LS=$(start_model_service "$MPATH" "$N")
    if [ "$LS" = "-1" ]; then
      [ $FIRST -eq 1 ] && FIRST=0 || echo ","
      echo "{\"level\":\"$L\",\"ctx\":$N,\"error\":\"service_start_failed\"}"
      continue
    fi
    # 构造 ~55% 窗口长输入, 头部埋暗号 CTXPROBE-<4位>
    local TOKEN=$(( (N * 55 / 100) ))
    local SECRET="CTXPROBE-$(head -c4 /dev/urandom | od -An -tx4 | tr -d ' \n' | cut -c1-4)"
    python3 - "$TOKEN" "$SECRET" > "$TMPD/ctxreq.json" << 'PYEOF'
import json, sys
ntok = int(sys.argv[1]); secret = sys.argv[2]
# 每段约 18 汉字 ≈ 18 token (中文近似 1字1token)
para = "工业互联网平台通过边缘计算节点实时采集产线传感器数据，"
reps = max(1, ntok // 18)
content = f"重要暗号：{secret}。请记住。" + para * reps + "我刚才给你的重要暗号是什么？只回答暗号本身。"
open('/dev/stdout','w').write(json.dumps({"messages":[{"role":"user","content":content}],"max_tokens":32,"stream":False,"chat_template_kwargs":{"enable_thinking":False}))
PYEOF
    local T0=$(date +%s.%N)
    curl -s --max-time 580 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d @"$TMPD/ctxreq.json" > "$TMPD/ctxr.json"
    local T1=$(date +%s.%N)
    # 结果解析: prefill tok/s + 暗号召回 + usage
    local RES
    RES=$(python3 -c "
import json
try:
    d=json.load(open('$TMPD/ctxr.json')); u=d.get('usage',{})
    pt=u.get('prompt_tokens',-1); ct=u.get('completion_tokens',-1)
    ans=d['choices'][0]['message'].get('content','')
    hit=1 if '$SECRET' in ans else 0
    import sys
    print('{\"prompt_tokens\":%d,\"completion_tokens\":%d,\"secret_hit\":%d,\"answer\":%s}' % (pt,ct,hit,json.dumps(ans[:60],ensure_ascii=False)))
except Exception as e:
    print('{\"error\":\"%s\"}' % str(e)[:60])
" 2>/dev/null || echo '{"error":"parse_failed"}')
    # 显存读数
    local VMEM
    VMEM=$(mthreads-gmi 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && NF>4 {print $5; exit}')
    [ -z "$VMEM" ] && VMEM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null | head -1)
    [ $FIRST -eq 1 ] && FIRST=0 || echo ","
    echo "{\"level\":\"$L\",\"ctx\":$N,\"load_s\":$LS,\"wall_s\":$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}'),\"vram\":\"$VMEM\",\"result\":$RES}"
  done
  echo "]"
  stop_model_service
}

# ---------- 阶段 E: OpenClaw Agent 框架集成测试 (Linux 默认, 未装自动跳过) ----------
# C8 只验证"模型会发起 tool_call"(API 层模拟); 阶段 E 验证"模型在 OpenClaw 框架里真能把活干成":
# 真实工具执行循环 / 多步链 / 输出预算截断 / parser 回退路径。
# 环境变量:
#   BOX_OPENCLAW       openclaw 可执行文件路径 (默认自动探测 PATH 中 openclaw)
#   BOX_OPENCLAW_PORT  OpenClaw 网关端口 (默认 18789, 探测用)
#   BOX_AGENT_SKIP=1   强制跳过阶段 E
#   BOX_AGENT_AUTOINSTALL=0  关闭 OpenClaw 自动安装 (默认 Linux 未装时自动安装)
# 输出: JSON 对象 {env, e2_chat, e3_tool, e4_chain, e5_budget, e6_fallback}
# 跨平台超时: Linux 用 timeout, macOS/BSD 无 timeout 时退化为裸调用 (设备为 Linux, 不影响产线)
if command -v timeout >/dev/null 2>&1; then
  OC_TIMEOUT() { timeout "$@"; }
else
  OC_TIMEOUT() { local t="$1"; shift; "$@"; }
fi
oc_send() { # $1=消息文本 $2=超时s -> stdout: openclaw 响应; 副作用: OC_WALL_S
  local MSG="$1" TO="${2:-120}"
  local T0=$(date +%s.%N)
  local OUT
  OUT=$(OC_TIMEOUT "$TO" "$OPENCLAW" --non-interactive --message "$MSG" 2>>"$RUNLOG" || echo "__OC_FAILED__")
  local T1=$(date +%s.%N)
  OC_WALL_S=$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}')
  echo "$OUT"
}

phase_agent() {
  # 前置: 仅 Linux; Windows 无 OpenClaw 部署形态
  if [ "$(uname -s)" != "Linux" ] || [ "${BOX_AGENT_SKIP:-0}" = "1" ]; then
    echo "{\"skipped\":\"not_linux_or_disabled\"}"
    progress agent skipped "非 Linux 环境或 BOX_AGENT_SKIP=1, 跳过 Agent 集成测试"
    return
  fi
  OPENCLAW="${BOX_OPENCLAW:-$(command -v openclaw 2>/dev/null)}"
  OC_PORT="${BOX_OPENCLAW_PORT:-18789}"
  # E0: 未装 OpenClaw 时主动安装 (v1.12.0 双路: 先无 sudo 用户态安装, 失败再退官方 install.sh)
  # 背景: 官方 install.sh 需 sudo 装 Node/构建工具, 无免密 sudo 的设备账号会第 1 步即失败。
  # 用户态路径: Node 官方 tar.gz 解压到 ~/.local/node + npm prefix ~/.local, 全程零 root。
  # 环境变量: BOX_AGENT_AUTOINSTALL=0 关闭; BOX_AGENT_NODE_VERSION 自定义 Node 版本 (默认 v22.14.0)
  if [ -z "$OPENCLAW" ] && [ "${BOX_AGENT_AUTOINSTALL:-1}" = "1" ]; then
    progress agent running "未检测到 openclaw, 正在自动安装 (优先无 sudo 用户态安装, 约1-3分钟)"
    log "阶段E: 未装 OpenClaw, 开始自动安装 (用户态优先)"
    oc_autoinstall_ok=0
    # --- 路径1: 无 sudo 用户态安装 (aarch64/x86_64 Linux) ---
    OC_NODE_VER="${BOX_AGENT_NODE_VERSION:-v22.14.0}"
    case "$(uname -m)" in
      aarch64|arm64) OC_NODE_ARCH="arm64";;
      x86_64)        OC_NODE_ARCH="x64";;
      *)             OC_NODE_ARCH="";;
    esac
    if [ -n "$OC_NODE_ARCH" ] && command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
      progress agent running "用户态安装 Node $OC_NODE_VER ($OC_NODE_ARCH) 到 ~/.local/node"
      if [ ! -x "$HOME/.local/node/bin/node" ]; then
        curl -fsSL --max-time 240 -o /tmp/.boxbench_node.tar.xz \
          "https://nodejs.org/dist/$OC_NODE_VER/node-$OC_NODE_VER-linux-$OC_NODE_ARCH.tar.xz" >>"$RUNLOG" 2>&1 \
          && tar -xJf /tmp/.boxbench_node.tar.xz -C "$HOME/.local" >>"$RUNLOG" 2>&1 \
          && mv "$HOME/.local/node-$OC_NODE_VER-linux-$OC_NODE_ARCH" "$HOME/.local/node" >>"$RUNLOG" 2>&1 \
          && rm -f /tmp/.boxbench_node.tar.xz
      fi
      if [ -x "$HOME/.local/node/bin/node" ]; then
        PATH="$HOME/.local/node/bin:$PATH"
        progress agent running "npm 安装 openclaw 到 ~/.local (用户目录, 不需要 root)"
        if mkdir -p "$HOME/.local" \
          && "$HOME/.local/node/bin/npm" config set prefix "$HOME/.local" >>"$RUNLOG" 2>&1 \
          && "$HOME/.local/node/bin/npm" install -g openclaw --no-audit --no-fund >>"$RUNLOG" 2>&1; then
          oc_autoinstall_ok=1
        fi
      fi
    fi
    # --- 路径2 (回退): 官方 install.sh (需要 sudo 时可能失败) ---
    if [ "$oc_autoinstall_ok" != "1" ]; then
      progress agent running "用户态安装未成功, 回退官方 install.sh (需 sudo 时会失败)"
      log "阶段E: 用户态安装失败, 回退 openclaw.ai/install.sh"
      curl -fsSL --proto '=https' --tlsv1.2 --max-time 300 https://openclaw.ai/install.sh | bash -s -- --no-onboard >>"$RUNLOG" 2>&1 || true
    fi
    # 安装后刷新 PATH 再探测 (~/.local/bin / npm global / 官方脚本位置)
    for PD in "$HOME/.local/bin" "$HOME/.local/node/bin" "$HOME/.npm-global/bin" /usr/local/bin; do
      case ":$PATH:" in *":$PD:"*) ;; *) PATH="$PATH:$PD";; esac
    done
    hash -r 2>/dev/null
    OPENCLAW="$(command -v openclaw 2>/dev/null)"
    if [ -z "$OPENCLAW" ]; then
      echo "{\"skipped\":\"openclaw_autoinstall_failed\"}"
      progress agent failed "OpenClaw 自动安装失败 (详见 boxbench_run_*.log); 可装好后重跑或 BOX_AGENT_AUTOINSTALL=0 跳过安装"
      return
    fi
    progress agent done "OpenClaw 自动安装成功: $OPENCLAW"
    log "OpenClaw 安装完成: $OPENCLAW"
  fi
  # E1: 网关/CLI 探活
  progress agent running "检测 OpenClaw 部署 (CLI + 网关端口 $OC_PORT)"
  local OC_VER="" OC_PROC=""
  if [ -z "$OPENCLAW" ]; then
    echo "{\"skipped\":\"openclaw_not_installed\"}"
    progress agent skipped "未检测到 openclaw CLI, 跳过 (安装后重跑或 BOX_OPENCLAW 指定路径)"
    return
  fi
  OC_VER=$(OC_TIMEOUT 10 "$OPENCLAW" --version 2>/dev/null | head -1)
  OC_PROC=$(pgrep -fc "openclaw" 2>/dev/null || echo 0)
  local GW_OK=0
  # 网关端口探测: 通/进程存在 均视为已部署 (CLI 模式可能不需要常驻网关)
  if ss -tln 2>/dev/null | grep -q ":$OC_PORT " || [ "$OC_PROC" -gt 0 ]; then GW_OK=1; fi
  if [ "$GW_OK" != "1" ]; then
    echo "{\"skipped\":\"openclaw_not_running\",\"cli\":\"$OPENCLAW\",\"version\":\"$OC_VER\"}"
    progress agent skipped "openclaw CLI 存在但网关/进程未运行"
    return
  fi
  progress agent done "OpenClaw 已部署 (v${OC_VER:-unknown}, 进程 ${OC_PROC})"
  log "阶段E: OpenClaw 集成测试开始 (CLI=$OPENCLAW, ver=$OC_VER)"
  # 注意: E2 失败时的提前收尾用 AGENT_E2_FAIL 标志控制, 不在重定向块内 return
  # (块内 return 会跳过块外的 cat, 导致 stdout 无输出)
  local AGENT_E2_FAIL=0
  {
    echo "{"
    echo "\"env\":{\"cli\":\"$OPENCLAW\",\"version\":\"$OC_VER\",\"port\":$OC_PORT,\"procs\":$OC_PROC,\"model_api\":\"$API\"}",
    # E2: 端到端单轮问答 (走 OpenClaw 网关, 记端到端耗时 vs 裸 API C2 对比开销)
    progress agent running "E2: 端到端单轮问答"
    local R EOK
    R=$(oc_send "请用一句话回答:1+1等于几?" 90)
    EOK=0; [ -n "$R" ] && [ "$R" != "__OC_FAILED__" ] && EOK=1
    echo "\"e2_chat\":{\"ok\":$EOK,\"wall_s\":$OC_WALL_S,\"reply\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1][:100], ensure_ascii=False))" "$R" 2>/dev/null || echo '""')}"
    if [ "$EOK" != "1" ]; then
      # 网关通但对话失败 → 后续工具测试大概率也失败, 直接收尾 (e3~e6 置 -1 不计分)
      echo ",\"e3_tool\":{\"ok\":-1},\"e4_chain\":{\"ok\":-1},\"e5_budget\":{\"ok\":-1},\"e6_fallback\":{\"ok\":-1}"
      progress agent failed "E2 端到端问答失败, 阶段E 提前结束"
      AGENT_E2_FAIL=1
    fi
    if [ "$AGENT_E2_FAIL" != "1" ]; then
    progress agent done "E2 通过 (${OC_WALL_S}s)"
    # E3: 单工具调用 (注册真实工具, 验证执行循环: 调用→解析→执行→回填→生成)
    progress agent running "E3: 单工具真实执行"
    R=$(oc_send "请调用 calc 工具计算 137*24 的结果,并告诉我答案" 120)
    # 成功判据: 响应含正确结果 3288 (工具真执行了) 而非模型口算(可能对也可能没用工具, 以结果为准)
    local E3=0; echo "$R" | grep -q "3288" && E3=1
    echo ",\"e3_tool\":{\"ok\":$E3,\"wall_s\":$OC_WALL_S,\"reply\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1][:150], ensure_ascii=False))" "$R" 2>/dev/null || echo '""')}"
    [ "$E3" = "1" ] && progress agent done "E3 通过: 工具结果 3288 正确回填" || progress agent failed "E3 未见工具执行结果 3288"
    # E4: 多步工具链 (需连续两次调用才能完成的任务, 暴露 parser 多步问题)
    progress agent running "E4: 多步工具链 (连续两次调用)"
    R=$(oc_send "请先用 calc 工具计算 15*8, 再用 calc 工具把上一步结果加上 470, 最后告诉我最终数字" 180)
    # 15*8=120, 120+470=590; 判据: 最终响应含 590
    local E4=0; echo "$R" | grep -q "590" && E4=1
    echo ",\"e4_chain\":{\"ok\":$E4,\"wall_s\":$OC_WALL_S,\"reply\":$(python3 -c "import json,sys; print(json.dumps(sys.argv[1][:150], ensure_ascii=False))" "$R" 2>/dev/null || echo '""')}"
    [ "$E4" = "1" ] && progress agent done "E4 通过: 多步链最终结果 590 正确" || progress agent failed "E4 多步链未得到 590"
    # E5: 输出预算 (长回复是否被 OpenClaw 输出预算截断 — 实战踩坑项)
    progress agent running "E5: 输出预算截断检查"
    R=$(oc_send "请写一篇500字左右的短文, 主题: 智能制造的未来" 150)
    local RLEN
    RLEN=$(python3 -c "import sys; print(len(sys.argv[1]))" "$R" 2>/dev/null || echo 0)
    # 判据: 响应长度 ≥400 字符视为未被严重截断 (500字要求 + 余量); 记录实际长度供人工判读
    local E5=0; [ "$RLEN" -ge 400 ] 2>/dev/null && E5=1
    echo ",\"e5_budget\":{\"ok\":$E5,\"reply_len\":$RLEN,\"min_expected\":400}"
    [ "$E5" = "1" ] && progress agent done "E5 通过: 长回复未截断 (${RLEN} 字符)" || progress agent failed "E5 疑似输出截断 (${RLEN} 字符 < 400)"
    # E6: 非流式容错 (不需要工具的问题, parser 回退纯文本路径)
    progress agent running "E6: 纯文本回退路径"
    R=$(oc_send "中国的首都是哪座城市?" 90)
    local E6=0; echo "$R" | grep -q "北京" && E6=1
    echo ",\"e6_fallback\":{\"ok\":$E6,\"wall_s\":$OC_WALL_S}"
    [ "$E6" = "1" ] && progress agent done "E6 通过" || progress agent failed "E6 未见正确回答"
    fi  # AGENT_E2_FAIL 条件结束
    echo "}"
  } > "$TMPD/phasee_fragment.json"
  progress agent done "阶段E 采集完成"
  cat "$TMPD/phasee_fragment.json"
}

# ---------- 主流程 ----------
MODE="${1:-auto}"
version_check_bg   # 后台异步版本自检, 不阻塞测试
if [ "$MODE" = "classify" ]; then
  phase_classify
elif [ "$MODE" = "ctxtest" ]; then
  # 纯 C13 测试: 直接输出 (不套 phase_a/b)
  echo "{\"boxbench_version\":\"$VERSION\",\"spec_version\":\"$SPEC_VERSION\",\"timestamp\":\"$(date -Iseconds)\",\"ctxtest\":$(phase_ctxtest "$@")}"
else
  phase_fingerprint
  phase_inventory
  progress classify running "匹配硬件档位与模型区间"
  phase_classify
  progress classify done "硬件分档结束"
  if [ "$MODE" = "auto" ]; then
    curl -s --max-time 5 "$API/health" >/dev/null 2>&1 && MODE=collect || MODE=fingerprint_only
  fi
  if [ "$MODE" = "fingerprint" ] || [ "$MODE" = "fingerprint_only" ]; then
    progress service skipped "仅采集环境，或推理服务未就绪"
    skip_model_steps "本次仅采集硬件与环境"
  fi
  if [ "$MODE" = "collect" ]; then
    phase_collect
    echo ",\"engine\":{$(collect_engine_info)}" >> "$TMPD/out.json"
    echo ",\"phase_c\":$(cat "$TMPD/phasec_fragment.json")" >> "$TMPD/out.json"
    # 阶段E: OpenClaw Agent 集成 (Linux 默认执行, 未装/非Linux 自动跳过)
    progress agent running "Agent 框架集成测试 (OpenClaw)"
    echo ",\"phase_e\":$(phase_agent)" >> "$TMPD/out.json"
  fi
  if [ "$MODE" = "multi" ]; then
    # phase_multi 输出 (models 数组) 直接写入 out.json
    phase_multi "$@" >> "$TMPD/out.json"
    # 顶层全局引擎段
    if grep -q '"models"' "$TMPD/out.json" 2>/dev/null; then
      echo ",\"engine\":{$(collect_engine_info)}" >> "$TMPD/out.json"
    fi
  fi
fi
echo "}" >> "$TMPD/out.json"
progress archive running "校验并保存原始测试 JSON"

# 校验 JSON 并输出(先清洗非法控制字符; 字符串值内换行替换为空格)
python3 -c "
import json, sys, re
raw = open('$TMPD/out.json').read()
out = []; in_str = False; esc = False
for ch in raw:
    if esc: out.append(ch); esc = False; continue
    if ch == chr(92): out.append(ch); esc = True; continue
    if ch == '\"': in_str = not in_str; out.append(ch); continue
    if in_str and ch == chr(10): out.append(' '); continue
    if in_str and ord(ch) < 32: continue
    out.append(ch)
clean = ''.join(out)
d = json.loads(clean)
json.dump(d, open('$OUT','w'), ensure_ascii=False, indent=2)
print('OK -> $OUT')
" || { progress archive failed "JSON 组装失败，已保留 raw 文件"; echo 'JSON 组装失败' >&2; cp "$TMPD/out.json" "${OUT}.raw"; exit 1; }
progress archive done "原始 JSON 已保存：$OUT；HTML 报告需另行渲染"
# 经验池 push 由 render_report.py 渲染成功后自动执行（v1.10.15），
# 此处仅标记看板环节；设备端不直接联网上传。
progress exp-push running "经验推送已就绪：本机渲染报告时自动上传（渲染器执行，幂等不重传）"
log "完成: $OUT"
log "运行日志: $RUNLOG (过程留痕, 交付时与 JSON/报告一并归档)"
