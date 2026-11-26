#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BoxBench v1.3.9 Windows 采集脚本 — 被测设备为 Windows 时的 boxbench.sh 等价实现
（boxbench.sh 依赖 /proc、lscpu、free、lsblk、ss、mthreads-gmi，Windows 均不可用）

用法:
  python boxbench_windows.py                     # 自动: 阶段A+B+classify + 阶段C(服务就绪则测)
  python boxbench_windows.py fingerprint         # 仅阶段A+B+classify
  python boxbench_windows.py collect             # 阶段A+B+classify + 阶段C(强制, 服务未就绪则记录跳过)
  python boxbench_windows.py --all               # 对 /v1/models 中全部 LLM 顺序实测(输出 models 数组)

选项:
  --api URL        推理服务地址 (默认 http://127.0.0.1:1234, 即 LM Studio 默认端口)
  --model NAME     指定 /v1/models 中的模型 id (默认自动取第一个非 embedding 模型)
  --thinking none|keep
                   none=注入 reasoning_effort:"none" 关闭思考 (默认, 与 SPEC 基线口径一致);
                   keep=保留思考, 自动加大 token 预算 (速度数据仍真实, 但含 reasoning token, 跨设备不可比)
  --out PATH       输出 JSON 路径 (默认 ./boxbench_results_YYYYMMDD_HHMMSS.json)

产出与 boxbench.sh 相同结构的 JSON, 直接交给 render_report.py 渲染:
  python scripts/render_report.py <result.json> [输出.html] --device <型号>

Windows 实测踩坑均已内置修正 (详见 PLATFORM_NOTES.md `lmstudio-llamacpp-rtx5060ti-x2`):
  - 显存必须用 nvidia-smi 读 (Win32_VideoController.AdapterRAM 32 位溢出, 16GB 卡报 4GB)
  - FreePhysicalMemory 单位是 KB 不是 MB
  - LM Studio 无 /health 端点, 服务探测回退 GET /v1/models + 短 chat 探测
  - Qwen3.6 等 GGUF 在 LM Studio 强制思考: chat_template_kwargs/enable_thinking//no_think
    均无效, 仅 reasoning_effort:"none" 有效
仅依赖 Python3 标准库 + 系统自带 PowerShell 5.1 / nvidia-smi。
"""
import json, os, re, sys, time, socket, subprocess, datetime, argparse, threading
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

# GBK 控制台防崩溃: stdout/stderr 强制 UTF-8 (v1.3.7 渲染器同款修正, 2026-11-25 Strix Halo 实测踩坑)
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

VERSION = "1.7.0"
SPEC_VERSION = "1.7"
AI_PORTS = [1234, 17701, 8080, 8088, 11434, 8000, 9997]  # LM Studio 默认 1234 在最前


RUNLOG_PATH = None  # main() 里初始化


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] [boxbench-win] %s" % (ts, msg)
    print(line, flush=True)
    # 过程留痕: 追加写入运行日志文件 (失败不影响主流程)
    if RUNLOG_PATH:
        try:
            with open(RUNLOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass



def progress(stage, status, detail=""):
    # Standard event protocol also works when this script is run over SSH.
    print("@@BOXBENCH_EVENT " + json.dumps(dict(stage=stage, status=status, detail=detail),
                                           ensure_ascii=False), file=sys.stderr, flush=True)


def progress_model(name):
    print("@@BOXBENCH_EVENT " + json.dumps(dict(type="model", name=name), ensure_ascii=False),
          file=sys.stderr, flush=True)


def end_step(stage, result):
    failed = isinstance(result, dict) and (bool(result.get("error")) or
             result.get("ok") == 0 or result.get("s", 0) < 0 or
             ("total" in result and result.get("ok") != result["total"]))
    progress(stage, "failed" if failed else "done",
             "测试结果异常，详见原始 JSON" if failed else "采集结束，指标结论以实测报告为准")


def skip_model_steps(reason):
    for stage in ("decode", "latency", "context", "concurrency", "tools", "memory", "resources"):
        progress(stage, "skipped", reason)


def run_ps(script, timeout=60):
    """PowerShell 5.1 执行, 强制 UTF-8 输出 (中文 Caption 防乱码). 返回 stdout 文本."""
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
           "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + script]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace")


# ---------------- 阶段 A: 硬件指纹 ----------------
def phase_fingerprint():
    log("阶段A: 硬件指纹采集 (PowerShell 等价 boxbench.sh)")
    out = {}
    raw = run_ps(r"""
$os=Get-CimInstance Win32_OperatingSystem
$cs=Get-CimInstance Win32_ComputerSystem
$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1
"hostname=$env:COMPUTERNAME"
"os=$($os.Caption)|$($os.BuildNumber)"
"kernel=$($os.Version) (Windows NT)"
"cpu=$($cpu.Name)"
"cores=$($cpu.NumberOfCores)|$($cpu.NumberOfLogicalProcessors)"
"max_mhz=$($cpu.MaxClockSpeed)"
"load_pct=$($cpu.LoadPercentage)"
"mem_total_kb=$($os.TotalVisibleMemorySize)"
"mem_free_kb=$($os.FreePhysicalMemory)"
"mem_type=$((Get-CimInstance Win32_PhysicalMemory|Select-Object -First 1).SMBIOSMemoryType)"
foreach($d in (Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3')){"ldisk=$($d.DeviceID)|$($d.Size)|$($d.FreeSpace)"}
foreach($g in (Get-CimInstance Win32_VideoController)){"wddm_gpu=$($g.Name)|$($g.DriverVersion)"}
foreach($i in (Get-NetIPAddress -AddressFamily IPv4|Where-Object{$_.IPAddress -ne '127.0.0.1'})){"net=$($i.InterfaceAlias)=$($i.IPAddress)"}
$t=Get-CimInstance Win32_TemperatureProbe -ErrorAction SilentlyContinue
"temp=$(if($t){$t.CurrentReading -join ';'}else{'NOT_AVAILABLE'})"
""")
    kv, ldisk, nets, gpus = {}, [], [], []
    for line in raw.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k == "ldisk":
            dev, size, free = v.split("|")
            ldisk.append((dev, int(size), int(free)))
        elif k == "net":
            nets.append(v)
        elif k == "wddm_gpu":
            gpus.append(v)
        else:
            kv[k] = v

    mem_total_gb = int(kv.get("mem_total_kb", "0")) / 1024 / 1024
    mem_free_gb = int(kv.get("mem_free_kb", "0")) / 1024 / 1024
    root = next((d for d in ldisk if d[0].rstrip(":").upper() == "C"), ldisk[0] if ldisk else None)
    gpu_rows = nvidia_smi()
    vram_total = sum(g["mem_total_mib"] for g in gpu_rows) if gpu_rows else 0

    # 显存一律以 nvidia-smi 为准 (WDDM AdapterRAM 溢出), nvidia-smi 不存在时才用 WDDM 行兜底
    if gpu_rows:
        acc = "; ".join("%s %d/%d MiB (driver %s)" % (g["name"], g["mem_used_mib"],
                       g["mem_total_mib"], g["driver"]) for g in gpu_rows)
    elif gpus:
        acc = "WDDM(未校准): " + "; ".join(gpus)
    else:
        acc = "N/A"

    out.update({
        "hostname": kv.get("hostname", "?"),
        "interfaces": "；".join(nets) if nets else "N/A",
        "os": "%s (build %s)" % tuple(kv.get("os", "?|?").split("|")),
        "kernel": kv.get("kernel", "?"),
        "cpu_model": kv.get("cpu", "?"),
        "cpu_arch": "x86_64 (%s)" % ("64 位" if "64" in kv.get("kernel", "") else "?"),
        "cpu_cores": "%s 核 / %s 线程" % tuple(kv.get("cores", "?|?").split("|")),
        "cpu_max_mhz": kv.get("max_mhz", "?"),
        "mem_total": "%.1f GB (SMBIOSMemoryType=%s)" % (mem_total_gb, kv.get("mem_type", "?")),
        "mem_available": "%.1f GB（采集时空闲物理内存）" % mem_free_gb,
        "root_disk": ("C: %.0fGB / 已用 %.1fGB (%.0f%% used)" %
                      (root[1] / 2**30, (root[1] - root[2]) / 2**30,
                       (root[1] - root[2]) / root[1] * 100)) if root else "N/A",
        "blocks": ("；".join("%s total=%.1fGB free=%.1fGB" % (d[0], d[1] / 2**30, d[2] / 2**30)
                             for d in ldisk) or "N/A"),
        "accelerator": acc,
        "accel_tool": "nvidia-smi" if gpu_rows else "N/A",
        "accel_mem_gb": round(vram_total / 1024, 1) if vram_total else 0,
        "gpu_temp_c": (round(sum(g["temp_c"] for g in gpu_rows) / len(gpu_rows), 1)
                       if gpu_rows else "N/A"),
        "power_limit_w": (round(gpu_rows[0]["power_limit_w"], 1) if gpu_rows else "N/A"),
        "cuda_version": cuda_version() if gpu_rows else "N/A",
        "load": "CPU 负载 %s%%（采集时）；Windows 无 load average；"
                "Win32_TemperatureProbe 不可用，GPU 温度改由 nvidia-smi 采集" %
                kv.get("load_pct", "?"),
    })
    return out, mem_total_gb, vram_total


def nvidia_smi():
    """返回 [{index,name,mem_used_mib,mem_total_mib,driver,temp_c,power_limit_w,sm_mhz}]."""
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,memory.total,memory.used,driver_version,"
             "temperature.gpu,power.limit,clocks.sm",
             "--format=csv,noheader,nounits"], capture_output=True, timeout=20)
        rows = []
        for line in r.stdout.decode("utf-8", "replace").strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 8:
                rows.append({"index": int(parts[0]), "name": parts[1],
                             "mem_total_mib": int(parts[2]), "mem_used_mib": int(parts[3]),
                             "driver": parts[4], "temp_c": float(parts[5]),
                             "power_limit_w": float(parts[6]), "sm_mhz": float(parts[7])})
        return rows
    except Exception:
        return []


def cuda_version():
    """从 nvidia-smi 头部读取 CUDA Version（B3 加速栈指纹）."""
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, timeout=10)\
                       .stdout.decode("utf-8", "replace")
        m = re.search(r"CUDA Version:\s*([\d.]+)", out)
        if m:
            return m.group(1)
        # 新版驱动头部可能不显示 CUDA Version, 从 LM Studio backend 名推断并标注来源
        for b in lm_studio_backends():
            mm = re.search(r"cuda(\d+)", b, re.I)
            if mm:
                return "%s（由 LM Studio backend 名推断）" % mm.group(1)
        return "未识别"
    except Exception:
        return "未识别"


def gpu_runtime_sample():
    """单次运行时采样: util% / power W / temp C（多卡取均值）, 供阶段C 全程采样."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, timeout=10)
        vals = []
        for line in r.stdout.decode("utf-8", "replace").strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) >= 3:
                vals.append((float(p[0]), float(p[1]), float(p[2])))
        if not vals:
            return None
        return (sum(v[0] for v in vals) / len(vals),
                sum(v[1] for v in vals) / len(vals),
                sum(v[2] for v in vals) / len(vals))
    except Exception:
        return None


def lms_ps_info():
    """读 lms ps 里的实际 CONTEXT / PARALLEL（Windows LM Studio 无原生启动命令行, 用它还原等价加载参数）."""
    try:
        exe = os.path.join(os.path.expanduser("~"), ".lmstudio", "bin", "lms.exe")
        out = subprocess.run([exe, "ps"], capture_output=True, text=True,
                             timeout=30).stdout or ""
        m = re.search(r"\b(\d{4,7})\s+(\d+)\s+(?:Local|GPU|CPU)", out)
        return {"context": int(m.group(1)), "parallel": int(m.group(2))} if m else {}
    except Exception:
        return {}


# ---------------- 阶段 B: 环境盘点 ----------------
def phase_inventory():
    log("阶段B: 环境盘点 (只读, 约1-2分钟)")
    home = os.path.expanduser("~")
    roots = [os.path.join(home, ".lmstudio", "models"),
             os.path.join(home, ".ollama", "models"),
             os.path.join(home, ".cache", "huggingface"),
             os.path.join(home, ".cache", "lm-studio"),
             os.path.join(home, "AppData", "Local", "Ollama"),
             os.path.join(home, "Downloads"),
             r"C:\models", r"D:\models", r"C:\opt", "D:\\"]
    exts = (".gguf", ".safetensors", ".onnx")
    found, deadline, seen = [], time.time() + 60, set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            if time.time() > deadline or len(found) >= 30:
                break
            if dirpath.count(os.sep) - base_depth >= 4:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and
                           d not in ("node_modules", "Windows", "System32", "Temp")]
            for fn in filenames:
                if not fn.lower().endswith(exts):
                    continue
                p = os.path.join(dirpath, fn)
                if p in seen:
                    continue
                seen.add(p)
                try:
                    st = os.stat(p)
                    if st.st_size >= 100 * 1024 * 1024:
                        found.append({"path": p, "size": "%.2f GB" % (st.st_size / 2**30),
                                      "mtime": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))})
                except OSError:
                    pass
            if len(found) >= 30:
                break
        if len(found) >= 30:
            break

    # 推理引擎探测
    engines = []
    lmver = lm_studio_version()
    if lmver:
        engines.append("LM Studio %s + backends: %s" %
                       (lmver, ", ".join(lm_studio_backends()) or "未识别"))
    for name in ("ollama", "llama-server", "vllm", "docker"):
        path = which(name)
        if path:
            engines.append("%s -> %s" % (name, path))

    # 监听端口 (socket 探测, 不依赖 ss/netstat)
    services = []
    for port in AI_PORTS:
        if port_open(port):
            services.append("127.0.0.1:%d" % port)

    gpus = nvidia_smi()
    stack = ("driver %s / CUDA %s / LM Studio backends: %s"
             % (gpus[0]["driver"] if gpus else "N/A", cuda_version(),
                ", ".join(lm_studio_backends()) or "未识别")) if gpus else "未识别"
    return {"model_files": found,
            "engine_paths": "；".join(engines) if engines else "未发现推理引擎",
            "accel_stack": stack,
            "docker": ("已安装" if which("docker") else "未安装（docker 命令不存在）"),
            "ai_services": "；".join(services) if services else "常见 AI 端口均无监听"}


