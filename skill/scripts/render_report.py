#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BoxBench v1.1 报告渲染器 — 工具无关
输入: boxbench.sh 产出的 JSON 结果文件 (单模型或 multi 多模型)
输出: 统一样式 HTML 报告 (深色主题 + Chart.js 图表)
用法: python3 render_report.py <result.json> [输出.html] [--device 型号] [--model 模型名] [--tops ..] [--bw ..] [--no-redact]
脱敏: 默认开启 (--no-redact 关闭)。IP/IPv6/MAC/主机名 在渲染前自动替换为占位符, 报告可直接对外提交。
多模型: JSON 含 "models" 数组时自动切换多模型报告:
  - 每模型一份实测明细 (复用单模型渲染)
  - 多模型横向对比表 (解码/显存/工具调用/并发/加载时间)
  - 对比图表 (Chart.js 柱状图)
任何环境可运行: 仅依赖 Python3 标准库; 图表使用 CDN 引入的 Chart.js(离线打开仍可看表格数据)。
"""
import json, sys, os, datetime, html as H, re

# Windows 控制台默认 GBK，print 中文文件名可能抛 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SPEC_VERSION = "1.7"

# 判定基线 (SPEC v1.1 §4.3)
BASELINE = {
    "load_s_35b": 180, "load_s_small": 60,
    "decode_35b": 15, "decode_flash": 40,
    "ttft_s": 1.0, "prefill_tps": 300, "ctx_decode_drop_pct": 20,
    "conc_drop_pct": 30,
}

# 已知加速卡规格表
KNOWN_ACCEL = {
    "M1000":  {"tops": "50 TOPS (INT8)", "bw": "~102 GB/s", "vram": "30.6 GiB 统一内存"},
    "E300K":  {"tops": "50 TOPS (INT8)", "bw": "~102 GB/s", "vram": "30.6 GiB 统一内存"},
}

TIER_DESC = {
    "D1": ("入门", "<7GB 推理内存", "小模型/embedding"),
    "D2": ("主流", "7~14GB", "4B~9B 模型"),
    "D3": ("中档", "14~28GB", "14B/30B-A3B 模型"),
    "D4": ("高档", "28~64GB", "35B 级主力模型"),
    "D5": ("旗舰", "≥64GB", "70B~80B 级模型"),
}

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--border:#2d3748;
--txt:#e6edf3;--muted:#9aa7b4;--accent:#58a6ff;--win:#3fb950;
--bad:#f85149;--warn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
line-height:1.55;padding:28px 18px 60px}
.wrap{max-width:1060px;margin:0 auto}
h1{font-size:25px;margin:0 0 4px;font-weight:700}
h2{font-size:18px;margin:32px 0 12px;padding-left:11px;border-left:4px solid var(--accent)}
h3.msec{font-size:15px;margin:22px 0 10px;color:var(--accent)}
.sub{color:var(--muted);font-size:13px;margin-bottom:8px}
.summary{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px 20px;margin:16px 0}
.summary p{margin:6px 0;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px}
.card .k{color:var(--muted);font-size:12px}
.card .v{font-size:21px;font-weight:700;margin-top:3px}
.card .v small{font-size:12px;color:var(--muted);font-weight:400}
.card .v.hl{color:var(--accent)}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px;margin:14px 0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:780px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;background:var(--panel2)}
td.c{text-align:center}
.ok{color:var(--win);font-weight:600}
.no{color:var(--bad);font-weight:600}
.mid{color:var(--warn);font-weight:600}
.skip{color:var(--muted)}
.chartbox{position:relative;height:260px}
.legend{font-size:12px;color:var(--muted);margin-top:8px}
.note{font-size:12.5px;color:var(--muted);background:var(--panel2);border-radius:8px;padding:10px 12px;margin-top:10px}
.foot{color:var(--muted);font-size:12px;margin-top:28px;text-align:center}
.badge{display:inline-block;padding:2px 12px;border-radius:999px;font-size:13px;font-weight:700;color:#fff;vertical-align:middle}
.b-green{background:var(--win)}.b-amber{background:var(--warn)}.b-red{background:var(--bad)}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.p-ok{background:#0c2d18;color:var(--win)}
.p-no{background:#3d1418;color:var(--bad)}
.p-mid{background:#3a2c0a;color:var(--warn)}
.p-skip{background:#232b36;color:var(--muted)}
.tiers{display:flex;gap:8px;margin:10px 0 6px}
.tier{flex:1;background:var(--panel2);border:1px solid var(--border);border-radius:10px;
padding:10px 12px;position:relative;opacity:.45}
.tier.on{opacity:1;border-color:var(--accent);background:#12233c;box-shadow:0 0 0 1px var(--accent)}
.tier .tn{font-size:15px;font-weight:700}
.tier.on .tn{color:var(--accent)}
.tier .td1{font-size:11.5px;color:var(--muted);margin-top:2px}
.tier .td2{font-size:11px;color:var(--muted)}
code{background:#21262d;padding:1px 6px;border-radius:5px;font-size:12px}
.sample{background:#0b0f14;border:1px solid var(--border);border-radius:8px;padding:10px 12px;
font-size:12.5px;color:var(--txt);margin-top:8px;line-height:1.7}
.sample .q{color:var(--muted);font-size:11.5px}
.mblock{border:1px solid var(--border);border-radius:14px;padding:0;margin:20px 0;overflow:hidden}
.mblock .mhead{background:var(--panel2);padding:12px 18px;font-size:15.5px;font-weight:700;
display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.mblock .mbody{padding:4px 16px 14px}
.tagchip{display:inline-block;background:#12233c;color:var(--accent);border:1px solid var(--accent);
border-radius:999px;padding:1px 12px;font-size:12.5px;font-weight:700}
.best{color:var(--win);font-weight:700}
"""

def esc(x): return H.escape(str(x if x is not None else ""))

def infer_model_name(m):
    """从模型记录自动反解可读模型名（--model 未给出时的兜底，v1.11.0 起）。
    优先级: weight 名称清洗 > 权重文件名去扩展 > path 基名。
    例: HiModel_xh2_qwen3.6-35b-a3b_w4a8_256_256k_b1_1chip_2cores_v1.5.0_20260824.gguf
        → Qwen3.6-35B-A3B(W4A8)（量化段之前的权重名段，连字符转空格后按词首大写）。
    v1.11.1: 补充 engine.model_path / engine.model_file 来源（Strata 等引擎
    启动命令行无 -m 参数、模型路径记录在 engine 段的场景）。"""
    import re as _re
    eng = m.get("engine") or {}
    cmd = str(eng.get("engine_cmd") or "")
    path = ""
    mm = _re.search(r'(?:-m|--model)[= ](\S+)', cmd)
    if mm:
        path = mm.group(1)
    # Strata/打包式引擎: 命令行无 -m, 模型文件记录在 engine 段
    path = path or str(m.get("path") or "")
    path = path or str(eng.get("model_path") or "")
    if not path:
        mf = str(eng.get("model_file") or "")
        if mf and mf not in ("未记录", "?", ""):
            path = mf
    if not path:
        # 顶层兜底: boxbench_windows.py 单模型模式把路径写在结果 JSON 顶层 model_path
        # (人工/脚本修正 engine 段时容易抹掉 engine.model_path, 顶层字段更稳)
        path = str(m.get("model_path") or "")
    if not path or "<model>" in path:
        return ""
    base = _re.split(r"[\\/]", path)[-1]
    stem = _re.sub(r"\.(gguf|safetensors|onnx)$", "", base, flags=_re.I)
    # 清洗: 去掉 HiModel_xh2_ 前缀、量化段(w4a8/Q4_K_M/int8/iq3_s/tq1_0...)及之后的规格尾段
    stem = _re.sub(r"^HiModel[_-][a-z0-9]+[_-]", "", stem, flags=_re.I)
    stem = _re.sub(r"[_-](?:w\d+a\d+|Q\d_[A-Z0-9_]+|iq\d_[a-z0-9_]+|tq\d_[a-z0-9_]+|int\d+)(?:[_-].*)?$",
                   "", stem, flags=_re.I)
    stem = stem.replace("-", " ").replace("_", " ").strip()
    if not stem:
        return ""
    def cap(tok):
        # 字母+数字混合(35b/a3b/mtp/w4a8) → 全大写: 35B/A3B/MTP/W4A8
        # 纯字母且已含大写(LLaMA) → 保留专有名; 纯小写单词(qwen) → 词首大写(Qwen)
        if _re.search(r"\d", tok):
            # 例外: 品牌名+版本号(Qwen3.8/glm4) 保留品牌大小写, 只有纯规格词(35b/a3b)才全大写
            if _re.fullmatch(r"(?i)(qwen|glm|deepseek|llama|minicpm)\d+(\.\d+)?", tok):
                m2 = _re.match(r"(?i)([a-z]+)(\d+(?:\.\d+)?)", tok)
                return m2.group(1)[:1].upper() + m2.group(1)[1:].lower() + m2.group(2)
            return tok.upper()
        if _re.search(r"[A-Z]", tok):
            return tok
        return tok[:1].upper() + tok[1:]
    out = " ".join(cap(t) for t in stem.split() if t)
    # 官方产品名连字符恢复（分词后执行, 避免 cap 拆词）: Gyro-S / Inkling-2 / Flash-Next
    out = (out.replace("Gyro S", "Gyro-S").replace("Inkling 2", "Inkling-2")
              .replace("Flash Next", "Flash-Next"))
    return out


# ============ 脱敏 (默认开启; 对齐 boxbench_exp.py 的脱敏口径) ============
_RE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_RE_IPV6 = re.compile(r"\b(?:[a-f0-9]{1,4}:){2,7}[a-f0-9]{1,4}\b", re.I)
_RE_MAC = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)

