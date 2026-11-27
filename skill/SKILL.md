---
name: box-bench
description: 工控算力盒子（AI Box）标准化实测。拿到任何新盒子时触发：自动采集硬件指纹、环境盘点、跑模型实测（解码速度/长上下文/并发/工具调用/多轮），按 SPEC 统一标准产出 HTML 报告。Linux 设备自动加测 OpenClaw Agent 框架集成（工具执行循环/多步链/输出预算）。支持预装模型和指定模型下发测试（国内模型聚焦，含模型合规性验证），支持多模型顺序测试与横向对比报告。触发词：测盒子、盒子测试、工控盒实测、AI Box benchmark、设备验收。
version: 1.10.21
---

# BoxBench — 工控算力盒子标准化实测 Skill

## 目标

任何 AI 编程工具/Agent 均可执行本 Skill（工具无关）。对一台工控算力盒子完成标准化实测，产出统一样式 HTML 报告。

## 资产清单（同目录）

| 文件 | 用途 |
|---|---|
| `SPEC.md` | 测试规范 v1.7 — 测试项/判定标准/流程的**唯一权威定义，先通读** |
| `RUNBOOK.md` | **一页复现 SOP（换人可 100% 复现）**：逐步命令+每步预期输出+异常对照表 A-1~A-10；新人/新工具照做即可 |
| `AUTOMATION.md` | 定时回归模板：WorkBuddy 定时任务 / cron 双形态，在管盒子周期自动跑分+趋势对比 |
| `PLATFORM_NOTES.md` | **引擎×芯片经验库（测前必查，测后必回写）** — 同平台坑/规则/可用模型直接复用；`boxbench_exp.py sync` 自动合并公共经验（标记块隔离） |
| `scripts/boxbench_exp.py` | **公共经验池客户端**（`sync` 测前合并、`push` 测后上传、`pull` 只读，零依赖） |
| `scripts/boxbench.sh` | 设备端采集脚本（阶段A/B 自动 + 阶段C 自动 + multi 多模型 + C13 上下文阶梯） |
| `scripts/boxbench_live.py` + `scripts/live/` | **本机实时测试工作台**：包装本地或 SSH 测试命令，动态节点/流动连线/步骤耗时/实时日志/运行快照；纯 Python3 标准库，前端资源离线随包分发；`--replay <journal>` 按真实时间轴回放历史测试 |
| `scripts/check_update.sh` | **版本自检**：本地 SKILL.md vs GitHub/Gitee 远端版本；`--verbose` 带说明、`--upgrade` 自动升级；离线输出 unknown 不阻塞（第 0.5 步） |
| `scripts/boxbench_windows.py` | **被测设备为 Windows** 的等价一键脚本（阶段A/B/classify + 阶段C C2~C12 + C5 流式分段 + GPU 运行时采样，PowerShell + Python 标准库零依赖，产出与 boxbench.sh 同结构 JSON） |
| `scripts/render_report.py` | 报告渲染器（纯 Python3 标准库，无第三方依赖；Windows 兼容：反斜杠路径/GBK 控制台/无 NPU 标称值回退实测卡） |
| `scripts/vendor/chart.umd.min.js` | Chart.js 4.4.1（201K）——渲染器自动内嵌进报告，**随 skill 整体分发/拷贝时必须带上 scripts/ 目录**；vendor 丢失时渲染器自动降级 CDN（需联网） |

## 执行流程

### 第 0 步：查经验库（每次必做，防重复踩坑）

1. 阶段B 环境盘点跑完后，得到设备的 引擎名+芯片 组合（如 `houmo-HLIELLama-xh2`）
2. **同步公共经验池**（联网时，可选）：`python3 scripts/boxbench_exp.py sync --platform <平台键>` —— 拉到全网已验证经验并**自动合并进 `PLATFORM_NOTES.md`**。合并块用 `<!-- BOXBENCH-COMMONS:BEGIN/END -->` 标记隔离，只替换该块，**绝不改动手写内容**；重复执行幂等。离线自动用本地缓存，失败不阻塞。
   - 一次同步所有已知平台：`sync --all`（先拉目录再逐个合并）
   - 自测（离线，不联网）：`selftest`
   - 只想看不想改文件：`pull --platform <平台键>`
   - **信任门槛**：`--min-trust` 默认 2（≥2 台独立设备交叉验证才显示）。单设备上传的数据默认**不展示**（防单机自证），加 `--min-trust 0` 可查看全部
   - 预览合并结果：`sync --platform <平台键> --dry-run`