def which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for ext in (".exe", ".cmd", ".bat", ""):
            p = os.path.join(d.strip('"'), name + ext)
            if os.path.isfile(p):
                return p
    return None


def port_open(port, host="127.0.0.1", timeout=0.4):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def lm_studio_version():
    try:
        raw = run_ps("(Get-Process -Name 'LM Studio' -ErrorAction SilentlyContinue "
                     "| Select-Object -First 1).ProductVersion", timeout=20)
        v = raw.strip()
        return v or None
    except Exception:
        return None


def lm_studio_backends():
    base = os.path.join(os.path.expanduser("~"), ".lmstudio", "extensions", "backends")
    try:
        return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    except OSError:
        return []


# ---------------- classify: 硬件分档 ----------------
def phase_classify(mem_total_gb, vram_total_gb):
    # 独立加速卡取 min(系统内存, 卡显存合计); 无卡取系统内存
    infer_mem = min(mem_total_gb, vram_total_gb) if vram_total_gb > 0 else mem_total_gb
    igb = int(infer_mem)
    if igb >= 64:
        tier = "D5"
    elif igb >= 28:
        tier = "D4"
    elif igb >= 14:
        tier = "D3"
    elif igb >= 7:
        tier = "D2"
    else:
        tier = "D1"
    rec = {
        "D1": ["Qwen3-1.7B(Q4)", "MiniCPM-4-2B(int4)", "bge-m3-embedding"],
        "D2": ["Qwen3-4B(Q4)", "Qwen3-8B(Q4)", "GLM-4-9B(Q4)", "PaddleOCR"],
        "D3": ["Qwen3-14B(Q4)", "Qwen3-30B-A3B(Q4)", "Qwen3-Coder-30B-A3B(Q4_K_M)",
               "DeepSeek-R1-Distill-32B(Q4)"],
        "D4": ["Qwen3.6-35B-A3B(W4A8)", "Qwen3.8-27b-mtp(W4A8)", "GPT-OSS_20b(W4A8)"],
        "D5": ["Qwen2.5-72B(Q4)", "Qwen3-Next-80B-A3B(Q4)", "Llama-3.3-70B(Q4)"],
    }[tier]
    cls = {"tier": tier, "infer_mem_gb": igb,
           "system_mem_gb": round(mem_total_gb, 1),
           "accel_mem_gb": (int(vram_total_gb / 2**0)) if vram_total_gb else "N/A",
           "recommended_models": rec,
           "skip_rule": "模型档位M vs 设备档位D: M>=D+2→硬件不支持; M<=D-2→不必要验证",
           "note": "Windows: 独立加速卡取 min(系统内存, nvidia-smi 显存合计)=%.0fGB → %s"
                   % (infer_mem, tier)}
    return cls