def make_redactor(redact: bool, device_label=""):
    """返回 (预处理函数, 主机名替换表)。redact=False 时为恒等变换。
    hostname → `<设备型号>` (评委仍能看出是哪台设备), IP/MAC → <内网IP>/<mac>。"""
    if not redact:
        return (lambda s: s), {}
    def _sub_ip(m):
        v = m.group(0)
        if v.startswith("127.") or v == "0.0.0.0":
            return v  # 回环/监听地址无敏感性, 保留可读性
        return "<内网IP>"
    def red(s):
        if not isinstance(s, str):
            s = str(s if s is not None else "")
        s = _RE_MAC.sub("<mac>", s)
        s = _RE_IPV6.sub("<ipv6>", s)
        s = _RE_IP.sub(_sub_ip, s)
        # 网络接口行(如 enp131s0=IP/掩码): IP 已被替换, 掩码一并去掉避免残留拓扑信息
        s = re.sub(r"=/<内网IP>/\d+", "=<内网IP>", s)
        # 主机名: 仅替换 phase_a.hostname 字段值本身 (在 redact_deep 里按 key 定向处理, 字符串级不误伤)
        return s
    return red, {}


def get(d, path, default=""):
    cur = d
    for k in path.split('.'):
        if isinstance(cur, dict) and k in cur: cur = cur[k]
        else: return default
    return cur

def pill(text, cls): return f'<span class="pill {cls}">{text}</span>'

def verdict_cell(ok):
    if ok == 1: return '<span class="ok">✅ 通过</span>'
    if ok == 0: return '<span class="no">❌ 失败</span>'
    return '<span class="mid">⚠️ 异常</span>'

def build_tier_bar(cls):
    cur = cls.get("tier", "")
    parts = [f'<div class="sub" style="margin-top:14px">硬件分档判定（依据 HARDWARE_MODEL_MATRIX v1.0，按推理内存 {cls.get("infer_mem_gb","?")}GB 判档）</div><div class="tiers">']
    for t in ["D1","D2","D3","D4","D5"]:
        name, mem, fit = TIER_DESC[t]
        on = " on" if t == cur else ""
        tag = " ◀ 当前" if t == cur else ""
        parts.append(f'<div class="tier{on}"><div class="tn">{t} {name}{tag}</div>'
                     f'<div class="td1">{mem}</div><div class="td2">{fit}</div></div>')
    parts.append("</div>")
    return "".join(parts)

def build_recommend_table(cls, tier="D4", tested=None):
    """tested: {模型名: stats} 已实测模型。分档表只列已测模型及其实测状态；
    推荐清单里未测的模型收进备注（不进表格，避免"✅ 应测"被误读为已测）。"""
    tested = tested or {}
    rows = []
    for m in cls.get("recommended_models", []):
        if m in tested:
            s = tested[m]
            if s.get("skipped") or s.get("error"):
                dec, dec_cls = "⏭ 未测", "p-skip"
            else:
                pr = (s["pass_n"] / s["graded_n"] * 100) if s.get("graded_n") else 0
                dec, dec_cls = f"✅ 已测（{pr:.0f}% 通过）", "p-ok" if pr >= 70 else "p-mid"
            rows.append(f'<tr><td><b>{esc(m)}</b></td><td class="c">{pill(dec, dec_cls)}</td>'
                        f'<td>档位匹配（{esc(tier)}），本轮已实测</td></tr>')
    untested = [m for m in cls.get("recommended_models", []) if m not in tested]
    note_bits = []
    if untested:
        note_bits.append(f'本档推荐但<b>本轮未测</b>：{esc("、".join(untested))}（"应测"≠已测，未测模型不进表）。')
    rule = cls.get("skip_rule", "")
    note_bits.append(f'跳过规则：{esc(rule)} —— 模型档位 ≥ 设备+2 标注 <b>⏭ 硬件不支持</b>；模型档位 ≤ 设备−2 标注 <b>◼ 不必要验证</b>。跳过的模型列出不计入通过率。')
    if not rows:
        rows.append('<tr><td colspan="3">本轮无推荐清单内模型被实测</td></tr>')
    return ('<table><thead><tr><th>模型</th><th class="c">测试状态</th><th>依据</th></tr></thead><tbody>'
            + "".join(rows) +
            '</tbody></table><div class="note">' + " ".join(note_bits) + "</div>")

def build_engine_cfg(m, top_engine=None):
    """模型运行配置表: 引擎/版本/启动命令/上下文/量化/模型文件。横向对比公平性的前提。"""
    eng = m.get("engine") or top_engine or {}
    def g(k, default="未记录"):
        v = eng.get(k)
        return v if v not in (None, "", "None") else default
    ctx = g("ctx_size")
    try:
        if ctx != "未记录":
            n = int(str(ctx)); ctx = f"{n:,}（{n/1024:.0f}K）"
    except Exception: pass
    quant = g("model_quant")
    # 单模型模式没有 m["path"]，从 engine 段取；Windows 路径用正反斜杠都能切出文件名
    path = str(m.get("path") or eng.get("model_path") or eng.get("model_file") or "未记录")
    if quant == "未记录" and path != "未记录":
        mq = re.search(r'(w\d+a\d+|Q\d_[A-Z_0-9]+|int\d+)', path)
        if mq: quant = mq.group(1)
    short = re.split(r"[\\/]", path)[-1] if re.search(r"[\\/]", path) else path
    cmd = str(g("engine_cmd"))
    port = "未记录"
    pm = re.search(r'--port[= ](\d+)', cmd)
    if pm: port = pm.group(1)
    rows = [
        ("模型权重", f"{esc(short)}（{esc(g('model_file_size'))}）"),
        ("量化格式", esc(quant)),
        ("推理引擎", f"{esc(g('engine_name'))}（build: {esc(g('engine_build'))}）"),
        ("上下文窗口 ctx-size", esc(ctx)),
        ("服务端口", esc(port)),
    ]
    if g("model_build_date") != "未记录":
        rows.insert(2, ("权重构建日期", esc(g("model_build_date"))))
    t = ('<table style="margin:10px 0 14px"><thead><tr><th style="width:200px">运行配置</th><th>值</th></tr></thead><tbody>'
         + "".join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in rows)
         + f'<tr><td>启动命令行</td><td><code style="word-break:break-all">{esc(cmd)}</code></td></tr>'
         + "</tbody></table>")
    note = "" if m.get("engine") or top_engine else '<div class="note">⚠ 本模型数据未记录引擎运行配置，横向对比时注意：两模型实际启动参数一致时才可比。</div>'
    return t + note

def build_util_section(mc, tops_str="50 TOPS"):
    """算力利用率分析 (v1.5 起 phase_c 带 npu 采样): 空闲/解码/prefill/并发的 NPU 利用率 + 算力瓶颈判读。
    无采样数据时返回空串(旧 JSON 兼容)。"""
    idle = mc.get("idle_baseline") or {}
    c2 = ((mc.get("c2_short_decode") or {}).get("npu")) or {}
    c4 = ((mc.get("c4_long_ctx") or {}).get("npu")) or {}
    # 并发阶梯段: 取实测存在阶梯中的最高档 (v1.8); 旧数据回退 conc4
    conc_segs = []
    for n in (32, 16, 8, 4, 2):
        cc = ((mc.get(f"c6c7_conc{n}") or {}).get("npu")) or {}
        if cc:
            conc_segs.append((f"并发阶梯 {n} 路（上探最高档）", cc))
            break
    else:
        c7 = ((mc.get("c6c7_conc4") or {}).get("npu")) or {}
        if c7:
            conc_segs.append(("C7 并发 4 路", c7))
    c6 = ((mc.get("c6c7_conc2") or {}).get("npu")) or {}
    ov = mc.get("util_overall") or {}
    # v1.10.13: Windows GPU 计数器路径（runtime_metrics.source=gpu-counter）也出利用率表
    rt = mc.get("runtime_metrics") or {}
    if not any([c2, c4, conc_segs, ov]) and not (isinstance(rt, dict) and rt.get("util")):
        return ""
    def fmt(d, key="util_avg"):
        v = d.get(key)
        return f"{v:.0f}%" if isinstance(v, (int, float)) else "—"
    rows = []
    segs = [
        ("空闲基线（服务已加载，无请求）", idle),
        ("C2 短输入解码（生成阶段）", c2),
        ("C4 长上下文 prefill（~2K tok 吞入）", c4),
        ("C6 并发 2 路", c6),
    ] + conc_segs + [
        ("全场综合（空闲后全部测试段）", ov),
    ]
    for name, seg in segs:
        if not seg:
            continue
        peak = seg.get("util_peak")
        peak_s = f"/峰值 {peak:.0f}%" if isinstance(peak, (int, float)) else ""
        temp = seg.get("temp_max")
        temp_s = f"{temp:.1f}℃" if isinstance(temp, (int, float)) else "—"
        rows.append(f'<tr><td>{esc(name)}</td><td class="c">{fmt(seg)}{peak_s}</td>'
                    f'<td class="c">{fmt(seg, "mem_pct_avg")}</td>'
                    f'<td class="c">{temp_s}</td>'
                    f'<td class="c">{seg.get("samples", "—")}</td></tr>')
    # v1.10.13: GPU 计数器路径（无 npu 分段字段）→ 用 runtime_metrics 出全场汇总行
    _rt = mc.get("runtime_metrics") or {}
    _rt_src = _rt.get("source", "")
    if not rows and _rt_src == "gpu-counter" and isinstance(_rt.get("util"), dict):
        _u = _rt["util"]
        rows.append(f'<tr><td>全场综合（GPU 计数器采样，{_rt.get("samples", "—")} 样本）</td>'
                    f'<td class="c">{_u.get("avg", 0):.0f}%/峰值 {_u.get("max", 0):.0f}%</td>'
                    f'<td class="c">{esc(str(mc.get("c10_vram", "—")))}</td>'
                    f'<td class="c">—</td>'
                    f'<td class="c">{_rt.get("samples", "—")}</td>')
    if not rows:
        return ""
    # 瓶颈判读: prefill 是计算受限段, 其利用率反映真实算力发挥; 解码是访存受限, 利用率低属正常
    pf_u = c4.get("util_avg"); dec_u = c2.get("util_avg")
    verdicts = []
    # 恒 0 检测: 全部段 util 均为 0 → 该平台管理工具不统计 NPU 利用率(驱动限制), 如实标注
    # v1.10.13: GPU 计数器路径(rt=util)有真实读数, 不触发恒 0 警告
    all_utils = [s.get("util_avg") for s in [idle, c2, c4, c6, ov] + [seg for _, seg in conc_segs] if isinstance(s, dict)]
    if _rt_src == "gpu-counter" and isinstance(_rt.get("util"), dict) and _rt["util"].get("avg", 0) > 0:
        pass  # 计数器路径已有真实读数判读, 跳过恒 0 警告
    elif all_utils and all(u == 0 for u in all_utils if u is not None):
        verdicts.append("⚠️ 全程 NPU 利用率读数恒为 0（含推理时段）——该平台管理工具/驱动未实现该计数器，<b>不代表 NPU 未工作</b>（引擎计时正常推进、输出正常产出）。此为采集工具限制，OS 侧无法量化该 NPU 的真实算力利用率；替代口径：解码/prefill 吞吐（C2/C4）与显存/温度占用即本报告的算力利用证据链。")
    if isinstance(pf_u, (int, float)) and pf_u > 0:
        if pf_u >= 70:
            verdicts.append(f"prefill 段 NPU 平均利用率 <b>{pf_u:.0f}%</b>——计算密集段算力发挥充分，接近标称算力的有效区间")
        elif pf_u >= 40:
            verdicts.append(f"prefill 段 NPU 平均利用率 <b>{pf_u:.0f}%</b>——计算密集段有中等发挥，算力或受数据供给/调度开销约束")
        else:
            verdicts.append(f"prefill 段 NPU 平均利用率 <b>{pf_u:.0f}%</b>——计算密集段利用率偏低，标称算力远未打满（引擎调度/带宽瓶颈/模型结构限制）")
    if isinstance(dec_u, (int, float)) and isinstance(pf_u, (int, float)) and pf_u > 0:
        verdicts.append(f"解码段（{dec_u:.0f}%）低于 prefill 段（{pf_u:.0f}%）符合预期：自回归解码每步仅 1 token，属<b>访存受限</b>负载，算力利用率天然低——这是所有 LLM 推理的共性，不是该设备的问题")
    mem_c10 = str(mc.get("c10_vram", ""))
    if mem_c10 and ("MiB" in mem_c10 or "计数器口径" in mem_c10):
        verdicts.append(f"显存占用 {esc(mem_c10)}（加载后）——结合利用率：显存余量大意味着有上探更大模型/更大并发/更长上下文的空间")
    _rt_util = (mc.get("runtime_metrics") or {}).get("util") or {}
    _rt_src = (mc.get("runtime_metrics") or {}).get("source", "")
    if isinstance(_rt_util.get("avg"), (int, float)) and _rt_src == "gpu-counter":
        verdicts.append(
            f"GPU 计数器全程平均 <b>{_rt_util['avg']:.0f}%</b> / 峰值 <b>{_rt_util.get('max', 0):.0f}%</b>"
            "（Windows GPU Engine compute 引擎聚合口径，多调度器架构可 >100%；AMD 核显无独立功耗/温度计数器）——"
            "解码吞吐与显存占用见 C2/C5/C10，采样源 runtime_metrics.source=gpu-counter")
    t = ('<div class="sub" style="font-weight:600;color:var(--txt);margin-top:14px">NPU 算力利用率分析（测试期间 1s 间隔采样）</div>'
         '<table style="margin:6px 0 8px"><thead><tr><th>阶段</th><th class="c">NPU 利用率（均值/峰值）</th>'
         '<th class="c">显存占用</th><th class="c">温度峰值</th><th class="c">样本数</th></tr></thead><tbody>'
         + "".join(rows) + '</tbody></table><div class="note">'
         + " ".join(f"<div style='margin:2px 0'>· {v}</div>" for v in verdicts)
         + "</div>")
    return t