3. **查 `PLATFORM_NOTES.md`**（本地）：命中 → 直接套用该平台的坑/规则/可用模型清单（如 NPU 只认专用格式、-dev 0 参数、model-cli 用法），跳过所有已踩过的坑
4. 未命中 → 全新平台，正常探索，测完**必须回写**（见第 6 步）
5. 选型时结合经验库的"可跑模型清单"过滤 HARDWARE_MODEL_MATRIX.md 推荐清单——**矩阵推荐 ≠ 该引擎可跑**（格式/后端限制以经验库为准）
6. **利用率优先选型**（教训：E300K 跑 35B 仅占 4G/30G，绰绰有余）：首选该档位最大可用模型；主力测完后**默认不向下测更小模型**——大模型跑得绰绰有余时，小模型只有更快没有更好。补测第二模型仅在：显存占用低有上探空间 / 有场景特化对比需求（代码、Agent 特化 vs 通用）/ 主力不达标需备选

### 第 0.5 步：版本自检（每次实测前，可选但推荐）
本地安装的 skill 可能落后于云端仓库。实测开始前在 **Agent 本机**跑一次：
```bash
bash scripts/check_update.sh --verbose
# 输出: up-to-date（最新）| outdated <远端版本>（有新版）| unknown（离线，不阻塞）
# 自动升级: bash scripts/check_update.sh --upgrade
```
- `outdated` → 先 `--upgrade`（或把仓库最新 `scripts/` 重新拷入本地 skill 目录）再测试，避免用旧脚本踩已修过的坑
- `unknown`（设备/本机离线）→ 直接继续测试，**永不因版本检查阻塞**
- 设备端 `boxbench.sh` 也会后台异步自检（24h 缓存、失败静默），设备端脚本过旧时在运行日志里提示"云端已有新版本"——看到该提示应在本次测完后更新设备端脚本
- 被更新过的 skill 建议顺手核对 `CHANGELOG.md` 里新版本的 Fixed 项，确认是否影响本轮判读

### 第 1 步：连接信息
向用户确认（或从上下文提取）：设备 IP、SSH 账号、密码/密钥。未给出则询问。

**本机（执行 Agent 的机器）为 Windows 时的注意事项**：
- Windows 10 1809+ 自带 `ssh`/`scp`（OpenSSH 客户端），PowerShell 直接可用；无 `expect`/`sshpass`，密码交互改用 ssh 密钥登录，或 `plink -pw <密码>`（PuTTY 套件），或让用户手动输一次密码
- **PowerShell 重定向编码陷阱**：Windows PowerShell 5.1 的 `>` / `Out-File` 默认 UTF-16LE 编码——把脚本内容重定向成文件再传设备会因 BOM/编码导致 bash 报错。正确做法：`Set-Content -Encoding UTF8`（无 BOM 用 `-Encoding utf8NoBOM` 的 pwsh 7）、或用 `curl` 直接从仓库拉 `boxbench.sh` 到设备、或 ssh 后用 heredoc 粘贴。传完在设备上验证：`head -1 boxbench.sh` 应为 `#!/bin/bash` 且无乱码
- **换行符**：仓库带 `.gitattributes` 强制 LF，正常 git clone 不会出问题；但若经其他渠道（复制粘贴/压缩包）流转，传设备前检查 CRLF：`file boxbench.sh` 或 `grep -c $'\r' boxbench.sh` 应为 0
- **Python 命令名**：Windows 上通常没有 `python3`，用 `python` 或 `py`（装了 Python Launcher 时）。渲染命令对应改为 `python scripts\render_report.py ...`
- 渲染器已做编码适配（UTF-8 显式读写 + stdout 自动重配置），Windows Python 3 直接可跑，无需 chcp
- 路径分隔符：渲染器内部用 `os.path`，Windows 反斜杠路径直接可用；scp 目标路径用正斜杠

