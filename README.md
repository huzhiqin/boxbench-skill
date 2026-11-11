# BoxBench Skill — 工控算力盒子标准化实测套件

> v1.3.7 ｜ 工具无关 ｜ MIT License
> 让任何 AI 编程工具（WorkBuddy / Claude Code / Cursor / Cline…）都能对工控算力盒子做标准化实测，产出统一格式的 HTML 验收报告。

## 安装

### 方式一：直接把仓库丢给 AI 工具（推荐）

对任何 AI 编程工具（WorkBuddy / Claude Code / Cursor / Cline…）说：

> 帮我安装这个 skill：https://github.com/huzhiqin/boxbench-skill （克隆仓库，把 skill/ 目录作为 skill 安装）

国内网络访问 GitHub 困难时，用 Gitee 镜像：

> 帮我安装这个 skill：https://gitee.com/276635035/boxbench-skill

AI 会自动克隆仓库并把 skill 装到对应 skills 目录。Windows 上的 AI 工具同样适用（克隆后 skill 文件均为 LF 换行，可直接使用）。

### 方式二：脚本安装（无 AI 工具 / CI 环境）

```bash
# GitHub
curl -fsSL https://raw.githubusercontent.com/huzhiqin/boxbench-skill/main/install.sh | bash
# 国内网络（Gitee 源）
curl -fsSL https://gitee.com/276635035/boxbench-skill/raw/main/install.sh | bash
```

- 自动探测已安装的 AI 工具（WorkBuddy / Claude Code / Cursor / Continue），装到对应 skills 目录
- 脚本内置 GitHub → Gitee 双源自动切换（单文件下载失败自动换源）
- 可用环境变量指定目标：`BOXBENCH_TARGET=~/.claude/skills bash install.sh`

**Windows 用户**：install.sh 是 bash 脚本，需在 **Git Bash**（装 Git for Windows 自带）或 **WSL** 中执行。WorkBuddy 的 skills 目录位于 `%USERPROFILE%\.workbuddy\skills`（Git Bash 中即 `~/.workbuddy/skills`，脚本自动探测）。安装后 boxbench.sh / render_report.py 的使用方式与 macOS/Linux 一致。

## 升级

```bash
~/.workbuddy/skills/box-bench/boxbench-update   # 路径以实际安装位置为准
```

升级前自动对比本地与远端版本号，已是最新则跳过。版本历史见 [CHANGELOG.md](CHANGELOG.md)。
本仓库 GitHub 与 Gitee 双平台同步发布，任一源拉到的版本一致。

## 使用

安装后对 AI 工具说：

> 测这台盒子：IP 192.168.x.x，账号 dev，密码 xxx

Agent 会按 `SKILL.md` 编排执行：硬件指纹 → 环境盘点 → 查平台经验库 → 模型实测（12 项）→ 渲染 HTML 报告 → 回写经验库。

也可以不用 AI 工具，手动/CI 执行：

```bash
scp skill/scripts/boxbench.sh user@device:~/
ssh user@device "bash ~/boxbench.sh"
scp user@device:~/boxbench_results_*.json .
python3 skill/scripts/render_report.py boxbench_results_xxx.json --device "型号" --model "模型"
```

Windows 本机注意：`python3` 换成 `python` 或 `py`；被测设备是 Windows 时 boxbench.sh 无法直接运行（依赖 /proc 等 Linux 工具），按 SKILL.md「被测设备是 Windows 系统时」的路径处理（WSL 或 PowerShell 等价采集）。

## 特性

- **工具无关**：纯 Markdown + Bash + Python3 标准库，零第三方依赖
- **规范驱动**：`SPEC.md` 是测试项/判定标准的唯一权威定义，报告跨设备可比
- **经验库自进化**：`PLATFORM_NOTES.md` 按引擎×芯片记录已踩坑与可用模型，每测一台设备自动回写，同平台不再重复踩坑
- **硬件分档**：D1~D5 五档设备档位自动匹配推荐模型清单，跑不动的自动跳过并注明原因
- **多模型横向对比**：multi 模式顺序测试多模型，自动生成对比表与图表

## 测试范围

| 阶段 | 内容 |
|---|---|
| A 硬件指纹 | 芯片/内存/存储/NPU/系统/网络（9 项） |
| B 环境盘点 | 模型权重/引擎/加速栈/容器/服务（5 项） |
| C 模型实测 | 加载/解码/TTFT/长上下文/并发2/4/工具调用/多轮/显存/多模态/质量（12 项） |
| D 容量结论 | 并发建议/场景判定（只写实测，禁止估算） |

## 目录结构

```
boxbench-skill/
├── skill/                    # skill 本体（安装时拷入 AI 工具的 skills 目录）
├── install.sh                # 脚本安装（可选，AI 安装无需它）
├── .gitattributes            # 强制脚本 LF 换行（Windows clone 兼容）
├── CHANGELOG.md              # 版本历史
├── LICENSE                   # MIT
└── README.md
```

## License

MIT — 见 [LICENSE](LICENSE)