def build_agent_section(pe):
    """阶段 E: OpenClaw Agent 框架集成测试分节。pe = JSON phase_e 段。
    返回 HTML (无数据/跳过时返回空串)。结果独立于 C 通过率。"""
    if not isinstance(pe, dict) or not pe:
        return ""
    if pe.get("skipped"):
        reason_map = {
            "openclaw_not_installed": "设备未安装 OpenClaw 且自动安装未启用（BOX_AGENT_AUTOINSTALL=0）或非 Linux",
            "openclaw_autoinstall_failed": "OpenClaw 自动安装失败（网络受限或依赖缺失，详见设备端运行日志）",
            "openclaw_not_running": "OpenClaw CLI 存在但网关/进程未运行",
            "not_linux_or_disabled": "非 Linux 环境（Windows 无 OpenClaw 部署形态）或显式跳过",
        }
        reason = reason_map.get(pe.get("skipped"), pe.get("skipped"))
        return (f'<div class="sub" style="font-weight:600;color:var(--txt);margin-top:14px">'
                f'Agent 框架集成（阶段 E · OpenClaw）</div><div class="note">⏭ 跳过 — {esc(reason)}</div>')
    env = pe.get("env", {})
    items = [
        ("E2", "端到端单轮问答", "e2_chat", "经 OpenClaw 网关收发一轮对话（网关基本能力，必过）"),
        ("E3", "单工具真实执行", "e3_tool", "calc 工具计算 137×24，验证调用→执行→回填完整循环"),
        ("E4", "多步工具链", "e4_chain", "连续两次工具调用（15×8→+470），多步场景暴露 parser 循环问题"),
        ("E5", "输出预算截断", "e5_budget", "500 字长文生成，检查是否被 OpenClaw 输出预算截断"),
        ("E6", "纯文本回退", "e6_fallback", "无工具场景下 parser 回退纯文本路径"),
    ]
    rows = []
    epass = 0; egraded = 0
    for no, name, key, desc in items:
        it = pe.get(key, {})
        ok = it.get("ok", -1)
        if ok == 1: epass += 1
        if ok in (0, 1): egraded += 1
        val_parts = []
        if it.get("wall_s"): val_parts.append(f"{it['wall_s']}s")
        if key == "e5_budget" and it.get("reply_len") is not None:
            val_parts.append(f"回复 {it['reply_len']} 字符（要求 ≥{it.get('min_expected', 400)}）")
        if it.get("reply"):
            val_parts.append(esc(str(it["reply"])[:60]))
        val = "｜".join(val_parts) if val_parts else ("未执行" if ok == -1 else "")
        cls = "p-ok" if ok == 1 else ("p-no" if ok == 0 else "p-skip")
        mark = "✅" if ok == 1 else ("❌" if ok == 0 else "—")
        rows.append(f'<tr><td>{no}</td><td><b>{name}</b></td><td>{desc}</td>'
                    f'<td>{val}</td><td class="c">{pill(mark + (" 通过" if ok==1 else (" 失败" if ok==0 else "")), cls)}</td></tr>')
    rate = f'{epass}/{egraded}' if egraded else "—"
    oc_ver = env.get("version") or "unknown"
    env_line = f"OpenClaw {esc(str(oc_ver))} ｜ 网关端口 {env.get('port', '?')} ｜ 后端 API {esc(str(env.get('model_api', '?')))}"
    # E2 失败提示
    fail_note = ""
    if pe.get("e2_chat", {}).get("ok") == 0:
        fail_note = '<div class="note" style="color:#f85149">⚠ E2 失败：E3~E6 未执行（置 -1，不计入分母）。排查方向：OpenClaw 网关配置 / 后端模型连通性 / CLI 非交互模式参数。</div>'
    return (f'<div class="sub" style="font-weight:600;color:var(--txt);margin-top:14px">'
            f'Agent 框架集成（阶段 E · OpenClaw）<span class="pill p-mid" style="margin-left:8px">{rate} 通过</span></div>'
            f'<div class="note" style="margin:4px 0 6px">{env_line}｜本节验证 C8 覆盖不到的<b>真实工具执行循环</b>，独立于 C 通过率。</div>'
            f'{fail_note}'
            f'<table style="margin:6px 0 8px"><thead><tr><th>#</th><th>测试项</th><th>方法</th>'
            f'<th>实测结果</th><th class="c">判定</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')

def accel_short(acc):
    """加速栈一行摘要: 过滤表头/空值, 优先取含数字的型号词"""
    toks = [t for t in str(acc or "").replace(",", " ").split()
            if t not in ("Type", "N/A", "") and not t.startswith("mem=")]
    for t in toks:              # 型号词通常含数字 (M1000/A100/910B)
        if re.search(r"\d", t): return t
    return toks[0] if toks else "?"

def cfg_line(m):
    """对比表用一行运行配置摘要: 引擎 short-name + ctx + 量化"""
    eng = m.get("engine") or {}
    if not eng:
        return "v1.3 前数据·参数未记录"
    name = str(eng.get("engine_name", "?"))
    # 取引擎核心名 (去掉括号内的长描述)
    core = name.split("(")[0].strip() or name
    core = core if len(core) <= 30 else core[:29] + "…"
    ctx = str(eng.get("ctx_size", "?"))
    try:
        ctx = f"{int(ctx)//1024}K"
    except Exception: pass
    q = eng.get("model_quant", "?")
    return f"{core}｜ctx {ctx}｜{q}"