**被测设备是 Windows 系统时**：`boxbench.sh` 无法直接运行（bash 脚本依赖 /proc、lscpu、free、ss 等 Linux 工具）。处理路径：
1. 设备有 WSL：进 WSL 执行 boxbench.sh，部分硬件查询（NPU/加速卡）可能需回退 Windows 侧 PowerShell 命令补采
2. 无 WSL（v1.3.8 起推荐）：直接运行一键脚本 `python scripts/boxbench_windows.py [--api URL] [--model NAME] [--thinking none|keep] [--all]`——自动完成阶段A/B/classify + 阶段C（C2~C12），产出与 boxbench.sh 同结构 JSON，交给 render_report.py 照常渲染。脚本已内置 Windows 实测踩坑修正（显存必须用 nvidia-smi 读、LM Studio 无 /health 用 /v1/models 探测、思考模型用 reasoning_effort=none 关闭思考），平台细节见 PLATFORM_NOTES.md。C5 采用流式同请求分段实测（prefill/decode 分离），并全程 nvidia-smi 采样 GPU 利用率/功耗/温度（runtime_metrics），另采集 A7 GPU 温度、A9 TDP、B3 CUDA/驱动栈
3. 报告"部署环境"行如实标注 Windows 版本；引擎经验库照常回写（标注 OS）

### 第 1.5 步：硬件分档 + 模型清单匹配（自动）
boxbench.sh 默认输出 `tier`（D1~D5 设备档位）与 `recommended_models`（该档位推荐清单，依据 `HARDWARE_MODEL_MATRIX.md`，覆盖 8000~50000 元价位段）。对用户指定的每个待测模型：
- 模型档位 ≤ 设备档位 → ✅ 测试
- 模型档位 = 设备档位+1 → ⚠️ 边界尝试（标注后正常测）
- 模型档位 ≥ 设备档位+2 → `⏭ 硬件不支持 — {原因}`，自动跳过
- 模型档位 ≤ 设备档位-2 → `◼ 不必要验证 — 模型档位远低于设备档位`，自动跳过
跳过的模型在报告中列出但不计通过率。

### 第 2 步：分发脚本
**交互测试必须用 live 工作台包装，且必须把看板打开给用户**（硬性要求，见硬性规则 #9）。在 **Agent 所在本机** 用 `boxbench_live.py` 包装原测试命令。不要在无桌面的盒子端启动浏览器；不要为了演示重复启动一轮真实测试。

```bash
# Linux 远程测试（SSH 凭据按第1步处理；优先密钥，SSH 不加 -t）
# Agent 自带内置浏览器/文件预览能力时，加 --no-open 并自行打开 BOXBENCH_LIVE_URL
python3 scripts/boxbench_live.py --no-open -- ssh user@device "bash ~/boxbench.sh collect"
# 没有内置浏览器时，省略 --no-open 让系统浏览器自动弹出
python3 scripts/boxbench_live.py -- ssh user@device "bash ~/boxbench.sh collect"
# 多模型：将原 SSH 的 multi 命令原样放在 -- 后即可
# Windows 本机测试（python3 换成 python 或 py）
python scripts/boxbench_live.py --no-open -- python scripts/boxbench_windows.py --all
```

- **启动后第一优先级动作**：读取 `BOXBENCH_LIVE_URL=http://127.0.0.1:.../<随机路径>/`，**立即**（a）有内置浏览器/预览面板的 Agent → 在内置浏览器打开该 URL 并告知用户"看板已打开"；（b）无内置浏览器 → 省略 `--no-open` 让系统浏览器弹出；（c）两者都做不到 → 必须把 URL 原文发给用户并说明手动打开。URL 每次运行不同，不要硬编码。**必须在测试命令开始前打开看板**——collect 单模型全程仅约 1 分钟，测试开始后才开看板，用户只会看到全部完成后的静态画面（2026-11-18 实际反馈："没有任何变化"）。**内置浏览器若打开 404/空白**：这是 CDP 中继型内置浏览器的已知缺陷（127.0.0.1 在中继侧解析，见异常表 A-11），先 curl 自证服务 200 后直接降级到（b）或（c），不要重试内置浏览器。
- **回放模式**（v1.11.0）：测试跑完后用户想重看过程，或浏览器打开晚了只见最终态时，用 `--replay` 按真实时间轴重演：
  ```bash
  python3 scripts/boxbench_live.py --replay boxbench_live_20261118_103259_xxx.jsonl
  # 2 倍速: 加 --replay-speed 2.0；循环重放，Ctrl-C 退出
  ```
  journal 文件即每次运行落盘的 `boxbench_live_*.jsonl`（事件流已含全部阶段/耗时/日志）。**回放不得替代真实测试**，仅用于补看。
