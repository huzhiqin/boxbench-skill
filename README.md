# BoxBench Skill — 工控算力盒子标准化实测套件

> v1.2 ｜ 工具无关 ｜ MIT License
> 让任何 AI 编程工具（WorkBuddy / Claude Code / Cursor / Cline…）都能对工控算力盒子做标准化实测，产出统一格式的 HTML 验收报告。

## 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/huzhiqin/boxbench-skill/main/install.sh | bash
```

- 自动探测已安装的 AI 工具（WorkBuddy / Claude Code / Cursor / Continue），装到对应 skills 目录
- 可用环境变量指定目标：`BOXBENCH_TARGET=~/.claude/skills bash install.sh`

## 升级

```bash
~/.workbuddy/skills/box-bench/boxbench-update   # 路径以实际安装位置为准
```

升级前自动对比本地与远端版本号，已是最新则跳过。版本历史见 [CHANGELOG.md](CHANGELOG.md)。

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
├── skill/box-bench/          # skill 本体（安装时拷入 AI 工具的 skills 目录）
├── install.sh                # 一键安装/升级
├── CHANGELOG.md              # 版本历史
├── LICENSE                   # MIT
└── README.md
```

## License

MIT — 见 [LICENSE](LICENSE)