# ============ 单模型渲染 (供单模型报告 & 多模型明细复用) ============
def render_model_tests(c, mname):
    """渲染一个模型的 C1~C12 测试明细表, 返回 (html_rows, stats)
    stats: dict(decoder_tps_est, ttft, load_s, toolcall, multiturn, conc4_ok, vram, sample, graded_n, pass_n)
    """
    skipped = bool(c.get("skipped"))
    c2 = c.get("c2_short_decode", {}); c3 = c.get("c3_ttft", {})
    c4 = c.get("c4_long_ctx", {}); c8 = c.get("c8_toolcall", {})
    c9 = c.get("c9_multiturn", {}); c12 = c.get("c12_sample", "")
    conc2 = c.get("c6c7_conc2", {}); conc4 = c.get("c6c7_conc4", {})

    # 解码速度: 优先 API usage 真实 token 数 (tok/s), 无 usage 时降级为字/s 估算
    tps = 0.0; tps_src = "无"
    try:
        wl = float(c2.get("wall_s", 0)); ct = int(c2.get("completion_tokens", -1))
        if wl > 0 and ct > 0:
            tps = ct / wl; tps_src = "usage"
    except Exception: pass
    if tps == 0.0:
        try:
            if float(c2.get("wall_s", 0)) > 0 and int(c2.get("reply_len", 0)) > 0:
                tps = int(c2["reply_len"]) / float(c2["wall_s"]); tps_src = "est"
        except Exception: pass
    est_tps = tps
    # 峰值/均值双口径 (v1.11.1 起): 采集端流式 chunk 计时实测; 旧数据无此字段优雅降级
    # 注意: est_tps(usage 口径)本身就是持续均值, KPI 卡不得再标"最快"误导为峰值
    spd_peak = c2.get("speed_peak_tps")
    spd_mean = c2.get("speed_mean_tps")
    spd_method = c2.get("speed_method", "")
    # 流式均值与 usage 均值不一致时以 usage 为准（usage 是服务端权威统计）
    if isinstance(spd_mean, (int, float)) and tps_src == "usage" and tps > 0:
        spd_mean = round(tps, 1)

    trows = []
    def add(no, name, task, val, ok, note=""):
        trows.append(f'<tr><td>{no}</td><td><b>{name}</b></td><td>{task}</td><td>{val}</td>'
                     f'<td class="c">{verdict_cell(ok) if ok is not None else pill("记录","p-skip")}</td><td>{note}</td></tr>')

    if skipped:
        add("C", "模型实测（全部）", "C1~C12", "未执行", None,
            f"服务未就绪({esc(c.get('api'))})")
    else:
        lsec = c.get("c1_load_s")
        if lsec:
            c1val = f"{lsec}s"
        elif c.get("c1_probe_s"):
            c1val = (f"未冷启动；首请求就绪 {c['c1_probe_s']}s（含 JIT 权重加载，实测）")
        else:
            c1val = "未测（服务预先启动，禁止估算）"
        c1note = c.get("c1_note") or "SPEC 基线: 35B 级 <180s；服务预启动时 C1 不计入通过率"
        add("C1", "冷启动加载", "权重加载至 NPU 服务就绪", c1val, None, c1note)
        wl = float(c2.get("wall_s", 0)); rl = int(c2.get("reply_len", -1))
        ct = int(c2.get("completion_tokens", -1)); pt = int(c2.get("prompt_tokens", -1))
        if ct > 0 and wl > 0:
            c2val = f"{wl:.1f}s / {ct} tok = {est_tps:.1f} tok/s（usage 口径, prompt {pt} tok）"
            if isinstance(spd_peak, (int, float)):
                c2val += f"｜峰值 {spd_peak:.1f} tok/s（1s 窗口瞬时最大）"
        elif rl > 0:
            c2val = f"{wl:.1f}s / {rl} 字 ≈ {est_tps:.0f} 字/s（估算口径, 引擎未返回 usage）"
        else:
            c2val = "失败"
        add("C2", "解码速度（短输入）", "工业质检主题短文生成（关闭思考模式）",
            c2val, 1 if (ct > 0 or rl > 0) else 0, "SPEC 基线: 35B 级 ≥15 tok/s")
        if c3:
            ts = float(c3.get("s", -1))
            add("C3", "首字延迟 TTFT", "流式请求, 短 prompt「你好」首 chunk 到达",
                f"{ts:.2f}s", 1 if 0 < ts <= BASELINE["ttft_s"] else 0, "SPEC 基线: <1s")
        lw = float(c4.get("wall_s", 0)); lok = int(c4.get("ok", -1))
        lpt = int(c4.get("prompt_tokens", -1)); lct = int(c4.get("completion_tokens", -1))
        # prefill tok/s = prompt_tokens / (wall - 解码时间), 解码时间 = completion_tokens / 解码速度
        try:
            dec_s = lct / est_tps if (lct > 0 and est_tps > 0) else 0
            pf_tps = lpt / (lw - dec_s) if (lpt > 0 and lw > dec_s + 0.05) else 0
        except Exception:
            pf_tps = 0
        c5 = c.get("c5_ctx_decode", {})
        # v1.3.9: C5 流式同请求分段实测的 prefill 耗时优先于折算值
        pf_real = (lpt / c5["prefill_s"]) if (c5.get("prefill_s", 0) > 0 and lpt > 0) else 0
        if lok == 1 and pf_real > 0:
            c4val = f"{lw:.1f}s（prefill ≈{pf_real:.0f} tok/s, {lpt}+{lct} tok；C5 流式实测）"
        elif lok == 1 and pf_tps > 0:
            c4val = f"{lw:.1f}s（prefill ≈{pf_tps:.0f} tok/s, {lpt}+{lct} tok；折算）"
        elif lok == 1:
            c4val = f"{lw:.1f}s"
        else:
            c4val = "失败"
        add("C4", "长上下文 prefill+摘要", "~2000 token 智能制造长文输入 → 50 字总结",
            c4val, 1 if lok == 1 else 0,
            "prefill = prompt_tokens/首 chunk 前耗时（C5 流式实测）" if pf_real > 0
            else ("prefill tok/s = prompt_tokens/(总耗时−解码时间)（折算）" if pf_tps > 0
                  else "总结语义正确即通过"))
        # C5: SPEC §4.3 长上下文解码衰减（衰减 <20%）
        if c5.get("drop_pct") is not None:
            add("C5", "长上下文解码衰减", "同 C4 长上下文会话的解码速度 vs C2",
                f"prefill {c5['prefill_s']:.3f}s + 解码 {c5['decode_tps']:.1f} tok/s"
                f"（较 C2 衰减 {c5['drop_pct']:.1f}%）",
                c5.get("ok"), "SPEC 基线: 衰减 <20%；流式同请求分段计时（API 实测, 非估算）")
        else:
            add("C5", "长上下文解码衰减", "同 C4 长上下文会话的解码速度 vs C2",
                "未实测（缺流式分段计时）", None,
                esc(c5.get("error") or "旧数据无分段计时，按 SPEC 不计入通过率"))
        # C6/C7: 并发能力上探 (SPEC v1.7) — 单路基准 + 2/4/8/16/32 倍增阶梯
        conc_max = int(c.get("conc_max", 0) or 0)
        cb = c.get("conc_baseline", {})
        cbw = float(cb.get("wall_s", 0)) if cb else 0
        # 兼容旧数据: 无 conc_max 时从 c6c7_conc2/conc4 推导
        if not conc_max:
            _o2 = int(conc2.get("ok", 0)) if conc2 else 0
            _o4 = int(conc4.get("ok", 0)) if conc4 else 0
            if _o4 == 4: conc_max = 4
            elif _o2 == 2: conc_max = 2
        # C6 行: 阶梯各档明细
        lad_parts = []
        for n in (2, 4, 8, 16, 32):
            cc = c.get(f"c6c7_conc{n}", {})
            if not cc: continue
            okn = int(cc.get("ok", -1)); tot = int(cc.get("total", n))
            ctok = int(cc.get("completion_tokens", -1)); cwl = float(cc.get("wall_s", 0))
            v = cc.get("verdict", "")
            agg = ctok / cwl if (ctok > 0 and cwl > 0) else 0
            per = agg / n if agg > 0 else (cwl / n if cwl > 0 else 0)
            drop = ((per - cbw) / cbw * 100) if (cbw > 0 and per > 0) else None
            seg = f"{okn}/{tot}"
            if cwl: seg += f" {cwl:.1f}s"
            if per: seg += f" 单路≈{per:.0f} tok/s"
            if drop is not None: seg += f" 衰减{drop:.0f}%"
            if v == "degraded": seg += " ⚠衰减超标"
            elif okn < tot: seg += " ❌"
            lad_parts.append(f"{n}路: {seg}")
        if lad_parts:
            _cbnote = f"单路基准 {cbw:.1f}s" + (f" / {int(cb.get('completion_tokens',0) or 0)} tok" if cb and int(cb.get("completion_tokens", 0) or 0) > 0 else "") if cbw > 0 else "旧数据无单路基准，衰减按 wall/n 近似"
            add("C6", "并发阶梯（2/4/8/16/32）", "单路基准后逐档倍增，每档全部成功且衰减<30%才继续",
                " ｜ ".join(lad_parts), None, _cbnote)
        else:
            add("C6", "并发阶梯（2/4/8/16/32）", "单路基准后逐档倍增",
                "未采集（旧数据无阶梯明细）", None, "")
        # C7 行: 最大无衰减并发数 (conc_max)
        if conc_max >= 1:
            c7val = f"<b>{conc_max} 路</b>"
            c7ok = 1
            c7note = "SPEC: 倍增上探至首个失败/衰减≥30%档，前一档即设备并发承载上限"
            if conc_max >= 32:
                c7val += "（已触顶 32 路档，实际可能更高）"
        else:
            c7val = "单路基准失败，未上探"
            c7ok = 0
            c7note = "基准请求不通过无法判定并发能力"
        add("C7", "最大并发（conc_max）", "并发阶梯上探的实测无衰减上限",
            c7val, c7ok, c7note)
        add("C8", "工具调用 Function Calling", "OpenAI tools API: 查询北京天气(get_weather)",
            "正确发起调用", int(c8.get("ok", -1)), "finish_reason=tool_calls 且参数正确")
        add("C9", "多轮对话记忆", "3 轮对话, 第 3 轮复述第 1 轮设备编号",
            "正确引用 BX-7788", int(c9.get("ok", -1)), "Agent 多轮场景基础能力")
        add("C10", "显存占用", "加载后加速卡管理工具读数",
            esc(c.get("c10_vram", "N/A")), None, "记录值（无硬标准）")
        c11 = c.get("c11_mmproj")
        if c11 is not None:
            add("C11", "视觉多模态", "带 mmproj 启动 + 图片输入",
                esc(c11.get("val", "")), int(c11.get("ok", -1)), esc(c11.get("note", "")))
        else:
            add("C11", "视觉多模态", "带 mmproj 启动 + 图片输入", "未测", None,
                "需独立重启服务, 单独执行")
        add("C12", "输出质量抽查", "C2 生成文本人工抽查: 通顺/无乱码/无复读",
            "样本见下方", 1 if c12 and len(str(c12)) > 20 else None,
            "截取回复前 80 字供人工核验")

    graded = [r for r in trows if "✅" in r or "❌" in r]
    npass = sum(1 for r in graded if "✅" in r)

    stats = {
        "est_tps": est_tps,
        "tps_src": tps_src,
        "spd_peak": spd_peak,
        "spd_mean": spd_mean,
        "spd_method": spd_method,
        "ttft": float(c3.get("s", 0)) if c3 else 0,
        "load_s": c.get("c1_load_s"),
        "toolcall": int(c8.get("ok", -1)) if c8 else -1,
        "multiturn": int(c9.get("ok", -1)) if c9 else -1,
        "conc2_ok": int(conc2.get("ok", 0)) if conc2 else 0,
        "conc2_total": int(conc2.get("total", 2)) if conc2 else 2,
        "conc2_wall": float(conc2.get("wall_s", 0)) if conc2 else 0,
        "conc4_ok": int(conc4.get("ok", 0)) if conc4 else 0,
        "conc4_total": int(conc4.get("total", 4)) if conc4 else 4,
        "conc4_wall": float(conc4.get("wall_s", 0)) if conc4 else 0,
        "conc_max": conc_max,
        "vram": c.get("c10_vram", "N/A"),
        "c4_ok": int(c4.get("ok", -1)) if c4 else -1,
        "c2_wall": float(c2.get("wall_s", 0)) if c2 else 0,
        "sample": c12,
        "skipped": skipped,
        "graded_n": len(graded),
        "pass_n": npass,
    }
    return trows, stats