- **禁止以下列任何理由跳过看板**："collect 很快" / "服务已就绪只是复采" / "复测数据不会变" / "后台跑完直接给你报告"。这些理由全部不成立——用户要的是过程可见，不是只要结果。唯一例外：CI/无人值守场景，或用户明确说"不用界面"。
- 网页仅监听本机回环地址，资源无 CDN。状态事件经原 SSH 标准错误输出回传，不用开放设备端口。仅支持包装 `auto` / `fingerprint` / `collect` / `multi` 和 Windows 采集；独立 C13 阶梯暂用原日志查看。- 已执行/异常/跳过分别展示；**已执行不等于指标达标**，通过率仍以原始 JSON 与报告为准。多模型会重置模型阶段，前一模型事件保存在运行快照的 `models` 中。
- 测试结束后网页默认保留15分钟（`--linger 秒数` 可改）；原始结果和日志仍按原流程保存。本机另存 `boxbench_live_*.jsonl` 事件记录。界面快照／日志含内部环境信息，仅内部使用，不能当作脱敏报告直接外发。
- 只想展示界面时使用 `python3 scripts/boxbench_live.py --demo`，页面会标记“演示模式 · 非实测数据”，不连接设备、不产出实测数据。**不得用演示模式替代真实测试。**

以下为设备端原始命令（可放到包装器的 `--` 后，远程执行时放在 SSH 引号内）：
将 `scripts/boxbench.sh` 传到设备（scp 或粘贴执行均可），运行：
```bash
bash boxbench.sh            # 自动模式：指纹+盘点+（服务就绪则）模型实测
bash boxbench.sh collect     # 单模型补采（服务已启动）
bash boxbench.sh multi "模型名|模型文件绝对路径" ["模型名2|路径2" ...]
                            # 多模型顺序测试：自动停旧服务→起新服务(计时C1)→C2~C12→停服务→下一个
                            # ★ 单模型正式测试也用 multi（传一个模型即可）——它是唯一能
                            #   计时 C1 加载耗时、证据链完整的单模型模式
bash boxbench.sh ctxtest "模型名|模型文件绝对路径" ["32k,128k,max"]
                            # C13 上下文阶梯验证（可选）：验证模型标称大窗口是否真实可用。
                            # 每档以该窗口重启服务→塞 ~55% 窗口文本(头部埋随机暗号)→记录
                            # prefill 速度+暗号召回+显存。C1~C12 在 8K ctx 下测，
                            # 标称 128K/256K 窗口的能力只能由 C13 回答，验收大窗口模型必跑。
```
- `multi` 模式下 boxbench.sh 自动管理服务生命周期：每模型启动前做**资源预检**（磁盘可用 < 文件+2GB → `⏭ 磁盘空间不足，暂未测试`；权重×1.15 > 推理内存 → `⏭ 内存不足，暂未测试`，均跳过并在报告列出原因），通过后自动起服务计时（C1）→ 跑阶段C → 停服务换下一个。
- 速度口径（v1.2 起）：C2/C4/并发 均记录 API `usage.prompt_tokens/completion_tokens`，解码速度 = completion_tokens/耗时（**tok/s，usage 口径**）；旧数据自动降级"估算（字/s）"并标注。
- **NPU 算力利用率（v1.5 起，自动）**：阶段C 全程 1s 间隔采样加速卡（mthreads-gmi -q / nvidia-smi），按 空闲基线/C2解码/C4 prefill/并发/全场 分段汇总利用率均值/峰值/显存%/温度峰值。判读口径：解码段利用率低 = 访存受限（LLM 共性，正常）；**prefill 段利用率 = 计算密集段真实算力发挥**。报告自动出"算力利用率分析"章节。无采样能力设备（无管理工具）自动跳过，不影响其他测试。
- **Agent 框架集成（SPEC v1.5 起，Linux 默认自动）**：阶段C 结束后自动跑阶段 E（OpenClaw 集成测试，E0 自动安装 / E1 网关探活 / E2 端到端单轮 / E3 单工具真实执行 / E4 多步工具链 / E5 输出预算截断 / E6 纯文本回退）。**设备未装 OpenClaw 时自动安装**（官方 install.sh `--no-onboard`，约 1~3 分钟；失败才跳过并留日志，`BOX_AGENT_AUTOINSTALL=0` 关闭自动安装）。非 Linux 自动跳过并标注，不阻塞其他测试。`BOX_OPENCLAW`（CLI 路径）、`BOX_OPENCLAW_PORT`（网关端口，默认 18789）、`BOX_AGENT_SKIP=1`（强制跳过）可控制。**C8 通过 ≠ Agent 能用**——阶段 E 才验证真实工具执行循环。结果独立分节，不计入 C 通过率。
- 环境变量可覆盖默认路径：`BOX_API`（默认 http://127.0.0.1:17701）、`BOX_ENGINE`（llama-server 路径）、`BOX_ENGINE_LIB`、`BOX_PORT`。
- 设备上模型服务**未启动**时：阶段C 自动跳过。此时按用户需求决定是否启动服务，启动后运行 `bash boxbench.sh collect` 补采。

