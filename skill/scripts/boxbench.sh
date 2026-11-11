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
# 产出: ./boxbench_results_{YYYYMMDD_HHMMSS}.json (stdout 输出路径)
# =============================================================
VERSION="1.5"
SPEC_VERSION="1.4"
OUT="boxbench_results_$(date +%Y%m%d_%H%M%S).json"
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT

API="${BOX_API:-http://127.0.0.1:17701}"
PORT="${BOX_PORT:-17701}"
ENGINE="${BOX_ENGINE:-/home/dev/houmoAI/houmo/houmo-HLIELLama-xh2/bin/llama-server}"
ENGINE_LIB="${BOX_ENGINE_LIB:-/home/dev/houmoAI/houmo/houmo-HLIELLama-xh2/lib}"

log() { echo "[boxbench] $*" >&2; }

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
}

# ---------- 阶段 B: 环境盘点 ----------
phase_inventory() {
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
}

# ---------- 阶段 C: 单模型测试(需要 API 端点已就绪) ----------
# 输出到 $TMPD/phasec_fragment.json (一个完整 {} 对象)
phase_collect() {
  log "阶段C: 模型实测采集 (API=$API)"
  if ! curl -s --max-time 5 "$API/health" | grep -q '"ok"'; then
    log "⚠ 服务未就绪($API/health)，跳过阶段C。"
    echo "{\"skipped\":\"service_not_ready\",\"api\":\"$API\"}" > "$TMPD/phasec_fragment.json"
    return
  fi
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
    T0=$(date +%s.%N)
    R1=$(curl -s --max-time 300 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"请写一段250字左右的短文，介绍人工智能在工业质检中的应用"}],
      "max_tokens":400,"stream":false,"chat_template_kwargs":{"enable_thinking":false}}')
    T1=$(date +%s.%N)
    echo ",\"c2_short_decode\":{\"wall_s\":$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}'),$(echo "$R1" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin); u=d.get("usage",{})
    pt=u.get("prompt_tokens",-1); ct=u.get("completion_tokens",-1)
    print("\"prompt_tokens\":%d,\"completion_tokens\":%d"% (pt,ct))
except Exception:
    print("\"prompt_tokens\":-1,\"completion_tokens\":-1")'),\"reply_len\":$(echo "$R1" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["choices"][0]["message"].get("content","")))' 2>/dev/null || echo -1),\"npu\":$(util_summarize "$T0" "$T1" "$UTILF")}"
    # C4/C5: 长上下文
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
    # C6/C7: 并发 2/4
    for N in 2 4; do
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
      echo ",\"c6c7_conc${N}\":{\"ok\":$OKN,\"total\":$N,\"wall_s\":$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}'),\"completion_tokens\":$CTOK,\"npu\":$(util_summarize "$T0" "$T1" "$UTILF")}"
    done
    # C8: 工具调用
    TR=$(curl -s --max-time 100 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"北京现在天气怎么样？请帮我查一下"}],
      "max_tokens":300,"stream":false,
      "tools":[{"type":"function","function":{"name":"get_weather","description":"获取城市实时天气","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],
      "tool_choice":"auto","chat_template_kwargs":{"enable_thinking":false}}')
    TOOK=$(echo "$TR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(1 if d["choices"][0].get("finish_reason")=="tool_calls" else 0)' 2>/dev/null || echo -1)
    echo ",\"c8_toolcall\":{\"ok\":$TOOK}"
    # C9: 多轮对话
    MR=$(curl -s --max-time 200 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"我的设备编号是 BX-7788，请记住它"},
                  {"role":"assistant","content":"好的，已记住您的设备编号 BX-7788。"},
                  {"role":"user","content":"我刚才说的设备编号是多少？只回答编号即可"}],
      "max_tokens":50,"stream":false,"chat_template_kwargs":{"enable_thinking":false}}')
    MOK=$(echo "$MR" | python3 -c 'import json,sys; print(1 if "BX-7788" in json.load(sys.stdin)["choices"][0]["message"]["content"] else 0)' 2>/dev/null || echo -1)
    echo ",\"c9_multiturn\":{\"ok\":$MOK}"
    # C10: 加速卡显存
    VMEM=$(mthreads-gmi 2>/dev/null | awk '$1 ~ /^[0-9]+$/ && NF>4 {print $5; exit}')
    echo ",\"c10_vram\":\"$VMEM\""
    # C3: 首字延迟 TTFT
    T0=$(date +%s.%N)
    curl -sN --max-time 120 "$API/v1/chat/completions" -H 'Content-Type: application/json' -d '{
      "messages":[{"role":"user","content":"你好"}],
      "max_tokens":30,"stream":true,"chat_template_kwargs":{"enable_thinking":false}}' | head -c 200 > /dev/null
    T1=$(date +%s.%N)
    echo ",\"c3_ttft\":{\"s\":$(echo "$T1 $T0" | awk '{printf "%.2f",$1-$2}')}"
    # C12: 输出质量样本
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
  if   [ "$INFER_MEM" -ge 64 ]; then TIER=D5
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
    if [ ! -f "$MPATH" ]; then
      log "⚠ 模型文件不存在: $MPATH, 跳过"
      if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
      echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"error\":\"file_not_found\"}"
      continue
    fi
    # 资源预检: 磁盘/内存不足 → 记录并跳过(报告体现"暂未测试")
    PRECHECK=$(precheck_resources "$MPATH")
    if [ "$PRECHECK" != "ok" ]; then
      log "⚠ 资源预检失败: $PRECHECK, 跳过 $MNAME"
      if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
      echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"error\":\"resource_short\",\"reason\":\"$PRECHECK\"}"
      continue
    fi
    # 停旧服务,起新服务
    stop_model_service
    LOAD_S=$(start_model_service "$MPATH")
    if [ "$LOAD_S" = "-1" ]; then
      log "服务启动失败, 记录并继续"
      if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
      echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"error\":\"service_start_failed\"}"
      continue
    fi
    # 阶段C测试
    phase_collect
    # 组装该模型的结果 (engine 配置段与测试结果并列)
    if [ $FIRST -eq 1 ]; then echo ",\"models\":["; FIRST=0; else echo ","; fi
    echo "{\"name\":\"$MNAME\",\"path\":\"$MPATH\",\"c1_load_s\":$LOAD_S,\"engine\":{$(collect_engine_info "$MPATH")},\"phase_c\":$(cat "$TMPD/phasec_fragment.json")}"
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

# ---------- 主流程 ----------
MODE="${1:-auto}"
if [ "$MODE" = "classify" ]; then
  phase_classify
elif [ "$MODE" = "ctxtest" ]; then
  # 纯 C13 测试: 直接输出 (不套 phase_a/b)
  echo "{\"boxbench_version\":\"$VERSION\",\"spec_version\":\"$SPEC_VERSION\",\"timestamp\":\"$(date -Iseconds)\",\"ctxtest\":$(phase_ctxtest "$@")}"
else
  phase_fingerprint
  phase_inventory
  phase_classify
  if [ "$MODE" = "auto" ]; then
    curl -s --max-time 5 "$API/health" >/dev/null 2>&1 && MODE=collect || MODE=fingerprint_only
  fi
  if [ "$MODE" = "collect" ]; then
    phase_collect
    echo ",\"engine\":{$(collect_engine_info)}" >> "$TMPD/out.json"
    echo ",\"phase_c\":$(cat "$TMPD/phasec_fragment.json")" >> "$TMPD/out.json"
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
" || { echo 'JSON 组装失败' >&2; cp "$TMPD/out.json" "${OUT}.raw"; exit 1; }
log "完成: $OUT"