# ============ 主流程 ============
def redact_deep(value, red, key=None, device_label=""):
    """递归脱敏: dict/list/str 全覆盖, 其他类型原样返回。
    hostname 字段值定向替换为 `<主机·设备型号>` (只在字段级处理, 避免字符串级误伤)。"""
    if isinstance(value, str):
        if key == "hostname" and value.strip() and value.strip().lower() not in ("localhost", "unknown", "?"):
            return f"<主机·{device_label or '设备'}>"
        return red(value)
    if isinstance(value, list):
        return [redact_deep(v, red, key, device_label) for v in value]
    if isinstance(value, dict):
        return {k: redact_deep(v, red, k, device_label) for k, v in value.items()}
    return value

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    res_path = sys.argv[1]
    # Windows 默认 GBK, 中文 JSON/HTML 必须显式 UTF-8
    d = json.load(open(res_path, encoding="utf-8"))
    device = "AI Box"; model = "预装模型"; out_path = None
    topso = None; bwo = None; redact = True
    args = sys.argv[2:]; i = 0
    while i < len(args):
        if args[i] == "--device": device = args[i+1]; i += 2
        elif args[i] == "--model": model = args[i+1]; i += 2
        elif args[i] == "--tops": topso = args[i+1]; i += 2
        elif args[i] == "--bw": bwo = args[i+1]; i += 2
        elif args[i] == "--no-redact": redact = False; i += 1
        else: out_path = args[i]; i += 1

    # ---- 脱敏: 渲染前对整个结果 JSON 递归替换 (IP/IPv6/MAC/主机名) ----
    red, _ = make_redactor(redact, device_label=device)
    if redact:
        d = redact_deep(d, red, device_label=device)

    models = d.get("models")
    is_multi = isinstance(models, list) and len(models) > 0
    if not out_path:
        today = datetime.date.today().strftime("%Y%m%d")
        out_path = f"{device}_实测报告_{today}.html"

    a = d.get("phase_a", {}); b = d.get("phase_b", {}); c = d.get("phase_c", {})
    cls = d.get("classification", {})

    # 单模型且无 models 数组 → 沿用 phase_c
    if not is_multi:
        models = [{"name": model, "phase_c": c, "engine": d.get("engine", {})}]
        # 自动反解真实模型名：--model 未显式给出时，从引擎启动命令行的 -m 参数提取。
        # 背景（2026-11-18 修复）：collect 模式下模型名曾硬编码为"预装模型"，与分档推荐清单
        # 模糊匹配必然落空，报告误报"本轮无推荐清单内模型被实测"。数据无误，命名有误。
        if model == "预装模型":
            inferred = infer_model_name(models[0])
            if inferred:
                models[0]["name"] = inferred
                model = inferred

    # ---- 加速卡规格识别 ----
    accel_str = str(a.get("accelerator", ""))
    spec = {}
    for k, v in KNOWN_ACCEL.items():
        if k.lower() in accel_str.lower(): spec = v; break
    # 命令行覆盖仅在显式给出非空值时生效
    tops = topso if topso not in (None, "", "—", "-") else spec.get("tops", "N/A")
    bw = bwo if bwo not in (None, "", "—", "-") else spec.get("bw", "N/A")

    # ---- 先渲染所有模型 ----
    rendered = []  # [(name, trows_html, stats, m)]
    for m in models:
        mname = m.get("name", "未命名模型")
        mc = m.get("phase_c", {})
        # c1_load_s 可能在模型层级或 phase_c 内, 统一合并进 phase_c
        if isinstance(mc, dict) and "c1_load_s" in m and "c1_load_s" not in mc:
            mc = dict(mc); mc["c1_load_s"] = m["c1_load_s"]
        if m.get("error"):
            err = m["error"]
            reason = m.get("reason", "")
            if err == "file_not_found":
                err_txt, err_note = "模型文件不存在", "下发路径有误或未传完"
            elif err == "service_start_failed":
                err_txt, err_note = "服务启动失败", "查看服务日志排查（引擎不认该权重格式的可能性大）"
            elif err == "resource_short":
                err_txt, err_note = f"⏭ 磁盘/内存不足，暂未测试", esc(reason)
            else:
                err_txt, err_note = esc(err), ""
            trows = [f'<tr><td>C</td><td><b>全部测试</b></td><td>C1~C12</td><td>{err_txt}</td>'
                     f'<td class="c">{pill("⏭ 跳过","p-skip")}</td><td>{err_note}</td></tr>']
            stats = {"est_tps":0,"tps_src":"无","ttft":0,"load_s":None,"toolcall":-1,"multiturn":-1,
                     "conc2_ok":0,"conc2_total":2,"conc2_wall":0,"conc4_ok":0,"conc4_total":4,"conc4_wall":0,
                     "conc_max":0,
                     "vram":"N/A","c4_ok":-1,"c2_wall":0,"sample":"","skipped":True,"graded_n":0,"pass_n":0,"error":err}
        else:
            trows, stats = render_model_tests(mc, mname)
        rendered.append((mname, trows, stats, m))

    # ---- 汇总指标 (取第一个成功模型作主指标; multi 时取最优解码) ----
    ok_models = [r for r in rendered if not r[2].get("skipped")]
    if ok_models:
        main_stats = max(ok_models, key=lambda r: r[2]["est_tps"])[2]
        main_name = max(ok_models, key=lambda r: r[2]["est_tps"])[0]
    else:
        main_stats = rendered[0][2] if rendered else {}
        main_name = rendered[0][0] if rendered else "?"
    all_skipped = all(r[2].get("skipped") for r in rendered) if rendered else True

    # 总通过率 (所有模型 graded 汇总)
    tot_graded = sum(r[2]["graded_n"] for r in rendered)
    tot_pass = sum(r[2]["pass_n"] for r in rendered)
    rate = (tot_pass / tot_graded * 100) if tot_graded else 0
    badge = "b-green" if rate >= 90 else ("b-amber" if rate >= 70 else "b-red")
    label = "可用" if rate >= 90 else ("有条件可用" if rate >= 70 else "不可用")

    model_names = [r[0] for r in rendered]

    # ---- HTML 头部 ----
    title_models = " × ".join(model_names) if is_multi else model
    # 部署环境行: 引擎名 (模型级优先, 顶层兜底)
    _eng_src = d.get("engine") or (rendered[0][3].get("engine") if rendered and rendered[0][3].get("engine") else {}) or {}
    eng_name_line = _eng_src.get("engine_name") or "引擎信息未记录"
    # Chart.js 加载策略: 优先内嵌 vendor 本地文件 (离线可用), 无 vendor 时降级 CDN
    _vendor = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "chart.umd.min.js")
    if os.path.exists(_vendor):
        with open(_vendor, encoding="utf-8") as _f:
            _chart_js = _f.read()
        chart_script = f"<script>{_chart_js}</script>"
    else:
        chart_script = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'
    # v1.11.1: 摘要与 KPI 卡区分峰值/均值 — est_tps 是持续均值口径,
    # 不得标"最快"误导（推测解码引擎峰值可达均值 1.3~2 倍, 用户实测 46 vs 36 教训）
    _pk = main_stats.get('spd_peak')
    _pk_txt = (f"；峰值（1s 窗口瞬时最大）<b>{_pk:.1f} tok/s</b>"
               if isinstance(_pk, (int, float)) else "")
    _sum_tps_txt = (f"解码均值 <b>{main_stats.get('est_tps',0):.1f} tok/s</b>" + _pk_txt
                    + f"（{esc(main_name)}，{'API usage 真实 token 统计' if main_stats.get('tps_src')=='usage' else '估算口径'}）")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(device)} 实测报告</title>
{chart_script}
<style>{CSS}</style></head><body><div class="wrap">

<h1>{esc(device)} 实测报告 <span class="badge {badge}">{label} {rate:.0f}%</span></h1>
<div class="sub">测试模型：{esc(title_models)} ｜ SPEC v{SPEC_VERSION} ｜ boxbench v{d.get('boxbench_version','?')} ｜ {esc(d.get('timestamp',''))} ｜ 主机 {esc(a.get('hostname','?'))}</div>
<div class="sub" style="margin-top:4px">部署环境：{esc(eng_name_line)} ｜ 加速栈：{esc(accel_short(a.get('accelerator','')))} ｜ 系统：{esc(a.get('os','?'))}（{esc(a.get('kernel','?'))}）</div>