### 第 3 步：指定模型测试（如有）
1. 用户指定的模型（国内模型聚焦：Qwen3.6-35B / Qwen3.8-Flash-Next 去对齐微调版 / Qwen3-Coder / GLM / DeepSeek 等）
2. 记录权重来源、大小、量化格式
3. **去对齐微调版模型**：必须追加 SPEC §4.4 的 U1-U3（合规红线/越狱抵抗/能力对比）测试，结果如实记录
4. 每模型独立跑一遍阶段C，报告按模型分节

### 第 4 步：取回结果并渲染
```bash
# 设备端产出 boxbench_results_*.json（运行日志 boxbench_run_*.log 一并取回留痕），scp 回本机后：
python3 scripts/render_report.py <result.json> [输出.html] --device <型号> --model <模型名>
# 多模型（JSON 含 "models" 数组时自动切换多模型报告）：
python3 scripts/render_report.py <result.json> [输出.html] --device <型号>
# Windows 本机: python3 换成 python 或 py，路径分隔符正反斜杠均可
```
- **脱敏默认开启**：渲染时自动把 IP/IPv6/MAC/主机名替换为占位符（`<内网IP>`/`<主机·设备型号>`），报告可直接对外提交。内部排查需看真实 IP 时加 `--no-redact`（产物尾注会标"⚠ 未脱敏版"）
- 过程留痕：设备端 `boxbench_run_*.log`（每步带时间戳）随 JSON 一起归档，作为真实执行的过程记录
产出文件名：`{设备型号}_实测报告_{YYYYMMDD}.html`

多模型报告结构：KPI 卡（最优模型口径）→ 部署环境行（引擎版本+加速栈+系统）→ 硬件规格 → 分档（只列已测模型+通过率）→ **多模型横向对比表**（首行"运行配置"=引擎/ctx/量化一致性，然后加载/解码/TTFT/长上下文/并发/工具调用/多轮/显存/通过率，最优值 ◀ 标记）→ 对比图表 → 每模型块（**运行配置表**：模型权重文件+大小+量化+引擎版本+完整启动命令行+ctx+端口，然后 C1~C12 明细）→ 环境盘点 → 结论。
> **运行配置是横向对比公平性的前提**（ctx 8K vs 256K 的 TTFT/显存不可比）。boxbench v1.3 起每模型自动采集 engine 段；旧数据渲染时自动标注"参数未记录"。

### 第 5 步：报告补充（Agent 手工部分）
渲染器产出客观数据部分。Agent 需补充渲染器覆盖不到的项：
- C1 冷启动加载耗时（Agent 自己在启动服务时计时）
- C11 多模态（有 mmproj 时手动测）
- C12 输出质量人工抽查评语
- **C13 上下文阶梯**（模型标称窗口 > 32K 时建议跑 `ctxtest`，JSON 含 `ctxtest` 字段时渲染器自动出"上下文阶梯验证"章节并更新结论行长上下文能力）
- **阶段 E 判读**（设备部署了 OpenClaw 时）：E3/E4 失败时结合 PLATFORM_NOTES 判断是否为已知 tool parser 问题（如 MiniCPM5 需专用 parser），并在报告中给出修复建议；新坑测后回写经验库
- 阶段D 容量结论（**必须基于实测数据推导，禁止估算**）
将补充项以编辑方式并入 HTML（保持四段式结构与样式不变）。

### 第 5.5 步：交付前人工复核（合规硬要求，不可跳过）

