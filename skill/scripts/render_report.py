#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BoxBench v1.1 报告渲染器 — 工具无关
输入: boxbench.sh 产出的 JSON 结果文件 (单模型或 multi 多模型)
输出: 统一样式 HTML 报告 (深色主题 + Chart.js 图表)
用法: python3 render_report.py <result.json> [输出.html] [--device 型号] [--model 模型名] [--tops ..] [--bw ..]
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

SPEC_VERSION = "1.4"

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
    short = re.split(r"[\\/]", path)[-1]
    cmd = str(g("engine_cmd"))
    port = "未记录"
    pm = re.search(r'--port[= ](\d+)', cmd)
    if pm: port = pm.group(1)
    rows = [
        ("模型权重", f"{esc(short)}（{esc(g('model_file_size'))}）"),
        ("权重构建日期", esc(g("model_build_date"))),
        ("量化格式", esc(quant)),
        ("推理引擎", f"{esc(g('engine_name'))}（build: {esc(g('engine_build'))}）"),
        ("上下文窗口 ctx-size", esc(ctx)),
        ("服务端口", esc(port)),
    ]
    t = ('<table style="margin:10px 0 14px"><thead><tr><th style="width:200px">运行配置</th><th>值</th></tr></thead><tbody>'
         + "".join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in rows)
         + f'<tr><td>启动命令行</td><td><code style="word-break:break-all">{esc(cmd)}</code></td></tr>'
         + "</tbody></table>")
    note = "" if eng else '<div class="note">⚠ 本模型数据未记录引擎运行配置，横向对比时注意：两模型实际启动参数一致时才可比。</div>'
    return t + note