<div class="summary"><p><b>摘要：</b>在 {esc(device)} 上对 <b>{esc(title_models)}</b> 执行 SPEC v{SPEC_VERSION} 标准实测。
{('共 ' + str(len(rendered)) + ' 个模型，每模型 C1~C12 项测试 + 横向对比。' if is_multi else '')}
总计 {tot_graded} 项判定，通过 {tot_pass} 项（{rate:.0f}%）。
{_sum_tps_txt}。</p></div>
"""
    # ---- 管理层摘要（白话结论, 前置于所有技术细节, 产出质量: 可直接提交管理层）----
    def _yes(v): return "✅ " + v
    _conc = main_stats.get('conc_max', 0)
    _tps = main_stats.get('est_tps', 0)
    _load = main_stats.get('load_s')
    # 白话场景判定: 并发+工具调用+解码速度 → 能支撑什么业务
    _scene_bits = []
    if not all_skipped:
        if main_stats.get('toolcall') == 1 and main_stats.get('multiturn') == 1:
            _scene_bits.append("智能问答 / Agent 应用（工具调用与多轮记忆实测通过）")
        else:
            _scene_bits.append("基础问答（Agent 能力见明细 C8/C9）")
        if _tps >= 15:
            _scene_bits.append("日常文档生成（单字速度相当于每秒 {_tps:.0f} 字左右，阅读无卡顿）".format(_tps=_tps))
        if _conc >= 2:
            _scene_bits.append(f"小团队共用（实测 {_conc} 人同时提问互不影响）")
    _scene = "；".join(_scene_bits) if _scene_bits else "本轮服务未就绪，详见实测明细"
    _one_line = (f"这台 {esc(device)} 整体判定为「<b>{label}</b>」（{rate:.0f}% 测试项达标），"
                 f"推荐跑 <b>{esc(main_name)}</b>。它能干什么：{_scene}。"
                 + (f"从开机加载到可用约 {int(_load)} 秒。" if isinstance(_load, (int, float)) and _load else ""))
    exec_summary = f"""
<div class="panel" style="border-left:4px solid var(--accent)">
<div class="sub" style="font-weight:700;font-size:14px;color:var(--txt);margin-bottom:6px">管理层摘要（30 秒版）</div>
<p style="margin:6px 0">{_one_line}</p>
<p style="margin:6px 0;color:var(--muted);font-size:13px">全部结论均来自本机实测数据（非厂商标称）；技术明细见下文各节，原始 JSON 可复核。</p>
</div>
"""
    html += exec_summary

    # ---- KPI 卡 ----
    html += f"""
<div class="cards">
  <div class="card"><div class="k">AI 算力</div><div class="v hl">{esc(tops)}</div><div class="k">NPU INT8</div></div>
  <div class="card"><div class="k">内存带宽</div><div class="v hl">{esc(bw)}</div><div class="k">统一内存</div></div>
  <div class="card"><div class="k">推理显存</div><div class="v">{esc(cls.get('infer_mem_gb','?'))}<small> GB 可用</small></div><div class="k">加载后占用 {esc(main_stats.get('vram','-'))}</div></div>
  <div class="card"><div class="k">解码速度（峰值/均值）</div><div class="v">{((('%s' % ('%.1f' % main_stats['spd_peak'])) if isinstance(main_stats.get('spd_peak'),(int,float)) else '—') + '<small>/</small>' + ('%.1f' % main_stats.get('est_tps',0)))}<small> tok/s</small></div><div class="k">{esc(main_name)}｜峰值=1s 瞬时窗</div></div>
  <div class="card"><div class="k">最大并发</div><div class="v">{main_stats.get('conc_max',0)}<small> 路无衰减</small></div><div class="k">阶梯上探实测</div></div>
  <div class="card"><div class="k">首字延迟</div><div class="v">{main_stats.get('ttft',0):.2f}<small> s</small></div><div class="k">TTFT 最优模型</div></div>
</div>
"""

    # ---- 一、核心规格 ----
    html += f"""
<h2>一、核心硬件规格</h2>
<div class="panel"><table>
<thead><tr><th style="width:24%">项目</th><th>规格</th></tr></thead><tbody>
<tr><td>AI 加速卡</td><td><b>{esc(accel_str or 'N/A')}</b>（算力 {esc(tops)}，带宽 {esc(bw)}）</td></tr>
<tr><td>SoC / CPU</td><td>{esc(a.get('cpu_model','')).strip()} × {esc(a.get('cpu_cores','?'))} 核（{esc(a.get('cpu_arch','?'))}，最高 {esc(str(a.get('cpu_max_mhz','0')).strip())} MHz）</td></tr>
<tr><td>内存</td><td>统一内存 {esc(a.get('mem_total','?'))}（可用 {esc(a.get('mem_available','?'))}）— CPU/NPU 共享</td></tr>
<tr><td>存储</td><td>根分区 {esc(a.get('root_disk','?'))}｜块设备：{esc(a.get('blocks','?'))}</td></tr>
<tr><td>系统</td><td>{esc(a.get('os','?'))}（内核 {esc(a.get('kernel','?'))}）</td></tr>
<tr><td>网络</td><td>{esc(a.get('interfaces','?'))}</td></tr>
<tr><td>负载（采集时）</td><td>{esc(str(a.get('load','?')).strip())}</td></tr>
</tbody></table>
<div class="note">规格卡中的算力/带宽取自已知加速卡规格表；如需修正可用 <code>--tops</code> / <code>--bw</code> 参数覆盖。其余均为本机采集实测值。</div>
</div>
"""

    # ---- 二、硬件分档 ----
    if cls:
        # 实测模型名与推荐清单名模糊匹配（去空格/大小写对齐）
        def norm(x): return str(x).replace(" ", "").lower()
        # 匹配兜底: 再去掉连字符/点/括号, 使 "Qwen3.6 35B A3B" 可命中 "Qwen3.6-35B-A3B(W4A8)"
        def norm_loose(x):
            import re as _re
            return _re.sub(r"[-.()（）]", "", norm(x))
        tested_map = {}
        for mname, trows, stats, m in rendered:
            for rec in cls.get("recommended_models", []):
                lr, lm = norm_loose(rec), norm_loose(mname)
                if (norm(rec) == norm(mname) or norm(rec) in norm(mname) or norm(mname) in norm(rec)
                        or lr == lm or lr in lm or lm in lr):
                    tested_map[rec] = stats
                    break
        html += "<h2>二、硬件分档与模型匹配</h2><div class=\"panel\">"
        html += build_tier_bar(cls)
        html += build_recommend_table(cls, cls.get("tier", "D4"), tested_map)
        html += "</div>"

    # ---- 多模型横向对比表 (multi 模式) ----
    if is_multi:
        html += f"""
<h2>三、多模型横向对比</h2>
<div class="panel">
<table>
<thead><tr><th>指标</th>{''.join(f'<th class="c">{esc(n)}</th>' for n in model_names)}</tr></thead>
<tbody>
<tr><td><b>运行配置</b></td>{''.join(f'<td class="c"><span style="font-size:12px">{esc(cfg_line(r[3]))}</span></td>' for r in rendered)}</tr>
<tr><td><b>加载耗时 C1</b></td>{''.join(f'<td class="c">{esc(str(r[2]["load_s"]) + "s") if r[2]["load_s"] else "—"}</td>' for r in rendered)}</tr>
<tr><td><b>解码速度 C2</b></td>"""
        # 解码行加高亮最优；v1.11.1 起带峰值/均值双口径（旧数据无峰值则只显均值）
        best_tps = max((r[2]["est_tps"] for r in rendered), default=0)
        for r in rendered:
            _sp = r[2].get("spd_peak")
            if isinstance(_sp, (int, float)):
                v = f'峰值 {_sp:.1f} / 均值 {r[2]["est_tps"]:.1f} tok/s'
            else:
                v = f'{r[2]["est_tps"]:.1f} tok/s' + ('' if r[2].get("tps_src") == "usage" else ' (估)')
            cell = f'<span class="best">{v} ◀</span>' if r[2]["est_tps"] == best_tps and best_tps > 0 else v
            html += f'<td class="c">{cell}</td>'
        html += f'</tr>\n<tr><td><b>首字延迟 C3</b></td>'
        best_ttft = min((r[2]["ttft"] for r in rendered if r[2]["ttft"] > 0), default=0)
        for r in rendered:
            v = f'{r[2]["ttft"]:.2f}s'
            cell = f'<span class="best">{v} ◀</span>' if r[2]["ttft"] == best_ttft and best_ttft > 0 else v
            html += f'<td class="c">{cell}</td>'
        html += f'</tr>\n<tr><td><b>长上下文 C4</b></td>'
        for r in rendered:
            ok = r[2]["c4_ok"]
            cell = "✅ 正确" if ok == 1 else ("❌" if ok == 0 else "—")
            html += f'<td class="c">{cell}</td>'
        html += f'</tr>\n<tr><td><b>最大并发 C7</b></td>'
        best_conc = max((r[2].get("conc_max", 0) for r in rendered), default=0)
        for r in rendered:
            cm = r[2].get("conc_max", 0)
            v = f"{cm} 路" if cm else "—"
            cell = f'<span class="best">{v} ◀</span>' if cm == best_conc and cm > 0 else v
            html += f'<td class="c">{cell}</td>'
        html += f'</tr>\n<tr><td><b>工具调用 C8</b></td>'
        for r in rendered:
            ok = r[2]["toolcall"]
            cell = "✅ 通过" if ok == 1 else ("❌ 失败" if ok == 0 else "—")
            html += f'<td class="c">{cell}</td>'
        html += f'</tr>\n<tr><td><b>多轮记忆 C9</b></td>'
        for r in rendered:
            ok = r[2]["multiturn"]
            cell = "✅ 通过" if ok == 1 else ("❌ 失败" if ok == 0 else "—")
            html += f'<td class="c">{cell}</td>'
        html += f'</tr>\n<tr><td><b>显存占用 C10</b></td>'
        for r in rendered:
            html += f'<td class="c">{esc(r[2]["vram"])}</td>'
        html += f'</tr>\n<tr><td><b>NPU 利用率（prefill/解码）</b></td>'
        for r in rendered:
            mc = r[3].get("phase_c", {})
            pf = ((mc.get("c4_long_ctx") or {}).get("npu") or {}).get("util_avg")
            dec = ((mc.get("c2_short_decode") or {}).get("npu") or {}).get("util_avg")
            f = lambda v: f"{v:.0f}%" if isinstance(v, (int, float)) else "—"
            html += f'<td class="c"><span style="font-size:12px">{f(pf)} / {f(dec)}</span></td>'
        html += f'</tr>\n<tr><td><b>测试期温度峰值</b></td>'
        for r in rendered:
            tmax = (r[3].get("phase_c", {}) or {}).get("session_temp_max")
            html += f'<td class="c">{f"{tmax:.1f}℃" if isinstance(tmax,(int,float)) and tmax>0 else "—"}</td>'
        html += f'</tr>\n<tr><td><b>Agent 集成 E（OpenClaw）</b></td>'
        for r in rendered:
            pe = r[3].get("phase_e") or {}
            if pe.get("skipped"):
                cell = '<span class="skip">⏭ 跳过</span>'
            elif pe:
                keys = ["e2_chat", "e3_tool", "e4_chain", "e5_budget", "e6_fallback"]
                vals = [int(pe.get(k, {}).get("ok", -1)) for k in keys]
                np_ = sum(1 for v in vals if v == 1); ng = sum(1 for v in vals if v in (0, 1))
                cls = "ok" if ng and np_ == ng else ("no" if ng and np_ < ng / 2 else "mid")
                cell = f'<span class="{cls}">{np_}/{ng}</span>' if ng else '<span class="skip">—</span>'
            else:
                cell = '<span class="skip">—</span>'
            html += f'<td class="c">{cell}</td>'
        html += f'</tr>\n<tr><td><b>通过率</b></td>'
        for r in rendered:
            s = r[2]
            if s["graded_n"]:
                rr = s["pass_n"] / s["graded_n"] * 100
                html += f'<td class="c">{s["pass_n"]}/{s["graded_n"]}（{rr:.0f}%）</td>'
            else:
                html += f'<td class="c">—</td>'
        html += f"""