def accel_mem_gb(vram_total_mib):
    return vram_total_mib / 1024.0


# ---------------- 服务探测 ----------------
def http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def api_list_models(api):
    """LM Studio 无 /health; 服务探测以 GET /v1/models 为准."""
    try:
        d = http_json(api + "/v1/models", timeout=8)
        return [m.get("id", "") for m in d.get("data", [])]
    except Exception:
        return []


# ---------------- 阶段 C: 模型实测 ----------------
TIMEOUT = 300
LONG_PARA = ("智能制造通过工业物联网、人工智能、大数据分析和数字孪生技术的深度融合，实现生产过程的自主感知、"
             "自主决策和自主执行。智能工厂中设备互联产生海量数据，边缘计算节点负责实时预处理，云端平台承担"
             "模型训练与全局优化。机器视觉引入质检环节后缺陷识别准确率大幅提升。预测性维护系统通过振动温度"
             "等传感器数据判断设备健康状态，显著压缩非计划停机时间。")


class PhaseC:
    def __init__(self, api, model, thinking="none"):
        self.api = api
        self.model = model
        self.thinking = thinking
        self.no_think_field = {"reasoning_effort": "none"} if thinking == "none" else {}

    def post(self, payload, timeout=TIMEOUT):
        payload = dict(payload)
        payload.update(self.no_think_field)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.api + "/v1/chat/completions", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
        return json.loads(body), time.perf_counter() - t0

    def post_stream_chunk_times(self, payload, timeout=TIMEOUT):
        """流式请求并记录每个 content chunk 的到达时间戳（相对起点秒）。
        返回 (完整响应dict或None, [chunk_times], wall_s)。
        chunk 时间戳用于瞬时速度统计：推测解码(DFlash2/MTP)速度弹性大，
        均值会掩盖真实峰值，报告需同时呈现峰值与均值。"""
        payload = dict(payload)
        payload.update(self.no_think_field)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.api + "/v1/chat/completions", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.perf_counter()
        parts, times = [], []
        usage = None
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                except Exception:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                ch = (chunk.get("choices") or [{}])[0]
                content = (ch.get("delta") or {}).get("content")
                if content:
                    parts.append(content)
                    times.append(time.perf_counter() - t0)
        text = "".join(parts)
        wall = time.perf_counter() - t0
        resp = None
        if usage is not None:
            resp = {"usage": usage, "content": text}
        return resp, times, wall

    @staticmethod
    def usage(d):
        u = d.get("usage") or {}
        return int(u.get("prompt_tokens", -1)), int(u.get("completion_tokens", -1))

    @staticmethod
    def content(d):
        try:
            return d["choices"][0]["message"].get("content", "") or ""
        except Exception:
            return ""

    def mt(self, base):  # thinking=keep 时放大 token 预算, 让思考结束后仍有正文
        return base * 3 if self.thinking == "keep" else base

    def run(self):
        c = {"api": self.api, "model": self.model}
        # 阶段C 全程采样 GPU 利用率/功耗/温度（真实读数）
        samples, stop = [], threading.Event()

        def _sample_loop():
            while not stop.is_set():
                s = gpu_runtime_sample()
                if s:
                    samples.append(s)
                stop.wait(0.4)

        threading.Thread(target=_sample_loop, daemon=True).start()
        # 探测: LM Studio 无 /health, 直接短请求验证
        progress("service", "running", "验证模型首请求就绪状态")
        log("probe: POST /v1/chat/completions (服务就绪性)")
        try:
            p, pw = self.post({"model": self.model,
                               "messages": [{"role": "user", "content": "你好"}],
                               "max_tokens": self.mt(16)}, timeout=180)
            log("probe OK %.2fs" % pw)
            c["c1_probe_s"] = round(pw, 2)
            c["c1_note"] = ("服务由外部预先启动，未做冷启动计时（禁止估算）；"
                            "首请求就绪耗时含 JIT 权重加载，非完整冷启动，C1 不计入通过率。"
                            "补测需重启服务并自行计时后手工并入报告。")
        except Exception as e:
            stop.set()
            log("⚠ 服务未就绪(%s): %s" % (self.api, e))
            progress("service", "skipped", "推理服务未就绪")
            skip_model_steps("推理服务未就绪")
            return {"skipped": "service_not_ready", "api": self.api}

        progress("service", "done", "模型首请求就绪；非冷启动计时")
        progress("decode", "running", "执行短输入生成请求（流式，采集瞬时速度）")
        # C2 解码速度（v1.11.1 起流式采集 chunk 时间戳 → 峰值/均值双口径）
        # 背景: 推测解码(DFlash2/MTP)速度随草稿命中率波动，均值仅为持续负载口径，
        #       峰值反映引擎瞬时上限，两者都记录防止均值被误读为上限
        c2_payload = {"model": self.model,
                      "messages": [{"role": "user",
                                    "content": "请写一段250字左右的短文，介绍人工智能在工业质检中的应用"}],
                      "max_tokens": self.mt(400)}
        try:
            r2s, chunk_times, w2 = self.post_stream_chunk_times(c2_payload)
            if r2s:
                pt2, ct2 = int(r2s["usage"].get("prompt_tokens", -1)), int(r2s["usage"].get("completion_tokens", -1))
            else:  # 流式未回 usage → 用非流式重试拿 usage（速度峰值仍可用流式数据）
                r2, w2 = self.post(c2_payload)
                pt2, ct2 = self.usage(r2)
        except Exception as e:
            log("C2 stream failed (%s), 回退非流式" % e)
            r2, w2 = self.post(c2_payload)
            pt2, ct2 = self.usage(r2)
            chunk_times = []
        # 瞬时速度: 相邻 content chunk 间推定 1 token（流式解码每 chunk ≈1 token，业界通用口径）,
        # 窗口 1s 平滑抑制网络抖动毛刺; 峰值取窗口最大瞬时值
        c2_speed = {"peak": None, "mean": None, "method": None}
        if len(chunk_times) >= 4:
            ts = [0.0] + list(chunk_times)  # 首 chunk 前视为起点
            n_tok = len(ts) - 1
            # 均值: (chunk 数-1)/末 chunk 首尾跨度，与 usage 口径互验
            span = ts[-1] - ts[0] if ts[-1] > ts[0] else 0
            mean_tps = (n_tok - 1) / span if span > 0 else 0
            # 峰值: 1s 滑动窗口内最大 token 数
            peak_tps, i = 0.0, 0
            for j in range(len(ts)):
                while ts[j] - ts[i] > 1.0:
                    i += 1
                win_tok = j - i
                win_s = ts[j] - ts[i]
                if win_s > 0.05 and win_tok / win_s > peak_tps:
                    peak_tps = win_tok / win_s
            if mean_tps > 0:
                c2_speed = {"peak": round(peak_tps, 1), "mean": round(mean_tps, 1),
                            "method": "流式 chunk 计时；峰值=1s 滑动窗口最大瞬时速度，均值=chunk 跨度均速",
                            "chunks": n_tok}
        # C12 样本：C2 正文（流式或非流式回退）优先，短回复兜底
        try:
            _c2_body = r2s["content"] if (r2s and r2s.get("content")) else self.content(r2)
        except Exception:
            _c2_body = ""
        try:
            r2_probe, _ = self.post({"model": self.model,
                                     "messages": [{"role": "user", "content": "你好"}],
                                     "max_tokens": self.mt(8)}, timeout=60)
            c12_text = _c2_body or self.content(r2_probe)
        except Exception:
            c12_text = _c2_body
        c["c2_short_decode"] = {"wall_s": round(w2, 2), "prompt_tokens": pt2,
                                "completion_tokens": ct2, "reply_len": len(c12_text),
                                "speed_peak_tps": c2_speed["peak"],
                                "speed_mean_tps": c2_speed["mean"],
                                "speed_method": c2_speed["method"],
                                "speed_chunks": c2_speed.get("chunks")}
        c["c12_sample"] = c12_text[:80]
        log("C2: %.2fs / %s tok, peak %s / mean %s tok/s"
            % (w2, ct2, c2_speed["peak"], c2_speed["mean"]))

        end_step("decode", {"ok": 1 if c12_text else 0})
        progress("latency", "running", "等待流式请求首个非空 content chunk")
        # C3 TTFT (首个非空 content chunk)
        try:
            data = json.dumps({"model": self.model,
                               "messages": [{"role": "user", "content": "你好"}],
                               "max_tokens": self.mt(30), "stream": True,
                               **self.no_think_field},
                              ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(self.api + "/v1/chat/completions", data=data,
                                         headers={"Content-Type": "application/json"}, method="POST")
            t0 = time.perf_counter()
            ttft = -1.0
            with urllib.request.urlopen(req, timeout=120) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                        continue
                    try:
                        delta = json.loads(line[5:].strip())["choices"][0].get("delta", {})
                    except Exception:
                        continue
                    if delta.get("content"):
                        ttft = time.perf_counter() - t0
                        break
            c["c3_ttft"] = {"s": round(ttft, 2) if ttft > 0 else -1.0}
            log("C3 TTFT: %.2fs" % c["c3_ttft"]["s"])
        except Exception as e:
            log("C3 failed: %s" % e)
            c["c3_ttft"] = {"s": -1.0, "error": str(e)}

        end_step("latency", c.get("c3_ttft", {}))
        progress("context", "running", "执行长输入与流式同请求分段测试")
        # C4 长上下文
        try:
            r4, w4 = self.post({"model": self.model,
                                "messages": [{"role": "user",
                                              "content": LONG_PARA * 24 + "，请用50字总结核心"}],
                                "max_tokens": self.mt(120)})
            pt4, ct4 = self.usage(r4)
            c["c4_long_ctx"] = {"wall_s": round(w4, 2), "ok": 1 if self.content(r4) else 0,
                                "prompt_tokens": pt4, "completion_tokens": ct4}
            log("C4: %.2fs / prompt %s tok" % (w4, pt4))
        except Exception as e:
            log("C4 failed: %s" % e)
            c["c4_long_ctx"] = {"wall_s": 0, "ok": 0, "prompt_tokens": -1,
                                "completion_tokens": -1, "error": str(e)}

        # C5 长上下文解码衰减：流式「同一次请求」分段计时（prefill=首 content chunk 之前，
        # decode=首 chunk 到末 chunk），全部为真实 API 计时，不使用估算
        try:
            c5_prompt = LONG_PARA * 24 + "，请用50字总结核心"
            payload = {"model": self.model,
                       "messages": [{"role": "user", "content": c5_prompt}],
                       "max_tokens": self.mt(120), "stream": True,
                       "stream_options": {"include_usage": True}}
            payload.update(self.no_think_field)
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(self.api + "/v1/chat/completions", data=data,
                                         headers={"Content-Type": "application/json"}, method="POST")
            t0 = time.perf_counter()
            first = last = None
            ct5 = -1
            c5_chunk_times = []  # decode 段的 content chunk 相对时间戳
            with urllib.request.urlopen(req, timeout=180) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if chunk.get("usage"):
                        ct5 = int(chunk["usage"].get("completion_tokens", -1))
                    ch = (chunk.get("choices") or [{}])[0]
                    if (ch.get("delta") or {}).get("content"):
                        now = time.perf_counter()
                        if first is None:
                            first = now
                        last = now
                        c5_chunk_times.append(now)
            if ct5 < 0:
                ct5 = c["c4_long_ctx"].get("completion_tokens", -1)
                ct5_src = "流式未返回 usage，回退同 prompt 的 C4 非流式 usage"
            else:
                ct5_src = "流式 usage"
            single_tps = (c["c2_short_decode"]["completion_tokens"] /
                          c["c2_short_decode"]["wall_s"])
            prefill_s = (first - t0) if first else 0
            decode_s = (last - first) if (first and last and last > first) else 0
            dec_tps = ct5 / decode_s if (ct5 > 0 and decode_s > 0) else 0
            drop5 = ((single_tps - dec_tps) / single_tps * 100
                     if (single_tps > 0 and dec_tps > 0) else None)
            c5_speed = {"peak": None, "mean": None}
            if len(c5_chunk_times) >= 4:
                ts5 = [0.0] + [t - first for t in c5_chunk_times]
                span5 = ts5[-1] - ts5[0] if ts5[-1] > ts5[0] else 0
                mean5 = (len(ts5) - 2) / span5 if span5 > 0 else 0
                peak5, i5 = 0.0, 0
                for j in range(len(ts5)):
                    while ts5[j] - ts5[i5] > 1.0:
                        i5 += 1
                    win_tok = j - i5
                    win_s = ts5[j] - ts5[i5]
                    if win_s > 0.05 and win_tok / win_s > peak5:
                        peak5 = win_tok / win_s
                if mean5 > 0:
                    c5_speed = {"peak": round(peak5, 1), "mean": round(mean5, 1)}
            c["c5_ctx_decode"] = {
                "prefill_s": round(prefill_s, 3), "decode_s": round(decode_s, 3),
                "decode_tps": round(dec_tps, 1), "completion_tokens": ct5,
                "speed_peak_tps": c5_speed["peak"], "speed_mean_tps": c5_speed["mean"],
                "drop_pct": round(drop5, 1) if drop5 is not None else None,
                "ok": (1 if drop5 < 20 else 0) if drop5 is not None else None,
                "method": "流式同请求分段（首 content chunk 前=prefill，其后=decode）；token 源：" +
                          ct5_src + "；服务若有 prompt cache 会影响 prefill 绝对值，不影响 decode 段",
            }
            log("C5: prefill %.3fs, decode %.1f tok/s (peak %s), drop %s%%"
                % (prefill_s, dec_tps, c5_speed["peak"],
                   c["c5_ctx_decode"]["drop_pct"]))
        except Exception as e:
            log("C5 failed: %s" % e)
            c["c5_ctx_decode"] = {"ok": None, "error": str(e)}

        end_step("context", {"ok": 0 if c.get("c4_long_ctx", {}).get("ok") != 1 or c.get("c5_ctx_decode", {}).get("error") else 1})
        progress("concurrency", "running", "并发阶梯上探: 单路基准 → 2/4/8/16/32 逐档倍增")
        # C6 / C7 并发能力上探 (SPEC v1.7): 单路基准 → 倍增阶梯 → conc_max
        def one(i):
            try:
                d, _ = self.post({"model": self.model,
                                  "messages": [{"role": "user",
                                                "content": "请写200字短文，主题编号%d：介绍一项工业技术" % i}],
                                  "max_tokens": self.mt(200)}, timeout=TIMEOUT)
                return (1 if self.content(d) else 0), self.usage(d)[1]
            except Exception:
                return 0, 0

        # 单路基准
        t0 = time.perf_counter()
        bok, btok = one(0)
        bwall = time.perf_counter() - t0
        c["conc_baseline"] = {"ok": bok, "wall_s": round(bwall, 2), "completion_tokens": btok}
        conc_max = 0
        if bok == 1:
            conc_max = 1
            for n in (2, 4, 8, 16, 32):
                progress("concurrency", "running", "执行 %d 路并发请求" % n)
                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=n) as ex:
                    res = list(ex.map(one, range(1, n + 1)))
                wall = time.perf_counter() - t0
                okn = sum(x[0] for x in res)
                ctok = sum(max(0, x[1]) for x in res)
                # 衰减判定: 与 boxbench.sh 同口径 (usage 折算串行基准份数, 无 usage 时退化 wall/n)
                if okn < n:
                    verdict = "fail"
                else:
                    equiv = (ctok / 200.0) if ctok > 0 else float(n)
                    per = wall / equiv if equiv > 0 else wall
                    drop = (per - bwall) / bwall * 100 if bwall > 0 else 0
                    verdict = "ok" if drop < 30 else "degraded"
                c["c6c7_conc%d" % n] = {"ok": okn, "total": n,
                                        "wall_s": round(wall, 2),
                                        "completion_tokens": ctok,
                                        "verdict": verdict}
                log("C%d(并发%d): %s/%s ok in %.2fs, verdict=%s" % (6 if n == 2 else 7, n,
                    okn, n, wall, verdict))
                if verdict == "ok":
                    conc_max = n
                else:
                    log("并发 %d 路上探终止 (%s), conc_max=%d" % (n, verdict, conc_max))
                    break
        else:
            log("⚠ 单路基准请求失败, 并发阶梯跳过")
        c["conc_max"] = conc_max
        progress("concurrency", "done", "并发上探结束: 最大无衰减并发 %d 路" % conc_max)
        progress("tools", "running", "验证结构化工具调用响应")
        # C8 工具调用
        try:
            r8, _ = self.post({"model": self.model,
                               "messages": [{"role": "user", "content": "北京现在天气怎么样？请帮我查一下"}],
                               "max_tokens": self.mt(300),
                               "tools": [{"type": "function", "function": {
                                   "name": "get_weather", "description": "获取城市实时天气",
                                   "parameters": {"type": "object",
                                                  "properties": {"city": {"type": "string"}},
                                                  "required": ["city"]}}}],
                               "tool_choice": "auto"})
            ch = r8.get("choices", [{}])[0]
            tc = (ch.get("message") or {}).get("tool_calls")
            c["c8_toolcall"] = {"ok": 1 if (ch.get("finish_reason") == "tool_calls" or tc) else 0,
                                "finish_reason": ch.get("finish_reason"), "tool_calls": bool(tc)}
            log("C8: finish_reason=%s" % ch.get("finish_reason"))
        except Exception as e:
            log("C8 failed: %s" % e)
            c["c8_toolcall"] = {"ok": 0, "error": str(e)}

        end_step("tools", c.get("c8_toolcall", {}))
        progress("memory", "running", "验证设备编号多轮召回")
        # C9 多轮记忆
        try:
            r9, _ = self.post({"model": self.model,
                               "messages": [
                                   {"role": "user", "content": "我的设备编号是 BX-7788，请记住它"},
                                   {"role": "assistant", "content": "好的，已记住您的设备编号 BX-7788。"},
                                   {"role": "user", "content": "我刚才说的设备编号是多少？只回答编号即可"}],
                               "max_tokens": self.mt(50)})
            ans = self.content(r9)
            c["c9_multiturn"] = {"ok": 1 if "BX-7788" in ans else 0, "reply": ans[:60]}
            log("C9: ok=%s" % c["c9_multiturn"]["ok"])
        except Exception as e:
            log("C9 failed: %s" % e)
            c["c9_multiturn"] = {"ok": 0, "error": str(e)}

        end_step("memory", c.get("c9_multiturn", {}))
        progress("resources", "running", "读取显存与GPU运行采样")
        # C10 显存
        gpus = nvidia_smi()
        c["c10_vram"] = ("; ".join("GPU%s %s/%s MiB" % (g["index"], g["mem_used_mib"],
                                    g["mem_total_mib"]) for g in gpus)) if gpus else "N/A"
        log("C10 vram: %s" % c["c10_vram"])

        progress("resources", "done" if gpus else "skipped", "显存采集结束" if gpus else "nvidia-smi 未提供显存数据")
        stop.set()
        if samples:
            def _stat(i):
                v = [s[i] for s in samples]
                return {"avg": round(sum(v) / len(v), 1), "max": round(max(v), 1),
                        "min": round(min(v), 1)}
            c["runtime_metrics"] = {
                "samples": len(samples), "util": _stat(0), "power_w": _stat(1),
                "temp_c": _stat(2),
                "note": "阶段C 全程 nvidia-smi 采样（多卡均值，0.4s 间隔）",
            }
            log("runtime: util avg %.1f%% / power avg %.1fW"
                % (c["runtime_metrics"]["util"]["avg"],
                   c["runtime_metrics"]["power_w"]["avg"]))

        notes = ["C1 冷启动加载未测：服务由外部预先启动，未做服务重启计时（禁止估算）；"
                 "需要时在 LM Studio/引擎中重新加载模型并自行计时后手工并入报告。",
                 "C11 多模态未测：需服务以视觉模式(mmproj)启动, 单独重启后测。",
                 "C5 长上下文解码衰减：v1.3.9 起用流式同请求分段计时实测（prefill/decode 分离），"
                 "不再以「缺分段计时」跳过；判定基线 SPEC §4.3 衰减 <20%。",
                 "C3 TTFT 口径：流式请求首个非空 content chunk 到达时间（较 boxbench.sh 的 curl "
                 "总耗时口径更严格）。"]
        if self.thinking == "none":
            notes.append("思考控制：全部请求注入 reasoning_effort=none（LM Studio 上 "
                         "chat_template_kwargs/enable_thinking//no_think 均无效, 见 PLATFORM_NOTES）。")
        else:
            notes.append("思考模式：keep — 速度数据含 reasoning token, 与 SPEC 基线(关思考口径)不可比, "
                         "报告解读时注意。")
        c["notes"] = notes
        return c