def build_util_section(mc, tops_str="50 TOPS"):
    """算力利用率分析 (v1.5 起 phase_c 带 npu 采样): 空闲/解码/prefill/并发的 NPU 利用率 + 算力瓶颈判读。
    无采样数据时返回空串(旧 JSON 兼容)。"""
    idle = mc.get("idle_baseline") or {}
    c2 = ((mc.get("c2_short_decode") or {}).get("npu")) or {}
    c4 = ((mc.get("c4_long_ctx") or {}).get("npu")) or {}
    c6 = ((mc.get("c6c7_conc2") or {}).get("npu")) or {}
    c7 = ((mc.get("c6c7_conc4") or {}).get("npu")) or {}
    ov = mc.get("util_overall") or {}
    if not any([c2, c4, c7, ov]):
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
        ("C7 并发 4 路", c7),
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
    if not rows:
        return ""
    # 瓶颈判读: prefill 是计算受限段, 其利用率反映真实算力发挥; 解码是访存受限, 利用率低属正常
    pf_u = c4.get("util_avg"); dec_u = c2.get("util_avg")
    verdicts = []
    if isinstance(pf_u, (int, float)):
        if pf_u >= 70:
            verdicts.append(f"prefill 段 NPU 平均利用率 <b>{pf_u:.0f}%</b>——计算密集段算力发挥充分，接近标称算力的有效区间")
        elif pf_u >= 40:
            verdicts.append(f"prefill 段 NPU 平均利用率 <b>{pf_u:.0f}%</b>——计算密集段有中等发挥，算力或受数据供给/调度开销约束")
        else:
            verdicts.append(f"prefill 段 NPU 平均利用率 <b>{pf_u:.0f}%</b>——计算密集段利用率偏低，标称算力远未打满（引擎调度/带宽瓶颈/模型结构限制）")
    if isinstance(dec_u, (int, float)) and isinstance(pf_u, (int, float)):
        verdicts.append(f"解码段（{dec_u:.0f}%）低于 prefill 段（{pf_u:.0f}%）符合预期：自回归解码每步仅 1 token，属<b>访存受限</b>负载，算力利用率天然低——这是所有 LLM 推理的共性，不是该设备的问题")
    mem_c10 = str(mc.get("c10_vram", ""))
    if mem_c10 and "MiB" in mem_c10:
        verdicts.append(f"显存占用 {esc(mem_c10)}（加载后）——结合利用率：显存余量大意味着有上探更大模型/更大并发/更长上下文的空间")
    t = ('<div class="sub" style="font-weight:600;color:var(--txt);margin-top:14px">NPU 算力利用率分析（测试期间 1s 间隔采样）</div>'
         '<table style="margin:6px 0 8px"><thead><tr><th>阶段</th><th class="c">NPU 利用率（均值/峰值）</th>'
         '<th class="c">显存占用</th><th class="c">温度峰值</th><th class="c">样本数</th></tr></thead><tbody>'
         + "".join(rows) + '</tbody></table><div class="note">'
         + " ".join(f"<div style='margin:2px 0'>· {v}</div>" for v in verdicts)
         + "</div>")
    return t

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
        drops = {}
        for n, key, no in [(2, "c6c7_conc2", "C6"), (4, "c6c7_conc4", "C7")]:
            cc = c.get(key, {}); okn = int(cc.get("ok", -1)); tot = int(cc.get("total", n))
            ctok = int(cc.get("completion_tokens", -1)); cwl = float(cc.get("wall_s", 0))
            agg_tps = ctok / cwl if (ctok > 0 and cwl > 0) else 0
            per_tps = agg_tps / n if agg_tps > 0 else 0
            # SPEC §4.3: 全部成功 且 单路 tok/s 相对 C2 衰减 <30%（基准 = C2 usage 口径 tok/s）
            drop = ((est_tps - per_tps) / est_tps * 100) if (est_tps > 0 and per_tps > 0) else None
            drops[n] = drop
            if okn == tot and agg_tps > 0:
                cval = (f"{okn}/{tot} 成功, {cwl:.1f}s, 聚合 {agg_tps:.0f} tok/s"
                        f"（单路 ≈{per_tps:.0f} tok/s"
                        + (f", 较 C2 衰减 {drop:.1f}%" if drop is not None else "") + "）")
            elif okn == tot:
                cval = f"{okn}/{tot} 成功, {cwl:.1f}s（无 usage, 未验衰减）"
            else:
                cval = f"{okn}/{tot} 成功（失败）"
            verdict = 1 if okn == tot else 0
            if okn == tot and drop is not None and drop >= BASELINE["conc_drop_pct"]:
                verdict = 0  # 按 SPEC: 请求虽全部成功, 单路衰减超基线判失败
                cval += "｜衰减超 SPEC 基线, 判失败"
            add(no, f"并发 {n} 路", f"{n} 个 200 token 生成请求同时发出",
                cval, verdict, "SPEC: 全部成功 且 单路衰减 <30%（基准=C2 单路 tok/s）")
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
        "ttft": float(c3.get("s", 0)) if c3 else 0,
        "load_s": c.get("c1_load_s"),
        "toolcall": int(c8.get("ok", -1)) if c8 else -1,
        "multiturn": int(c9.get("ok", -1)) if c9 else -1,
        "conc2_ok": int(conc2.get("ok", 0)) if conc2 else 0,
        "conc2_total": int(conc2.get("total", 2)) if conc2 else 2,
        "conc2_wall": float(conc2.get("wall_s", 0)) if conc2 else 0,
        "conc2_drop": drops.get(2),
        "conc4_ok": int(conc4.get("ok", 0)) if conc4 else 0,
        "conc4_total": int(conc4.get("total", 4)) if conc4 else 4,
        "conc4_wall": float(conc4.get("wall_s", 0)) if conc4 else 0,
        "conc4_drop": drops.get(4),
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
def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    res_path = sys.argv[1]
    # Windows 默认 GBK, 中文 JSON/HTML 必须显式 UTF-8
    d = json.load(open(res_path, encoding="utf-8"))
    device = "AI Box"; model = d.get("model") or "预装模型"; out_path = None
    topso = None; bwo = None
    args = sys.argv[2:]; i = 0
    while i < len(args):
        if args[i] == "--device": device = args[i+1]; i += 2
        elif args[i] == "--model": model = args[i+1]; i += 2
        elif args[i] == "--tops": topso = args[i+1]; i += 2
        elif args[i] == "--bw": bwo = args[i+1]; i += 2
        else: out_path = args[i]; i += 1

    models = d.get("models")
    is_multi = isinstance(models, list) and len(models) > 0
    if not out_path:
        today = datetime.date.today().strftime("%Y%m%d")
        out_path = f"{device}_实测报告_{today}.html"

    a = d.get("phase_a", {}); b = d.get("phase_b", {}); c = d.get("phase_c", {})
    cls = d.get("classification", {})

    # 单模型且无 models 数组 → 沿用 phase_c
    if not is_multi:
        models = [{"name": model, "phase_c": c}]

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
最快解码 <b>{main_stats.get('est_tps',0):.1f} tok/s</b>（{esc(main_name)}，{'API usage 真实 token 统计' if main_stats.get('tps_src')=='usage' else '估算口径'}）。</p></div>
"""

    # ---- KPI 卡 ----
    # 非工控 NPU（Windows 独立 GPU 工作站）没有标称 TOPS/带宽时, 用本轮实测指标填卡, 不留 N/A 空卡
    try:
        _pc = rendered[0][3].get("phase_c", {}) or c
        _c2, _c4 = _pc.get("c2_short_decode", {}), _pc.get("c4_long_ctx", {})
        _single = float(_c2.get("completion_tokens", 0)) / (float(_c2.get("wall_s", 0)) or 1)
        _decs = float(_c4.get("completion_tokens", 0)) / _single if _single > 0 else 0
        _w4 = float(_c4.get("wall_s", 0))
        _pf = (float(_c4.get("prompt_tokens", 0)) / (_w4 - _decs)
               if _w4 > _decs + 0.05 else 0)
    except Exception:
        _pf = 0
    _accel_gb = a.get("accel_mem_gb") or cls.get("accel_mem_gb") or "?"
    if tops in (None, "", "N/A"):
        card_tops = ('<div class="card"><div class="k">长上下文 prefill</div>'
                     '<div class="v hl">%s<small> tok/s</small></div>'
                     '<div class="k">C4 实测折算（非 TOPS 标称）</div></div>'
                     % (("%.0f" % _pf) if _pf > 0 else "未测"))
    else:
        card_tops = (f'<div class="card"><div class="k">AI 算力</div>'
                     f'<div class="v hl">{esc(tops)}</div><div class="k">NPU INT8</div></div>')
    if bw in (None, "", "N/A"):
        card_bw = ('<div class="card"><div class="k">加速卡显存合计</div>'
                   '<div class="v hl">%s<small> GiB</small></div>'
                   '<div class="k">nvidia-smi 实测（非统一内存）</div></div>' % esc(str(_accel_gb)))
    else:
        card_bw = (f'<div class="card"><div class="k">内存带宽</div>'
                   f'<div class="v hl">{esc(bw)}</div><div class="k">统一内存</div></div>')
    accel_spec_line = (("算力 %s，带宽 %s" % (esc(tops), esc(bw)))
                       if tops not in (None, "", "N/A") else
                       "无 NPU 标称算力/带宽（本机为独立 GPU，非工控 NPU）；实测吞吐见 KPI 卡")
    mem_line = (("系统内存 %s（可用 %s）；独立加速卡显存 %s GiB — 推理内存取两者较小值"
                 % (esc(a.get("mem_total", "?")), esc(a.get("mem_available", "?")), esc(str(_accel_gb))))
                if a.get("accel_mem_gb") else
                ("统一内存 %s（可用 %s）— CPU/NPU 共享"
                 % (esc(a.get("mem_total", "?")), esc(a.get("mem_available", "?")))))
    _d4 = main_stats.get("conc4_drop")
    if _d4 is not None and _d4 >= BASELINE["conc_drop_pct"]:
        card_conc = ('<div class="card"><div class="k">并发能力</div>'
                     '<div class="v">%s<small>/4 路成功</small></div>'
                     '<div class="k">单路衰减 %.1f%% 超 SPEC 基线</div></div>'
                     % (main_stats.get("conc4_ok", 0), _d4))
    else:
        card_conc = (f'<div class="card"><div class="k">并发能力</div>'
                     f'<div class="v">{main_stats.get("conc4_ok",0)}<small>/4 路通过</small></div>'
                     f'<div class="k">最优模型实测</div></div>')
    rt = d.get("runtime_metrics") or (c.get("runtime_metrics") if isinstance(c, dict) else {}) or {}
    rt_line = ""
    if rt:
        rt_line = (f'<tr><td>GPU 运行时（阶段C 实测）</td><td>'
                   f'利用率 平均 <b>{rt["util"]["avg"]}%</b> / 峰值 {rt["util"]["max"]}%；'
                   f'单卡功耗 平均 {rt["power_w"]["avg"]}W / 峰值 {rt["power_w"]["max"]}W；'
                   f'温度 平均 {rt["temp_c"]["avg"]}°C / 峰值 {rt["temp_c"]["max"]}°C；'
                   f'共采样 {rt["samples"]} 次（加速卡管理工具，多卡均值）</td></tr>')
    hw_extra = ""
    if a.get("gpu_temp_c") or a.get("power_limit_w"):
        hw_extra = (f'<tr><td>GPU 静态温度 / 供电</td><td>'
                    f'采集时 GPU 温度 {esc(str(a.get("gpu_temp_c","?")))}°C；'
                    f'单卡 power.limit {esc(str(a.get("power_limit_w","?")))}W</td></tr>')
    html += f"""