</tr>
</tbody></table>
<div class="legend">◀ 标记该指标最优模型。解码均值 = completion_tokens / 耗时（tok/s，API usage 口径，即持续负载均速，<b>不是引擎上限</b>）；峰值 = 流式 1s 滑动窗口最大瞬时速度（推测解码引擎可达均值 1.3~2 倍）；标「估」为旧数据（字/s 估算）。并发行速度见各模型明细。</div>
</div>

<h2>四、性能对比图表</h2>
<div class="panel"><div class="grid2">
<div><div class="sub" style="font-weight:600;color:var(--txt)">解码速度对比（tok/s）</div>
<div class="chartbox"><canvas id="cTps"></canvas></div></div>
<div><div class="sub" style="font-weight:600;color:var(--txt)">加载耗时对比（秒）</div>
<div class="chartbox"><canvas id="cLoad"></canvas></div></div>
</div></div>
"""
        section_no = "五"
    else:
        section_no = "三"

    # ---- 每模型实测明细 ----
    html += f'<h2>{"五" if is_multi else "三"}、{"各模型" if is_multi else ""}实测明细（SPEC v{SPEC_VERSION}）</h2>\n'
    html += f"""<div class="note" style="margin:8px 0 14px"><b>C1~C12 导读</b>：SPEC 定义的 12 项标准化测试——C1 冷启动加载（权重→NPU 就绪耗时）｜C2 解码速度（生成 tok/s）｜C3 首字延迟 TTFT（用户体感快慢）｜C4 长上下文 prefill（长文吞入速度）｜C5 温度稳定性（持续推理温升）｜C6/C7 并发上探（单路基准→倍增阶梯→最大无衰减并发）｜C8 工具调用（Agent 能力）｜C9 多轮记忆（对话上下文保持）｜C10 显存占用｜C11 视觉多模态｜C12 输出质量抽查｜C14 NPU 算力利用率（各模型明细末尾"算力利用率分析"表）。每项含"测试任务"（怎么测的）与"基线"（及格线）。</div>\n"""
    for idx, (mname, trows, stats, m) in enumerate(rendered):
        sid = f"m{idx}"
        eng_cfg_html = build_engine_cfg(m, d.get("engine"))
        if is_multi:
            err = stats.get("error")
            if err == "resource_short":
                head_badge = pill("⏭ 资源不足·暂未测试", "p-skip")
            elif err:
                head_badge = pill("失败", "p-no")
            else:
                head_badge = pill(
                    f'{stats["pass_n"]}/{stats["graded_n"]} 通过', "p-ok" if stats["graded_n"] and stats["pass_n"]==stats["graded_n"] else "p-mid")
            html += f"""<div class="mblock">
<div class="mhead"><span><span class="tagchip">模型 {idx+1}</span> {esc(mname)}</span>{head_badge}</div>
<div class="mbody">{eng_cfg_html}"""
        if not is_multi:
            html += eng_cfg_html
        html += f"""<table>
<thead><tr><th>#</th><th>测试项</th><th>测试任务</th><th>实测结果</th><th class="c">判定</th><th>基线/说明</th></tr></thead>
<tbody>
{''.join(trows)}
</tbody></table>
<div class="note">通过率：<b>{stats["pass_n"]}/{stats["graded_n"]}</b>。计时为 API 往返口径。跳过/记录项不计入分母。</div>"""
        if not stats.get("skipped") and stats.get("sample"):
            html += f"""<div class="sample"><span class="q">Prompt：请写一段250字左右的短文，介绍人工智能在工业质检中的应用</span><br><br>{esc(stats["sample"])}……</div>"""
        util_html = build_util_section(m.get("phase_c", {}), tops)
        if util_html:
            html += util_html
        agent_html = build_agent_section(m.get("phase_e") or (d.get("phase_e") if not is_multi else None))
        if agent_html:
            html += agent_html
        if is_multi:
            html += "</div></div>"

    # ---- C13 上下文阶梯测试 (有 ctxtest 数据时) ----
    ctxd = d.get("ctxtest") or {}
    if ctxd.get("levels"):
        html += """
<h2>上下文阶梯验证（C13）</h2>
<div class="panel">
<div class="note" style="margin-bottom:8px">C1~C12 在 ctx-size 8K 下测试（短输入场景），模型<b>标称大窗口</b>是否真实、显存随窗口涨多少，由本节回答。每档：以该窗口重启服务 → 塞入约 55% 窗口长度的文本（头部埋随机暗号）→ 验证 prefill 速度、暗号召回（长程记忆）、显存。</div>
<table>
<thead><tr><th>档位</th><th class="c">加载</th><th class="c">prefill 输入</th><th class="c">耗时</th><th class="c">prefill 速度</th><th class="c">暗号召回</th><th class="c">显存</th></tr></thead>
<tbody>"""
        for lv in ctxd["levels"]:
            lvl = lv.get("level", "?"); nctx = lv.get("ctx", 0)
            if lv.get("error"):
                html += f'<tr><td><b>{esc(lvl)}</b>（{nctx//1024}K）</td><td colspan="6" class="c"><span class="skip">⏭ {esc(lv["error"])}</span></td></tr>'
                continue
            r = lv.get("result", {})
            pt = int(r.get("prompt_tokens", -1)); wall = float(lv.get("wall_s", 0))
            # prefill 速度 ≈ prompt_tokens/(总耗时-解码时间); 解码时间≈completion_tokens/35(粗估) → 简化: prompt_tokens/wall_s 为下限口径
            prefill_tps = f"{pt/wall:.0f} tok/s" if pt > 0 and wall > 0 else "—"
            hit = r.get("secret_hit", -1)
            hit_cell = ('<span class="ok">✅ 召回</span>' if hit == 1 else
                        '<span class="no">❌ 丢失</span>' if hit == 0 else '<span class="skip">—</span>')
            ans = str(r.get("answer", ""))[:40]
            ans_tip = f'<div class="skip" style="font-size:11px">答: {esc(ans)}</div>' if ans else ""
            html += (f'<tr><td><b>{esc(lvl)}</b>（{nctx//1024}K）</td>'
                     f'<td class="c">{lv.get("load_s","—")}s</td>'
                     f'<td class="c">{pt:,} tok</td>'
                     f'<td class="c">{wall:.1f}s</td>'
                     f'<td class="c">{prefill_tps}</td>'
                     f'<td class="c">{hit_cell}{ans_tip}</td>'
                     f'<td class="c">{esc(lv.get("vram","—"))}</td></tr>')
        cm = ctxd.get("claimed_max_ctx")
        if cm:
            html += f'<tr><td colspan="7" class="skip">模型自报窗口上限: {cm:,}（{cm//1024}K）｜暗号召回失败 = 标称窗口与真实能力不符（注意力稀释/截断）</td></tr>'
        html += "</tbody></table></div>"
        # 结论区更新长上下文行
        hits = [lv for lv in ctxd["levels"] if lv.get("result", {}).get("secret_hit") == 1]
        if hits:
            mx = max(lv.get("ctx", 0) for lv in hits)
            html_last_ctx = f"✅ 上下文阶梯实测通过至 {mx//1024}K（暗号召回）"
        else:
            html_last_ctx = "⚠ 阶梯档位未见暗号召回，长程记忆存疑"
    else:
        html_last_ctx = None

    # ---- 环境盘点 ----
    mf = b.get("model_files", [])
    env_no = "六" if is_multi else "四"
    html += f"""