报告渲染完成后、**对外发送/提交前**，必须由人工完成复核（SKILL 不得代替人勾选）：
1. **数字一致性**：抽查报告里 C2 解码速度、C7 并发、通过率三处与原始 JSON 一致
2. **敏感信息**：`grep -E "192\.168\.|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[01])\." 报告.html` 应为 0 命中（默认已脱敏，此处为兜底确认）
3. **C12 输出质量**：人工阅读生成样例，确认无乱码/复读/不当内容
4. 报告尾部"人工复核记录"表：勾选对应项、填写复核人与日期
5. 之后报告才允许对外发送；**不得由助手自动外发任何内容**（含邮件/消息推送）

> 复现全流程（含每步预期输出与 10 类异常的处理）见 `RUNBOOK.md`；在管盒子的周期自动回归见 `AUTOMATION.md`。

### 第 6 步：回写经验库（每次实测后必做，skill 自我进化）

报告交付后，将本次实测新增的事实回写 `PLATFORM_NOTES.md`：
1. **同平台复测**：更新该平台条目（新坑加入"🚫 已踩坑"；旧坑已修则标注；模型清单快照更新；实测基线以最新口径覆盖）
2. **新平台**：按文件末尾"回写格式"追加新条目
3. 只记实测验证过的事实 + 验证日期；推测不写入
4. 磁盘/内存不足被跳过的模型：在对应平台条目记录"需 X GB，仅 Y GB 可用"，下次选型直接避开或先清理

> 这是 skill 的记忆机制：不回写 = 下次同平台从零踩坑。**每测一台设备，经验库必须变厚。**

5. **上传公共经验池（v1.10.15 起渲染器自动执行，不再依赖人工记忆）**：`render_report.py` 渲染成功后自动完成 `boxbench_exp.py push` 的全部工作（构建 atom → 入 outbox → 上传），并按 `evidence_hash` 写本地台账 `~/.boxbench/pushed_ledger.json` —— 同一份结果 JSON 幂等不重传。控制台会打印 `[exp] 自动 push 完成` / `[exp] 已推送过` 字样。
   - **何时还需手动 push**：仅在渲染在本机以外环境完成、或结果 JSON 事后被修正（新 evidence_hash）时，手动执行
   ```bash
   python3 scripts/boxbench_exp.py push --result boxbench_results_xxx.json
   ```
   - 自动 push 失败不阻塞渲染：atom 留在 outbox，`boxbench_exp.py flush` 可重传；下次用同一 JSON 渲染也会自动补推
   - 退出贡献：`export BOXBENCH_CONTRIBUTE=0`（自动 push 同样尊重该开关）或渲染时加 `--no-push`
   - 平台键自动推断（取自结果 JSON 的 `engine.engine_name` 首词）；推断不出时明确报错并要求 `--platform`，不会编造键名导致池子分叉
   - 自动完成：提取白名单证据 → 脱敏 → 生成结构化经验单元 → 尽力上传（失败进本地 outbox 稍后 `flush` 重传）
   - 上传的是**脱敏后的结构化事实 + 证据**，不含 IP/账号/家目录等隐私（客户端与服务端双重脱敏）
   - 退出贡献：`export BOXBENCH_CONTRIBUTE=0`（企业/内网环境可只拉不传）
   - 上传后由服务端门控自动校验；冲突/存疑条目会进入待仲裁队列，不会立即对外可见
   - **可信度阶梯**：T0 隔离 → T1 单源候选 → T2 双机验证 → T3 人工确认。你自己一台机器测的数据停在 T1（单源不是错，只是还不够“已验证”），只有另一台**硬件不同**的机器报了同一结论才升到 T2
   - 独立性按**设备指纹**（OS/内核/架构/核数/内存/加速器/档位）判定，不按账号：换 token 重传不会提升可信度。字段刻意排除了时间戳、引擎 build、模型文件大小（这些重跑就会变，否则同一台机器多次实测会被当成多台）

## 硬性规则

