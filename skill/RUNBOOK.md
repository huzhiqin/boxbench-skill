# BoxBench RUNBOOK — 从拿到盒子到交付报告（换人可 100% 复现）

> 适用：任何 AI 编程工具（WorkBuddy / Claude Code / Cursor / 其它 Agent）+ 一台工控算力盒子。
> 前置条件只有两条：执行机有 `ssh`/`scp`；本机有 Python3。无第三方依赖。
> 每步都有**预期输出**与**异常对照**。跑完保留三件产物：`boxbench_run_*.log`（过程留痕）、`boxbench_results_*.json`（原始数据）、`*_实测报告_*.html`（交付物）。

## 0. 前置条件清单

| # | 检查项 | 怎么查 | 不满足时 |
|---|---|---|---|
| 0.1 | 执行机有 ssh/scp | `which ssh scp` | Windows 10 1809+ 自带；更老的用 Git Bash/WSL |
| 0.2 | 执行机有 Python3 | `python3 --version`（Windows 用 `python --version`） | 装 Python 3.8+，仅标准库即可 |
| 0.3 | 设备 SSH 可达 | `ssh <user>@<IP> hostname` | 确认 IP/账号/密码；密码登录见异常 A-1 |
| 0.4 | scripts/ 目录完整 | `ls scripts/vendor/chart.umd.min.js` 存在 | 从仓库补齐（渲染器 vendor 丢失会降级 CDN，离线打不开图） |

## 1. 测前：查经验库（SKILL.md 第 0 步）

```bash
# 阶段B 跑完得到平台键后再执行亦可; 已知平台键可直接同步
python3 scripts/boxbench_exp.py sync --platform <平台键>     # 联网时, 自动合并公共经验
```
**预期输出**：`synced N atoms into PLATFORM_NOTES.md` 或离线提示（不阻塞）。
然后**人工打开 `PLATFORM_NOTES.md`** 查该平台的"已踩坑/可用模型"。

## 2. 分发脚本到设备

```bash
scp scripts/boxbench.sh <user>@<IP>:~/
# 完整性校验（可选但推荐, 防 SSH 通道吃字符）:
md5 -q scripts/boxbench.sh                      # 本机
ssh <user>@<IP> "md5sum ~/boxbench.sh"          # 设备
```
**预期输出**：两边 MD5 一致。
⚠ 异常见 A-2（MD5 不一致）。

## 3. 设备端执行

交互测试推荐在本机启动工作台，原命令放到 `--` 后面：

```bash
python3 scripts/boxbench_live.py -- ssh <user>@<IP> "bash ~/boxbench.sh"
# Agent 内置浏览器：加 --no-open，读取 BOXBENCH_LIVE_URL 后在内置浏览器打开
# CI 不保留页面：加 --linger 0；不要将演示模式 --demo 用于验收
```

**预期输出**：首先出现 `BOXBENCH_LIVE_URL=...`，网页中节点随真实测试更新，底部显示日志；结束后保留15分钟。原始命令仍可直接使用：

```bash
ssh <user>@<IP> "bash ~/boxbench.sh"                    # 自动模式
# 多模型:
ssh <user>@<IP> 'bash ~/boxbench.sh multi "模型名|模型绝对路径" ["模型名2|路径2" ...]'
```
**预期输出**：屏幕滚动 `[时间戳] [boxbench] 阶段A/B/C...` 日志（同时落盘到设备上 `boxbench_run_*.log`），最后 `完成: boxbench_results_YYYYMMDD_HHMMSS.json`。

**服务未就绪时**：脚本自动跳过阶段C 并提示 `⚠ 服务未就绪(...)，跳过阶段C`。此时手动启动模型服务后补采：
```bash
ssh <user>@<IP> "bash ~/boxbench.sh collect"
```

## 4. 取回结果并渲染

```bash
scp <user>@<IP>:~/boxbench_results_*.json .
scp <user>@<IP>:~/boxbench_run_*.log ./logs/           # 过程留痕一并取回
python3 scripts/render_report.py boxbench_results_XXX.json 报告.html --device "设备型号" --model "模型名"
```
**预期输出**：`OK -> 报告.html`。默认已脱敏（IP/主机名替换为占位符）；产物中不应出现设备内网 IP，可用 `grep -c "<内网IP>" 报告.html` 抽查。

