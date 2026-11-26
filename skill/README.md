# BoxBench — 工控算力盒子标准化测试套件

> 版本 1.10.18 ｜ SPEC 1.4 ｜ 2026-11-26
> **工具无关设计**：本套件可在任何 AI 编程工具中使用（WorkBuddy / Claude Code / Cursor / 其它 Agent），目录整体拷贝即可转移。

## 这是什么

解决"盒子越买越多、每次测试标准和项目不统一"的问题。三层架构：

```
┌──────────────────────────────────────────────────┐
│ SPEC.md            规范层：测什么、怎么判、什么算过    │
├──────────────────────────────────────────────────┤
│ scripts/boxbench.sh         执行层：Linux/盒子端采集 │
│ scripts/boxbench_windows.py         执行层：Windows端 │
├──────────────────────────────────────────────────┤
│ SKILL.md              编排层：Agent 怎么串起来跑      │
│ scripts/render_report.py         统一 HTML 报告渲染  │
├──────────────────────────────────────────────────┤
│ PLATFORM_NOTES.md    经验层：引擎×芯片经验库           │
│ scripts/boxbench_exp.py        公共经验池：全网经验共享 │
└──────────────────────────────────────────────────┘
```

## 公共经验池（Commons）

每台设备测完的经验不只留在本机，而是汇入公共池，下次同平台直接复用。

```bash
python3 scripts/boxbench_exp.py sync --platform <平台键>   # 测前：拉全网经验并合并进 PLATFORM_NOTES.md
python3 scripts/boxbench_exp.py push --result results.json # 测后：上传本次实测（默认开启）
export BOXBENCH_CONTRIBUTE=0                               # 退出贡献（只拉不传）
```

三道保障：
1. **数值不可伪造** — 服务端用同一口径从证据重算，手改数字直接隔离。
2. **单机不能自证** — 晋升「已验证」需要**不同发布者**独立佐证，同一设备重跑不算。
3. **隐私不上传** — 客户端+服务端双重脱敏，不含 IP/账号/家目录/权重路径。

冲突时**本地实测永远优先**，公共池仅作参考。

## 价值量化（为什么值得用）

以 ZYSJ-E300K 首次实测为基准（人工方式 vs BoxBench）：

| 环节 | 人工方式 | BoxBench |
|---|---|---|
| 硬件指纹+环境盘点 | ~1h（手工敲命令、截图、抄录） | 自动，~3min |
| 12 项性能测试 | ~2h（逐项手工构造请求、记录、算口径） | 自动，随 multi 模式顺带完成 |
| 报告撰写 | ~2h（排版+图表+口径核对） | 渲染 <5s，人工仅补评语 |
| 换个模型重测 | 全部重来 | `multi` 一条命令，模型间自动切换 |
| 换个人执行 | 结果口径不一致，需师傅带 | RUNBOOK 照做，产出一致 |
| **单台合计** | **~5h/台** | **~30min（主要为多模型实测等待）** |

- 一台设备节省 **4.5h**；经验库沉淀后，同平台第二台节省更多（坑不用重踩）
- 数据口径统一（API usage tok/s），杜绝"人工记录时口径漂移"带来的返工
- 报告默认脱敏 + 复核记录栏，可直接提交管理层，无需二次加工

## 快速开始

### 实时测试工作台

交互测试默认用本机工作台包装原采集命令。动态流程图显示实际执行状态，点击节点查看详情；右侧显示耗时，底部显示实时日志。SSH 测试无需给设备开放网页端口。

```bash
python3 scripts/boxbench_live.py --demo   # 仅界面演示，无实测数据
python3 scripts/boxbench_live.py -- ssh user@device "bash ~/boxbench.sh collect"
# Windows 本机：
python scripts/boxbench_live.py -- python scripts/boxbench_windows.py --all
```

在 Codex 等有内置浏览器的 Agent 中加 `--no-open`，随后由 Agent 打开输出的 `BOXBENCH_LIVE_URL`。前端资源已包含在 `scripts/live/`，离线可用。结束后看板保留15分钟；CI 使用 `--linger 0`。快照只表示执行过程，不能替代实测结果／脱敏报告。多模型历史保存在快照 `models` 数组；独立 C13 仍用原日志查看。