1. **速度数据来源优先级**：引擎计时日志 > API 统计 > 前端估算（禁止前端估算入报告）
2. **禁止把未实测的数字写进报告**（历史教训：并发数凭印象写，被打回）
3. 报告必须记录环境指纹（引擎版本/启动参数/模型版本/SPEC 版本）
4. 判定标准以 SPEC.md 为准，SPEC 与本文件冲突时以 SPEC 为准
5. 去对齐微调版 U1/U2 只记录事实数据用于选型，不做绕过尝试
6. 每台设备产出报告后，同时留存原始 JSON（供跨设备对比）
7. **Chart.js 内嵌机制**：`scripts/vendor/chart.umd.min.js` 必须随 skill 分发（拷贝/打包/转移到其他 AI 工具时带上 scripts/ 整个目录）；渲染报告后检查产物无 `cdn.jsdelivr.net` 引用（内嵌成功）；若产物出现 CDN 引用说明 vendor 丢失，从 jsdelivr 下载 chart.umd.min.js（4.4.1）放回 scripts/vendor/ 后重渲染。产出报告必须离线可打开（内网/无外网环境是常态）
8. **对外合规三原则**：① 报告默认脱敏后才可对外（`--no-redact` 版仅限内部排查）；② 对外发送必须经人工复核（第 5.5 步），助手不得自动外发；③ 过程留痕（`boxbench_run_*.log`）与原始 JSON 一并归档，确保结论可回溯、禁止摆拍
9. **live 看板必须开给用户（不可豁免）**：凡真实测试（`auto`/`collect`/`multi`/Windows 采集），必须在 Agent 所在本机用 `boxbench_live.py` 包装，且按第 2 步三选一把看板交给用户（内置浏览器打开 / 系统浏览器弹出 / URL 原文发给用户）。"测试很快"、"复采"、"CI 之外的任何自判"都不构成跳过理由；仅 CI/无人值守或用户明说不用界面时可跳过。跳过即违规，用户无需追问就应已看到看板。**且必须在启动测试命令之前完成看板打开动作**——顺序反了，用户只能看到最终态（教训：2026-11-18 collect 全程 58 秒，用户开看板时已结束，以为看板没工作）。**内置浏览器打开 404/空白时的处理（2026-11-27 WorkClaw 教训）**：内置浏览器可能经 CDP 中继连接，`127.0.0.1` 在中继侧解析，中继上没有看板服务 → 返回中继自己的 404，与看板无关。处理：先 `curl` 同 URL 自证 200（服务正常），**不要重试内置浏览器**（重试必败），立即改用系统浏览器弹出或把 URL 原文发用户手动打开；保留期已过用 `--replay` 重演。完整对照实验见 RUNBOOK 异常表 A-11。
10. **看板打开晚 / 用户质疑"没有进展" → 用 `--replay` 重演，不要重跑测试**：每次运行的 `boxbench_live_*.jsonl` 完整记录了事件时间轴，`--replay` 可原样重演过程。重跑真实测试只为刷新数据，不为"给用户看过程"。
11. **报告实测模型名必须真实**：渲染器已能自动反解模型名（`infer_model_name`，v1.11.1 起来源优先级：engine_cmd 的 `-m` 参数 > 模型记录 `path` > engine 段 `model_path`/`model_file`——最后者覆盖 Strata 等打包式引擎），但 Agent 显式传 `--model` 时以传入值为准。禁止把"预装模型"这类占位名写进正式报告；若报告中模型名显示为占位符，说明 JSON 缺上述全部字段，先补采集再渲染。
12. **正式测试用 `multi`，不用 `collect`**：只要知道模型文件路径，单模型正式测试一律 `multi "模型名|路径"`（自动起服务计时 C1、证据链完整）。`collect` 仅限"服务由外部启动且无法重启"的补采场景，且报告必须标注"补采（C1 加载耗时未覆盖）"。`auto` 模式在服务已就绪时自动降级为 collect 同样的路径——正式测试时若有模型路径，直接用 `multi` 指定。
13. **解码速度必须峰值/均值并列呈现，禁止把均值标成"最快"**：usage 口径（completion_tokens/耗时）是持续负载**均值**；峰值 = 流式 1s 滑动窗口最大瞬时速度（v1.11.1 起采集端自动记录 `speed_peak_tps`/`speed_mean_tps`）。推测解码（DFlash2/MTP）引擎峰值可达均值 1.3~2 倍（2026-11-26 实测：同机冒烟 46.2 vs boxbench 均值 36.3 被用户质疑"为什么缩水"），KPI 卡/摘要/对比表一律标"解码均值"或"峰值/均值"双口径，旧数据无峰值字段时显示"—/均值"并注明为均值口径。

## 已验证的平台事实

见 `PLATFORM_NOTES.md`（按引擎×芯片索引）。当前已验证平台：后摩 M1000/E300K + HLIELLama（`houmo-HLIELLama-xh2`）。

## 跨设备对比

多台设备报告齐备后，可基于各 JSON 汇总对比表（速度/并发/显存/通过率），同样用 render_report.py 的样式规范输出。