<h2>{env_no}、设备环境盘点</h2>
<div class="panel"><table>
<thead><tr><th style="width:180px">采集项</th><th>内容</th></tr></thead><tbody>
<tr><td>已发现模型权重（{len(mf)} 个）</td><td>{'<br>'.join(f"{esc(m.get('path'))} <span class=skip>({esc(m.get('size'))}, {esc(m.get('mtime'))})</span>" for m in mf) if mf else '未发现'}</td></tr>
<tr><td>推理引擎路径</td><td><code>{esc(b.get('engine_paths','无'))}</code></td></tr>
<tr><td>容器</td><td>{esc(b.get('docker','无'))}</td></tr>
<tr><td>推理服务端口</td><td>{esc(b.get('ai_services','无'))}</td></tr>
</tbody></table></div>
"""

    # ---- 结论 ----
    concl_no = "七" if is_multi else "五"
    best_model = main_name
    # 算力利用结论: 取最优模型的 prefill/util 数据
    util_concl = "—"
    if not all_skipped:
        mc = (rendered[0][3].get("phase_c", {}) if rendered else {})
        for r_ in rendered:
            if not r_[2].get("skipped") and r_[0] == main_name:
                mc = r_[3].get("phase_c", {}); break
        pf = ((mc.get("c4_long_ctx") or {}).get("npu") or {}).get("util_avg")
        dec = ((mc.get("c2_short_decode") or {}).get("npu") or {}).get("util_avg")
        f_ = lambda v: f"{v:.0f}%" if isinstance(v, (int, float)) else None
        if f_(pf) == "0%" and f_(dec) == "0%":
            util_concl = "OS 侧利用率计数器不可用（驱动未实现，读数恒 0）——算力利用以实测吞吐（C2/C4）与显存/温度占用为证据链"
        elif f_(pf) or f_(dec):
            util_concl = (f"prefill {f_(pf) or '—'} / 解码 {f_(dec) or '—'}（{esc(main_name)}）。"
                          f"解码利用率低是 LLM 访存受限共性；prefill 利用率反映计算密集段真实算力发挥")
        else:
            util_concl = "未采集（boxbench v1.5 起支持）"
    html += f"""
<h2>{concl_no}、结论</h2>
<div class="panel"><table>
<thead><tr><th style="width:200px">结论项</th><th>判定</th></tr></thead><tbody>
<tr><td>综合可用性</td><td>{pill(label + f'（{rate:.0f}%）', 'p-ok' if rate>=90 else ('p-mid' if rate>=70 else 'p-no'))}</td></tr>
<tr><td>NPU 算力利用评估</td><td>{util_concl}</td></tr>
<tr><td>{'推荐模型' if is_multi else '测试模型'}</td><td><b>{esc(best_model)}</b>（解码均值 {main_stats.get('est_tps',0):.1f} tok/s{'，峰值 ' + format(main_stats['spd_peak'], '.1f') + ' tok/s' if isinstance(main_stats.get('spd_peak'),(int,float)) else ''}，{'usage 口径' if main_stats.get('tps_src')=='usage' else '估算口径'}）</td></tr>
<tr><td>建议并发规模</td><td>{f'<b>{main_stats.get("conc_max",0)} 路并发无衰减</b>（阶梯上探实测口径）' if not all_skipped else '未测（服务未就绪）'}</td></tr>
<tr><td>Agent 场景可用性</td><td>{'✅ 工具调用 + 多轮记忆均通过' if not all_skipped and main_stats.get('toolcall')==1 and main_stats.get('multiturn')==1 else '见实测明细 C8/C9'}</td></tr>
<tr><td>长上下文能力</td><td>{html_last_ctx or ('✅ ~2000 token prefill + 摘要正确' if not all_skipped and main_stats.get('c4_ok')==1 else '见实测明细 C4')}</td></tr>
<tr><td>数据口径</td><td>全部数值来自本机实测（API 计时 + 管理工具读数），非厂商标称值</td></tr>
</tbody></table></div>

<div class="panel" style="margin-top:14px">
<div class="sub" style="font-weight:700;color:var(--txt);margin-bottom:6px">人工复核记录（对外提交前必填，符合"对外发送须人工复核"合规要求）</div>
<table>
<tbody>
<tr><td style="width:200px">结论数字与原始 JSON 一致性抽查</td><td>☐ 已抽查（对照第{"五" if is_multi else "三"}节明细与 JSON 的 C1~C12 数值）</td></tr>
<tr><td>敏感信息检查（IP/账号/主机名/密钥）</td><td>☐ 已检查，报告内无未脱敏信息</td></tr>
<tr><td>输出质量抽查（C12 评语）</td><td>☐ 人工已读生成样例，无乱码/复读</td></tr>
<tr><td>复核人 / 复核日期</td><td>＿＿＿＿＿＿ / ＿＿＿＿＿＿</td></tr>
</tbody>
</table>
</div>

<div class="foot">BoxBench v{d.get('boxbench_version','?')} · SPEC v{SPEC_VERSION} · 渲染于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} · 原始 JSON 可复核{' · 已脱敏(IP/主机名替换为占位符)' if redact else ' · ⚠ 未脱敏版(仅内部使用)'}</div>
</div></body></html>
"""

    # ---- 图表脚本 ----
    chart_js_parts = []
    if is_multi and not all_skipped:
        labels = json.dumps(model_names, ensure_ascii=False)
        tps_data = [round(r[2]["est_tps"], 1) for r in rendered]
        load_data = [r[2]["load_s"] if isinstance(r[2]["load_s"], (int, float)) else 0 for r in rendered]
        chart_js_parts.append(f"""
new Chart(cTps,{{type:'bar',data:{{labels:{labels},
datasets:[{{data:{json.dumps(tps_data)},backgroundColor:['#3fb950','#58a6ff','#d29922','#f85149','#a371f7']}}]}},
options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>c.parsed.y.toFixed(1)+' tok/s'}}}}}},
scales:{{x:{{grid:{{color:'#21262d'}}}},y:{{grid:{{color:'#21262d'}},beginAtZero:true,title:{{display:true,text:'tok/s'}}}}}}}}}});
new Chart(cLoad,{{type:'bar',data:{{labels:{labels},
datasets:[{{data:{json.dumps(load_data)},backgroundColor:'#58a6ff'}}]}},
options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>c.parsed.y+' s'}}}}}},
scales:{{x:{{grid:{{color:'#21262d'}}}},y:{{grid:{{color:'#21262d'}},beginAtZero:true,title:{{display:true,text:'秒'}}}}}}}}}});
""")
    elif not is_multi and not all_skipped:
        # 单模型: 并发吞吐 + 阶段耗时
        ms = main_stats
        per2 = ms["conc2_ok"] * 200 * 0.6 / ms["conc2_wall"] if ms["conc2_wall"] > 0 else 0
        per4 = ms["conc4_ok"] * 200 * 0.6 / ms["conc4_wall"] / 4 if ms["conc4_wall"] > 0 else 0
        chart_js_parts.append(f"""
const C={{win:'#3fb950',bad:'#f85149',warn:'#d29922',acc:'#58a6ff',mut:'#9aa7b4'}};
Chart.defaults.color=C.mut;Chart.defaults.font.family='-apple-system,Segoe UI,PingFang SC,sans-serif';
Chart.defaults.borderColor='#2d3748';const grid={{color:'#21262d'}};
""")

    if chart_js_parts:
        script = "<script>\nChart.defaults.color='#9aa7b4';Chart.defaults.font.family='-apple-system,Segoe UI,PingFang SC,sans-serif';Chart.defaults.borderColor='#2d3748';\n" + "\n".join(chart_js_parts) + "\n</script>"
        html = html.replace("</body></html>", script + "</body></html>")

    open(out_path, "w", encoding="utf-8", newline="\n").write(html)
    try:
        print(f"OK -> {out_path}")
    except UnicodeEncodeError:
        # Windows GBK 控制台打不出中文文件名：转为可显示形式输出
        print(f"OK -> {out_path}".encode("unicode_escape").decode())

# ---------- 经验池自动 push（渲染成功后触发，幂等不重传） ----------
# 背景（2026-11-26）：push 原为 SKILL.md 第6步的手动步骤，靠 Agent 记性执行，
# Gyro-S 那轮在改 JSON/重渲染循环中被漏掉。改为渲染成功后自动触发：
#   - 本地台账 ~/.boxbench/pushed_ledger.json 按 evidence_hash 记录已推送，幂等
#   - 失败不阻塞渲染（outbox 兜底），BOXBENCH_CONTRIBUTE=0 / --no-push 可退出
def auto_push_to_commons(res_path: str):
    """渲染成功后自动 push 经验池。幂等：同一 evidence_hash 不重复 push。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import boxbench_exp as exp
    except ImportError:
        print("[exp] boxbench_exp.py 不在旁路，跳过自动 push", file=sys.stderr)
        return
    if not exp.contribution_enabled():
        print("[exp] BOXBENCH_CONTRIBUTE=0，跳过自动 push", file=sys.stderr)
        return
    try:
        d = json.load(open(res_path, encoding="utf-8"))
    except Exception as e:
        print(f"[exp] 结果 JSON 读取失败，跳过自动 push: {e}", file=sys.stderr)
        return
    platform = exp.derive_platform_key(d)
    if not platform:
        print("[exp] 平台键无法推断（engine.engine_name 缺失），跳过自动 push", file=sys.stderr)
        return
    # 跳过占位数据：无 phase_c 说明没实测，不产经验
    if not (d.get("phase_c") or d.get("models")):
        print("[exp] 无实测数据（phase_c/models 空），跳过自动 push", file=sys.stderr)
        return
    atom = exp.make_atom(d, platform)
    ev_hash = atom.get("evidence_hash", "")
    ledger_path = exp.state_dir() / "pushed_ledger.json"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    except Exception:
        ledger = {}
    if ev_hash and ev_hash in ledger:
        print(f"[exp] 已推送过（evidence_hash {ev_hash[:12]}…），跳过重复 push")
        return
    # 入 outbox（断网兜底），再尽力上传
    path = exp.enqueue(atom)
    print(f"[exp] queued: {path}")
    outcome = exp.flush()
    if outcome.get("ok"):
        ledger[ev_hash] = {"platform": platform, "atom_id": atom["atom_id"][:16],
                           "ts": datetime.datetime.now().isoformat(timespec="seconds")}
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[exp] 自动 push 完成（platform={platform}, sent={outcome.get('sent',0)}）")
    else:
        print(f"[exp] 上传失败，atom 已留在 outbox（exp flush 可重传）: {outcome}", file=sys.stderr)


if __name__ == "__main__":
    main()
    # 渲染成功才走到这；渲染异常/退出不会执行自动 push
    _res = sys.argv[1] if len(sys.argv) > 1 else None
    if _res and "--no-push" not in sys.argv:
        auto_push_to_commons(_res)