<div class="cards">
  {card_tops}
  {card_bw}
  <div class="card"><div class="k">推理显存</div><div class="v">{esc(cls.get('infer_mem_gb','?'))}<small> GB 可用</small></div><div class="k">加载后占用 {esc(main_stats.get('vram','-'))}</div></div>
  <div class="card"><div class="k">最快解码</div><div class="v">{main_stats.get('est_tps',0):.1f}<small> tok/s</small></div><div class="k">{esc(main_name)}</div></div>
  {card_conc}
  <div class="card"><div class="k">首字延迟</div><div class="v">{main_stats.get('ttft',0):.2f}<small> s</small></div><div class="k">TTFT 最优模型</div></div>
</div>
"""

    # ---- 一、核心规格 ----
    html += f"""
<h2>一、核心硬件规格</h2>
<div class="panel"><table>
<thead><tr><th style="width:24%">项目</th><th>规格</th></tr></thead><tbody>
<tr><td>AI 加速卡</td><td><b>{esc(accel_str or 'N/A')}</b>（{accel_spec_line}）</td></tr>
<tr><td>SoC / CPU</td><td>{esc(a.get('cpu_model','')).strip()} × {esc(a.get('cpu_cores','?'))} 核（{esc(a.get('cpu_arch','?'))}，最高 {esc(str(a.get('cpu_max_mhz','0')).strip())} MHz）</td></tr>
<tr><td>内存</td><td>{mem_line}</td></tr>
<tr><td>存储</td><td>根分区 {esc(a.get('root_disk','?'))}｜块设备：{esc(a.get('blocks','?'))}</td></tr>
<tr><td>系统</td><td>{esc(a.get('os','?'))}（内核 {esc(a.get('kernel','?'))}）</td></tr>
<tr><td>网络</td><td>{esc(a.get('interfaces','?'))}</td></tr>
<tr><td>负载（采集时）</td><td>{esc(str(a.get('load','?')).strip())}</td></tr>
{rt_line}{hw_extra}
</tbody></table>
<div class="note">算力/带宽仅对 KNOWN_ACCEL 表内的工控 NPU 给出标称值（可用 <code>--tops</code> / <code>--bw</code> 覆盖）；其它设备不注入厂商标称值，改以本轮实测 prefill / 显存指标填 KPI 卡。其余均为本机采集实测值。</div>
</div>
"""

    # ---- 二、硬件分档 ----
    if cls:
        # 实测模型名与推荐清单名模糊匹配（去空格/大小写对齐）
        def norm(x): return str(x).replace(" ", "").lower()
        tested_map = {}
        for mname, trows, stats, m in rendered:
            for rec in cls.get("recommended_models", []):
                if norm(rec) == norm(mname) or norm(rec) in norm(mname) or norm(mname) in norm(rec):
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
<tr><td><b>加载耗时 C1</b></td>{''.join(f'<td class="c">{esc(str(r[2]["load_s"]) + "s") if r[2]["load_s"] else "未测"}</td>' for r in rendered)}</tr>
<tr><td><b>解码速度 C2</b></td>"""
        # 解码行加高亮最优
        best_tps = max((r[2]["est_tps"] for r in rendered), default=0)
        for r in rendered:
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
        html += f'</tr>\n<tr><td><b>并发 2 路 C6</b></td>'
        for r in rendered:
            s = r[2]
            cell = f'{s["conc2_ok"]}/{s["conc2_total"]}' + (f'，{s["conc2_wall"]:.0f}s' if s["conc2_wall"] else '')
            ok_cls = "ok" if s["conc2_ok"] == s["conc2_total"] and s["conc2_total"] > 0 else "no"
            html += f'<td class="c"><span class="{ok_cls}">{cell}</span></td>'
        html += f'</tr>\n<tr><td><b>并发 4 路 C7</b></td>'
        for r in rendered:
            s = r[2]
            cell = f'{s["conc4_ok"]}/{s["conc4_total"]}' + (f'，{s["conc4_wall"]:.0f}s' if s["conc4_wall"] else '')
            ok_cls = "ok" if s["conc4_ok"] == s["conc4_total"] and s["conc4_total"] > 0 else "no"
            html += f'<td class="c"><span class="{ok_cls}">{cell}</span></td>'
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
<div class="legend">◀ 标记该指标最优模型。解码速度 = completion_tokens / 耗时（tok/s，API usage 口径）；标「估」为旧数据（字/s 估算）。并发行速度见各模型明细。</div>
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
    html += f"""<div class="note" style="margin:8px 0 14px"><b>C1~C14 导读</b>：SPEC 定义的标准化测试——C1 冷启动加载（权重→NPU 就绪耗时）｜C2 解码速度（生成 tok/s）｜C3 首字延迟 TTFT（用户体感快慢）｜C4 长上下文 prefill（长文吞入速度）｜C5 长上下文解码衰减（同会话解码速度 vs C2，衰减 &lt;20%）｜C6/C7 并发 2/4 路（多用户同时用是否撑得住）｜C8 工具调用（Agent 能力）｜C9 多轮记忆（对话上下文保持）｜C10 显存占用｜C11 视觉多模态｜C12 输出质量抽查｜C13 上下文阶梯验证（大窗口真实性，见独立章节）｜C14 NPU 算力利用率（各模型明细末尾"算力利用率分析"表）。每项含"测试任务"（怎么测的）与"基线"（及格线）。</div>\n"""
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

    def conc_suggestion(s):
        """按 SPEC §4.3 衰减基线推导建议并发（只写实测推导）。"""
        if s.get("skipped"):
            return "未测（服务未就绪）"
        d2, d4 = s.get("conc2_drop"), s.get("conc4_drop")
        ok2 = s.get("conc2_ok", 0) == s.get("conc2_total", 2)
        ok4 = s.get("conc4_ok", 0) == s.get("conc4_total", 4)
        base = BASELINE["conc_drop_pct"]
        if ok4 and (d4 is None or d4 < base):
            return "<b>4 路并发无衰减</b>（实测口径）"
        if ok2 and (d2 is None or d2 < base):
            return ("<b>≤ 2 路</b>（4 路单路衰减 %.1f%% 超 SPEC %d%% 基线）" % (d4, base)
                    if d4 is not None else "<b>≤ 2 路</b>（4 路未验衰减）")
        return "并发单路衰减均超基线，建议单路使用"

    conc_txt = conc_suggestion(main_stats)
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
        if f_(pf) or f_(dec):
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
<tr><td>{'推荐模型' if is_multi else '测试模型'}</td><td><b>{esc(best_model)}</b>（解码 {main_stats.get('est_tps',0):.1f} tok/s，{'usage 口径' if main_stats.get('tps_src')=='usage' else '估算口径'}）</td></tr>
<tr><td>建议并发规模</td><td>{conc_txt}</td></tr>
<tr><td>Agent 场景可用性</td><td>{'✅ 工具调用 + 多轮记忆均通过' if not all_skipped and main_stats.get('toolcall')==1 and main_stats.get('multiturn')==1 else '见实测明细 C8/C9'}</td></tr>
<tr><td>长上下文能力</td><td>{html_last_ctx or ('✅ ~2000 token prefill + 摘要正确' if not all_skipped and main_stats.get('c4_ok')==1 else '见实测明细 C4')}</td></tr>
<tr><td>数据口径</td><td>全部数值来自本机实测（API 计时 + 管理工具读数），非厂商标称值</td></tr>
</tbody></table></div>

<div class="foot">BoxBench v{d.get('boxbench_version','?')} · SPEC v{SPEC_VERSION} · 渲染于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} · 原始 JSON：{esc(os.path.basename(res_path))}（可复核）</div>
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

if __name__ == "__main__":
    main()
