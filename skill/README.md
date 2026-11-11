# BoxBench — 工控算力盒子标准化测试套件

> 版本 1.6.5 ｜ SPEC 1.4 ｜ 2026-11-11
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
└──────────────────────────────────────────────────┘
```

## 快速开始

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
├── PLATFORM_NOTES.md        # 引擎×芯片经验库（自进化）
├── HARDWARE_MODEL_MATRIX.md # 硬件分档 D1~D5 推荐模型
└── scripts/
    ├── boxbench.sh          # Linux/盒子端采集脚本（bash, 无依赖）
    ├── boxbench_windows.py  # Windows 端一键采集（LM Studio/NVIDIA 已验证）
    ├── render_report.py     # 报告渲染器（纯 Python3 标准库）
    └── vendor/              # 报告内嵌图表资源
```

## 转移到其它工具

1. 整目录拷贝 `skill/`
2. 对 Claude Code：放入 `~/.claude/skills/` 或项目 `.claude/skills/`
3. 对任意 Agent：把 SKILL.md 设为指令，SPEC.md 与 scripts/ 保持相对路径
4. 无需安装任何依赖：bash + python3（各盒子/开发机标配）

## 版本记录

完整版本历史见仓库根目录 [CHANGELOG.md](../CHANGELOG.md)。基准数据校准自 ZYSJ-E300K（Qwen3.6-35B-A3B W4A8：24.0 tok/s，4 路并发）。