### 方式一：通过 AI 工具（推荐）
把整个 `skill/` 目录给任何 Agent（作为 skill 或直接放入上下文），说"测这台盒子：IP x.x.x.x，账号 xx，密码 xx"。Agent 按 SKILL.md 流程执行。

**WorkBuddy**：目录放在 `~/.workbuddy/skills/box-bench/`（已安装）即自动可用。
**Claude Code / 其它**：把目录拷入对应 skills/commands 位置，或将 SKILL.md 内容作为 system prompt 注入。

### 方式二：手动 / CI（无需 AI 工具）

被测设备是 Linux / 工控盒：

```bash
# 1. 上传到设备
scp scripts/boxbench.sh user@device:~/
# 2. 设备上执行（模型服务已启动时自动跑全量）
ssh user@device "bash ~/boxbench.sh"
# 3. 取回 JSON，本机渲染报告（仅需 Python3，无第三方依赖）
scp user@device:~/boxbench_results_*.json .
python3 scripts/render_report.py boxbench_results_xxx.json --device "ZYSJ-E300K" --model "Qwen3.6-35B"
```

被测设备是 Windows（LM Studio / llama.cpp / NVIDIA GPU）：

```powershell
python scripts\boxbench_windows.py --api http://127.0.0.1:1234
python scripts\render_report.py boxbench_results_xxx.json --device "工作站型号"
```

## 测试范围（详见 SPEC.md）

- **阶段A 硬件指纹**：芯片/内存/存储/NPU/系统/网络（9 项）
- **阶段B 环境盘点**：模型权重/引擎/加速栈/容器/服务（5 项）
- **阶段C 模型实测**：C1~C14（加载/解码/TTFT/长上下文/解码衰减/并发2/4/工具调用/多轮/显存/多模态/质量/上下文阶梯/NPU 算力利用率）+ 去对齐微调版 U1-U3
- **阶段D 容量结论**：并发建议/场景判定/遗留问题（禁止估算，只写实测）

**前置硬件适配检查**：指定模型明显跑不动（显存/架构/磁盘）→ 报告标注"⏭ 硬件不支持"，自动跳过。

**指定模型聚焦清单**（国内模型）：Qwen3.6-35B-A3B（P0 基准，已校准 24.0 tok/s）、Qwen3.8-Flash-Next 去对齐微调版（P0，含合规验证）、Qwen3-Coder（P1）、GLM/混元/DeepSeek（P1）、Embedding/Rerank（P2）。

## 目录结构

```
skill/
├── SPEC.md                  # 规范（唯一权威定义，当前 v1.4）
├── SKILL.md                 # Agent 编排指令
├── RUNBOOK.md               # 一页复现 SOP：逐步命令+预期输出+异常对照表（换人可 100% 复现）
├── AUTOMATION.md            # 定时任务回归模板（WorkBuddy 定时任务 / cron 双形态）
├── PLATFORM_NOTES.md        # 引擎×芯片经验库（自进化）
├── HARDWARE_MODEL_MATRIX.md # 硬件分档 D1~D5 推荐模型
└── scripts/
    ├── boxbench.sh          # Linux/盒子端采集脚本（bash, 无依赖, 日志落盘留痕）
    ├── boxbench_windows.py  # Windows 端一键采集（LM Studio/NVIDIA 已验证, 日志落盘留痕）
    ├── boxbench_live.py     # 本机实时工作台，包装本地/SSH 测试命令
    ├── live/               # 动态流程图页面与离线图标
    ├── render_report.py     # 报告渲染器（纯 Python3 标准库, 默认脱敏+复核记录+管理层摘要）
    └── vendor/              # 报告内嵌图表资源
```

## 转移到其它工具

1. 整目录拷贝 `skill/`
2. 对 Claude Code：放入 `~/.claude/skills/` 或项目 `.claude/skills/`
3. 对任意 Agent：把 SKILL.md 设为指令，SPEC.md 与 scripts/ 保持相对路径
4. 无需安装任何依赖：bash + python3（各盒子/开发机标配）

## 版本记录

完整版本历史见仓库根目录 [CHANGELOG.md](../CHANGELOG.md)。基准数据校准自 ZYSJ-E300K（Qwen3.6-35B-A3B W4A8：24.0 tok/s，4 路并发）。