def collect_engine_info(api, model, model_files):
    """engine 段: 引擎名/版本/启动方式/ctx/量化/文件大小 (Windows 下尽量真实采集)."""
    lmver = lm_studio_version() or "未识别"
    backends = lm_studio_backends()
    # 实际用的是 CUDA backend，不能取排序后的第一个（那通常是 CPU avx2 版）
    cuda_b = [b for b in backends if "cuda" in b.lower() or "nvidia" in b.lower()]
    build = (cuda_b[0] if cuda_b else (backends[0] if backends else "未识别"))
    ps = lms_ps_info()
    port = api.rsplit(":", 1)[-1] if ":" in api.rsplit("/", 1)[-1] else "?"
    ctx = ""
    quant, fsize, mdate, mfile = "", "", "", ""
    for f in model_files:
        if os.path.basename(f["path"]).lower().startswith(re.split(r"[-_/\\]", model)[0].lower()[:20]):
            mfile, fsize, mdate = f["path"], f["size"], f["mtime"]
            break
    if mfile:
        mq = re.search(r"(w\d+a\d+|Q\d_[A-Z_0-9]+|int\d+|iq\d_[a-z0-9_]+)",
                       os.path.basename(mfile), re.I)
        quant = mq.group(1) if mq else ""
        cfg_dir = os.path.join(os.path.expanduser("~"), ".lmstudio", ".internal",
                               "user-concrete-model-default-config")
        target = os.path.basename(mfile)
        for dirpath, _, files in os.walk(cfg_dir):
            if (target + ".json") in files:  # 配置文件为 <model-file>.gguf.json
                try:
                    cfg = json.load(open(os.path.join(dirpath, target + ".json"),
                                         encoding="utf-8"))
                    for fld in cfg.get("load", {}).get("fields", []):
                        if fld.get("key") == "llm.load.contextLength":
                            ctx = str(fld.get("value"))
                except Exception:
                    pass
                break
    # Windows GUI 无原生启动命令行: 记录从 lms ps + 加载配置还原的等价参数
    equiv = ("lms load %s --gpu max -c %s --parallel %s --identifier %s "
             "| 本地服务 --port %s（GUI 启动, 无原生命令行, 以上为等价加载参数）"
             % (model, ctx or ps.get("context", "?"), ps.get("parallel", "?"),
                model, port))
    return {
        "engine_name": "LM Studio %s (OpenAI-compatible local server, llama.cpp CUDA12 backend)"
                       % lmver,
        "engine_build": build,
        "engine_bin": (which("LM Studio") or
                       os.path.join(os.path.expanduser("~"),
                                    "AppData", "Local", "Programs", "LM Studio", "LM Studio.exe")),
        "engine_cmd": equiv,
        "ctx_size": ctx or str(ps.get("context", "未记录")),
        "model_file": os.path.basename(mfile) if mfile else "未记录",
        "model_path": mfile or "未记录",
        "model_file_size": fsize or "未记录",
        "model_build_date": mdate or "未记录",
        "model_quant": quant or "未记录",
        "service_parallel": ps.get("parallel", "未记录"),
    }