## 5. 交付前人工复核（合规硬要求，不可跳过）

打开报告，逐项勾选尾部"人工复核记录"：
1. ☐ 结论数字与 JSON 一致（抽 C2 解码速度、C7 并发、通过率三处即可）
2. ☐ 敏感信息检查：`grep -E "192\.168\.|10\.\d|172\.(1[6-9]|2[0-9]|3[01])\." 报告.html` 应为 0 命中
3. ☐ C12 生成样例人工已读（无乱码/复读）
4. 填写复核人与日期 → 之后才允许对外发送

## 6. 测后：回写经验库

1. `PLATFORM_NOTES.md` 回写本次新坑/新基线（SKILL.md 第 6 步，**必做**）
2. `python3 scripts/boxbench_exp.py push --result boxbench_results_XXX.json` 上传公共池（默认开启；退出 `export BOXBENCH_CONTRIBUTE=0`）

## 异常对照表

| # | 症状 | 原因 | 处理 |
|---|---|---|---|
| A-1 | ssh 密码交互卡住 | 执行机无 expect/sshpass | 配 ssh 密钥；或 plink -pw（PuTTY）；或让用户手动输一次 |
| A-2 | 设备上脚本 md5 与本机不一致 | SSH 通道转义吃字符 / CRLF | 用 base64 传输：`base64 < boxbench.sh \| ssh user@ip "base64 -d > ~/boxbench.sh"`；检查 `grep -c $'\r' boxbench.sh` 应为 0 |
| A-3 | 阶段C 全部跳过 | 模型服务未启动 | 启动服务（见 PLATFORM_NOTES 该平台"已验证可用"的启动命令）→ `bash boxbench.sh collect` |
| A-4 | multi 提示"磁盘/内存不足，暂未测试" | 资源预检未过 | 按报告提示清理（该平台经验库有"磁盘清理参考"）或换更小量化 |
| A-5 | 渲染报 KeyError/结构错 | JSON 被截断或旧版本 | 检查设备磁盘；旧 JSON 用对应旧版渲染器或补采 |
| A-6 | 报告图表空白、出现 cdn.jsdelivr 引用 | vendor 丢失 | 下载 chart.umd.min.js 4.4.1 放回 scripts/vendor/ 重渲染 |
| A-7 | Windows 设备上 bash 不可用 | boxbench.sh 依赖 /proc | 有 WSL 进 WSL；无 WSL 用 `python scripts\boxbench_windows.py`（同等产出） |
| A-8 | 模型加载必崩（GGML_ASSERT） | NPU 不认普通 GGUF | 查经验库"已踩坑"：需专用转换格式（如 xh2），走 model-cli pull |
| A-9 | PowerShell 重定向后脚本在设备上跑不了 | PS 5.1 `>` 默认 UTF-16LE | `Set-Content -Encoding UTF8` 或直接 scp（勿经 PS 重定向） |
| A-10 | thinking 模型 C8 工具调用失败 | 思考内容挤占输出 token | 脚本已内置 `enable_thinking:false`；手动测试时同理（PLATFORM_NOTES 坑 #9） |
| A-11 | Agent 内置浏览器打开看板 URL 显示 404/空白 | 内置浏览器经 CDP 中继连接，`127.0.0.1` 在**中继侧**解析——中继那台机器上没有看板服务，返回的是中继自己的 404，**不是看板服务的 404**（2026-11-27 WorkClaw 实测：curl 直连同 URL 200、错 token 路径 404、同机静态服务 200，三方对照证实） | ① 先 `curl -s -o /dev/null -w "%{http_code}" $URL` 自证服务正常；② 不要重试内置浏览器（CDP relay 场景重试必败）；③ 立即把 URL 原文发用户用**系统浏览器**打开（系统浏览器在本机回环内直连可达）；④ 看板保留期已过 → `--replay boxbench_live_*.jsonl` 重演 |

## 产物归档清单（每台设备）

```
{设备型号}/
├── boxbench_run_YYYYMMDD_HHMMSS.log   # 过程留痕（真实执行证明）
├── boxbench_results_YYYYMMDD_HHMMSS.json  # 原始数据（可复核、可跨设备对比）
└── {设备型号}_实测报告_YYYYMMDD.html   # 交付物（已脱敏 + 复核记录已填）
```