def build_skipped_models(model_files, tested_models, infer_mem_gb):
    """SPEC §4.2: 本轮未测的本地权重按目录(shard 聚合)给出跳过判定与实测资源依据."""
    groups = {}
    for f in model_files:
        if os.path.basename(f["path"]).lower().startswith("mmproj"):
            continue  # 视觉编码器, 非独立 LLM 权重
        groups.setdefault(os.path.dirname(f["path"]), []).append(f)
    prefixes = [re.split(r"[-_/\\]", m)[0].lower() for m in tested_models]
    out = []
    for key, files in groups.items():
        if any(p in os.path.basename(x["path"]).lower() for x in files for p in prefixes):
            continue  # 本轮已测模型的权重目录
        try:
            size = sum(float(x["size"].split()[0]) for x in files)
        except Exception:
            continue
        need = size * 1.15  # 权重 + KV/激活开销 (SPEC §4.2)
        if need > infer_mem_gb:
            verdict = "⏭ 内存不足，暂未测试"
            reason = ("权重合计 %.2fGB ×1.15（含 KV/激活开销）≈ 需 %.1fGB 推理内存，"
                      "实际可用 %sGB（min(系统内存, 加速卡显存合计)）；"
                      "按 SPEC §4.2 自动跳过，不计入通过率。" % (size, need, infer_mem_gb))
        else:
            verdict = "◼ 本轮未测（未指定）"
            reason = ("权重合计 %.2fGB，资源可满足（需 %.1fGB / 可用 %sGB），但本轮只测服务已加载的模型；"
                      "加载该模型后可用 --all 补测。" % (size, need, infer_mem_gb))
        if "flash" in key.lower() or "去对齐" in key:
            reason += ("；去对齐微调版按 SPEC §4.4 需先验证权重来源可信并追加 U1~U3"
                       "（红线/越狱抵抗仅记录事实、不做绕过尝试），模型未加载，故 U1~U3 未执行。")
        out.append({"name": os.path.basename(key), "path": key + os.sep + "*.gguf",
                    "size": "%.2f GB" % size, "verdict": verdict, "reason": reason})
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("mode", nargs="?", default="auto",
                    choices=["auto", "fingerprint", "collect"])
    ap.add_argument("--api", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default=None)
    ap.add_argument("--thinking", default="none", choices=["none", "keep"])
    ap.add_argument("--all", action="store_true", help="对 /v1/models 全部 LLM 顺序实测")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    print("@@BOXBENCH_EVENT " + json.dumps(dict(type="plan", stages=[
        "hardware", "inventory", "classify", "service", "decode", "latency", "context",
        "concurrency", "tools", "memory", "resources", "archive"])), file=sys.stderr, flush=True)

    now = datetime.datetime.now().astimezone()
    out_path = args.out or "boxbench_results_%s.json" % now.strftime("%Y%m%d_%H%M%S")
    global RUNLOG_PATH
    RUNLOG_PATH = "boxbench_run_%s.log" % now.strftime("%Y%m%d_%H%M%S")
    log("运行日志: %s (过程留痕, 交付时与 JSON/报告一并归档)" % RUNLOG_PATH)

    progress("hardware", "running", "通过 PowerShell 采集硬件指纹")
    phase_a, mem_total_gb, vram_total_mib = phase_fingerprint()
    progress("hardware", "done", "硬件指纹采集结束")
    progress("inventory", "running", "盘点模型、引擎与服务")
    phase_b = phase_inventory()
    progress("inventory", "done", "环境盘点结束")
    progress("classify", "running", "匹配硬件档位")
    cls = phase_classify(mem_total_gb, accel_mem_gb(vram_total_mib))
    progress("classify", "done", "硬件分档结束")

    result = {"boxbench_version": VERSION, "spec_version": SPEC_VERSION,
              "timestamp": now.isoformat(timespec="seconds"),
              "host_os_path": "Windows 等价采集 (boxbench_windows.py; boxbench.sh 依赖 /proc 不可用)",
              "phase_a": phase_a, "phase_b": phase_b, "classification": cls}
    targets = []

    if args.mode == "fingerprint":
        progress("service", "skipped", "本次仅采集硬件与环境")
        skip_model_steps("本次仅采集硬件与环境")
    else:
        models = api_list_models(args.api)
        llms = [m for m in models if not re.search(r"embed|bge|rerank|clip", m, re.I)] or models
        if not llms:
            log("⚠ %s 未发现可用模型, 阶段C 跳过" % args.api)
            progress("service", "skipped", "未发现可用模型")
            skip_model_steps("未发现可用模型")
            result["phase_c"] = {"skipped": "service_not_ready", "api": args.api}
        else:
            targets = llms if args.all else [args.model or llms[0]]
            engine = collect_engine_info(args.api, targets[0], phase_b["model_files"])
            result["engine"] = engine
            if args.all and len(targets) > 1:
                result["models"] = []
                for m in targets:
                    progress_model(m)
                    log("===== 模型: %s =====" % m)
                    result["models"].append({"name": m,
                                             "path": engine.get("engine_bin", ""),
                                             "engine": collect_engine_info(args.api, m,
                                                                           phase_b["model_files"]),
                                             "phase_c": PhaseC(args.api, m,
                                                               args.thinking).run()})
            else:
                progress_model(targets[0])
                result["phase_c"] = PhaseC(args.api, targets[0], args.thinking).run()

    result["skipped_models"] = build_skipped_models(phase_b["model_files"], targets,
                                                    cls["infer_mem_gb"])
    result["model"] = targets[0] if targets else (args.model or "未加载模型")
    _eng = result.get("engine") or {}
    result["model_path"] = _eng.get("model_path", "未记录")
    _pc = result.get("phase_c") or {}
    if _pc.get("runtime_metrics"):
        result["runtime_metrics"] = _pc["runtime_metrics"]
    progress("archive", "running", "保存原始实测 JSON")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    progress("archive", "done", "原始 JSON 已保存；HTML 报告需另行渲染")
    print("OK -> %s" % out_path)
    log("完成: %s" % out_path)
    log("渲染: python scripts/render_report.py %s [输出.html] --device <型号>" % out_path)


if __name__ == "__main__":
    main()
