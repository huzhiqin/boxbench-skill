# PLATFORM_NOTES — 推理引擎×芯片平台经验库

> **目的**：避免重复踩坑。同一引擎+芯片的盒子，测过的坑、规则、可用模型直接复用，不重新探索。
> **索引键**：`引擎名+芯片`（见下方目录）。**每次实测完成后必须回写本文件**（SKILL.md 第 6 步）。
> 本文件是事实记录（全部来自实测），与 SPEC.md（规范）、HARDWARE_MODEL_MATRIX.md（分档）互补。

## 目录

| 平台键 | 芯片 | 引擎 | 状态 |
|---|---|---|---|
| `houmo-HLIELLama-xh2` | MTT E300K / M1000 NPU | HLIELLama (llama.cpp 衍生) | ✅ 已验证（ZYSJ-E300K，2026-11-11） |

---

## `houmo-HLIELLama-xh2` — 后摩 M1000/E300K + HLIELLama 引擎

**验证设备**：ZYSJ-E300K（m1000，8核AArch64 2.65GHz + M1000 NPU 50TOPS，32GB LPDDR5，推理内存~30GB）
**引擎版本**：v1.5.0（2026-08-24 构建）

### 🚫 已踩坑（直接避）

1. **NPU 只认 HiModel_xh2 转换格式**。普通 HuggingFace GGUF 用 `-dev 0` 加载必崩（GGML_ASSERT(buft) 失败）；纯 CPU 可跑但无意义。→ 选型时必须确认模型有 xh2 转换版。
2. **`-dev all` 参数不对**，必须 `-dev 0`。
3. **带 `-mm` 视觉编码器启动必挂**（v1.5.0 复测依旧）。多模态在该引擎暂不可用，报告标注"引擎限制未测"。
4. **SSH 命令含括号/引号会被通道吃掉**（scp 上传脚本后 md5 校验确认完整性；或用 base64 编码传输）。
5. **2chips 模型在 1chip 设备上不可用**（云端模型列表会标 chips 数，先核对）。
6. **llama-server blocks 值含换行**会导致 JSON 组装失败（v1.2 已在脚本内修复，注意旧数据）。
7. **NPU 利用率计数器不可用**（2026-11-11 实测）：mthreads-gmi -q 的 `Gpu:` 与 mthreads-smi 的 `gpu utilization` 在 LLM 推理全程（含 prefill/并发）恒 0.0%——驱动 5.2.2-M1000 未实现该计数器，不代表 NPU 未工作（引擎计时/输出正常）。本平台算力利用证据链 = C2/C4 吞吐 + 显存/温度占用。温度读数正常可用。
8. **后台采样器 + 裸 `wait` 死锁**（boxbench v1.5 首测踩坑）：util_start 的永循环后台子 shell 会让 C6/C7 并发段的裸 `wait` 永远等下去。修复：并发 curl 记录 `$!` 后 `wait $PIDS`；采样器启动必须 `> /dev/null 2>&1 &` 防止 stdout 污染结果文件。任何在测试期间加"后台监控进程"的改造都要检查所有裸 wait。
9. **thinking 开启 = 空回复 + 工具调用失效**（2026-11-09 E300 实测）：思考模型（如 Qwen3.6）开启 thinking 时，思考内容会挤占输出 token，导致 content 为空、function calling 无法触发。接入智能体框架或跑 C8 工具调用必须显式 `chat_template_kwargs: {"enable_thinking": false}`（boxbench.sh 已内置）。需要 thinking 输出时，必须相应放大 max_tokens 预算。
10. **空 content 先查 `reasoning_content` 字段**（2026-11-09 排查经验）：响应 content 为空时，先检查 message 里是否有 `reasoning_content`（reasoning 模型可能把输出放进该字段）及 `finish_reason`，再怀疑服务/模板问题。排查顺序：message keys → reasoning_content/content 特殊 token → finish_reason。
11. **阶段 E 自动安装需要 sudo**（2026-11-18 实测）：官方 `install.sh` 要更新包索引/装 build tools/配 NodeSource 源，全部走 sudo。dev 账号无免密 sudo 时在第 1 步即中止，`phase_e` 落 `openclaw_autoinstall_failed`，渲染器措辞写成"网络受限或依赖缺失"，**实际是权限问题**——排查先看 `boxbench_run_*.log` 里的 `sudo: a terminal is required`。测前若想跑通阶段 E：先配免密 sudo，或手工装好 OpenClaw 后用 `BOX_OPENCLAW=$(which openclaw)`；只想跑 C 阶段可 `BOX_AGENT_SKIP=1` 省 1~3 分钟。
12. **阶段 E 的 CLI 形式随版本漂移**（2026-11-18 实测）：boxbench.sh 早期用 `openclaw --non-interactive --message "..."` 发对话，但 OpenClaw 2026.5.x 起该顶层形式已不存在，报 `Error: Unknown command: openclaw hi`（把 message 误当子命令）。正确形式：`openclaw agent --session-id <key> --message "..."`（`agent` 子命令经网关跑一轮对话，stdout 为纯文本回复）。`oc_send` 已改为按 `--help` 是否含 `--non-interactive` 自动选新旧形式，且**每条用例独立 `--session-id`**——共用 session 会累积历史，后续请求越来越慢并污染判据。
13. **`oc_send` 副作用变量被命令替换子 shell 吞掉 → JSON 组装失败**（2026-11-18 连踩两轮）：`wall_s` 靠全局 `OC_WALL_S` 传回，但调用方 `R=$(oc_send ...)` 捕获 stdout 时整个函数在子 shell 里跑，`OC_WALL_S` 赋值丢失 → phase_e 里 `"wall_s":` 后为空 → 最终 `python3 json.loads` 报 `Expecting value: line N`。修复：`oc_send` 结尾把耗时 `printf` 落盘 `$TMPD/oc_wall`，调用方 `OC_WALL_S=$(cat "$TMPD/oc_wall")` 读回。**"函数副作用全局变量 + `$(...)` 捕获 stdout" 的组合必踩此坑**；且 `OC_WALL_S` 的 `printf` 必须在计时 T1 计算之后（先写=写空值）。
14. **非交互 SSH 下 `openclaw`/`node` 不在 PATH**（2026-11-18 实测）：用户态 Node 在 `~/.local/node/bin`、openclaw 在 `~/.local/bin`，非交互 SSH 默认 PATH 不含这两处 → `command -v openclaw` 为空，且 openclaw shebang 是 `#!/usr/bin/env node`，直接报 `env: "node": 没有那个文件或目录`。修复：`phase_agent` 开头把 `~/.local/node/bin`、`~/.local/bin`、`~/.npm-global/bin`、`/usr/local/bin` 依次补进 PATH 再探测；远程命令里显式 `export PATH=$HOME/.local/node/bin:$HOME/.local/bin:$PATH`。

### ✅ 已验证可用

- **引擎启动**：`LD_LIBRARY_PATH=<engine>/lib llama-server -m <model.gguf> -dev 0 -ngl 999 --host 0.0.0.0 --port 17701 --jinja --ctx-size 8192`
- **模型获取**：引擎自带 `model-cli`（bin/ 目录）：
  - `model-cli query "target=xh2"` 列云端模型（140+，含 Stable/Temporary 状态、chips 数、W4A8 量化）
  - `model-cli pull <ID>` 下载（自动 MD5 校验）
  - `model-cli list` / `ps` / `run` / `stop` 管理本地模型
- **1chip Stable 可跑大模型**（2026-11 快照）：Qwen3.6-35b-a3b（W4A8）、Qwen3.8-27b-mtp（W4A8）、GPT-OSS_20b、Gemma4_26b-a4b、Qwen3.5_9b
- **磁盘清理参考**：旧版模型/tar 包在 `~/houmoAI/houmo/` 下，当前版本模型在 `1_model/`，删除旧版不影响现役服务
- **OpenClaw 阶段 E 接入本地模型（2026-11-18 跑通，5/5）**：设备 OpenClaw 2026.5.7（用户态装于 `~/.local`，Node v22.14.0）。接法：① `openclaw config patch --file xx.json5` 写 `models.providers.houmo`（`baseUrl=http://127.0.0.1:17701/v1`、`api=openai-completions`、`apiKey` 任意占位、models[0] 用**短 id** + `compat.toolSchemaProfile="llamacpp"` + `supportsTools=true` + `reasoning:false` + `contextWindow/maxTokens`），`agents.defaults.model.primary=houmo/<短id>`；② `nohup openclaw gateway --allow-unconfigured > ~/oc_gateway.log 2>&1 &`（首次自动生成 gateway token 存 config，端口 18789 回环）；③ 阶段 E 用 `openclaw agent --session-id bb_<ts> --message "..."` 发用例。llama-server 真实 model id 是完整长文件名，provider 里用短 id 由 OpenClaw 映射即可，无需匹配。

### 📊 实测基线（可用作跨设备对比锚点）

| 模型 | 加载 | 解码（usage 口径） | TTFT | 并发4路 | 显存 | 温度峰值 |
|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B(W4A8) v1.5.0 | 130s | 23.6 tok/s | 0.40s | ✅ 无衰减 | 3.6G/31.4G | 32.9℃ |
| Qwen3.8-27b-mtp(W4A8) 20260911 | 136s | 4.8 tok/s | 1.12s | ✅ 无衰减 | 5.8G/31.4G | 34.5℃ |

> 2026-11-11 boxbench v1.5 复测（usage 口径覆盖旧估算值）。NPU 利用率计数器不可用（见已踩坑 #7）。
> 2026-11-17 再次复测（同一台 m1000，v1.9.1 脚本 collect 模式）：C2 解码 174tok/7.26s≈24 tok/s、TTFT 0.4s、显存 3.8G/31.4G、并发 2/4 全过、温度峰值 28.6℃——与基线一致，复现稳定。注意并发段 usage.completion_tokens 返回 0（引擎并发响应不回 usage），并发速度只能按 wall_s 判衰减。
> 2026-11-17 三次复测（同一台 m1000，192.168.81.82，v1.10.1 脚本 collect 模式，SPEC v1.4）：C2 解码 164tok/6.92s=23.7 tok/s、TTFT 0.40s、显存 3880MiB/31367MiB、并发 2 路 9.6s / 4 路 22.4s 全过、工具调用/多轮召回通过、温度峰值 29.9℃、设备档位 D4——与基线一致，复现稳定（当天第三次独立验证）。HTML 报告已产出并过脱敏/离线自检。
> 2026-11-18 复测（同一台 m1000，192.168.81.82，v1.10.3 脚本 collect 模式，SPEC v1.5）：设备冷启动后首次测试，服务健康探测 503→200 用时约 105s（开机负载 8.0，GNOME 桌面占用 CPU）。C2 解码 165tok/6.87s=**24.0 tok/s**、TTFT 0.36s、显存 4478MiB/31367MiB、并发 2 路 10.5s / 4 路 20.6s 全过、工具调用/多轮通过、温度峰值 35.3℃、档位 D4——与基线一致。注意：本机磁盘仅余 11G（95G 用 89%），多模型测试的前置预检会因此跳过部分模型；本机未装 OpenClaw，阶段 E 自动跳过。C5 补测（流式分段）：短上下文 52.0 char/s → 长上下文约6400字 43.1 char/s，衰减 17.2%（<20% 基线，通过）。
> 2026-11-18 正式测试（同一台 m1000，192.168.81.82，**v1.10.9 脚本 multi 模式**，SPEC v1.6）：按硬性规则 #12 用 multi 起服务计时 C1——**加载 111s**、C2 解码 179tok/7.37s=**24.3 tok/s**、TTFT 0.36s、C4 长上下文 1050tok/2.95s、并发 2 路 10.6s / 4 路 21.0s 全过、工具调用/多轮通过、显存 4538MiB/31367MiB、温度峰值 36.4℃、档位 D4，通过率 8/8——与基线一致。**新坑 #11：阶段 E 自动安装需 sudo**，dev 账号无免密 sudo，install.sh 在"更新包索引"即中止（脚本误报为"网络受限或依赖缺失"，实际是权限问题），phase_e 记为 openclaw_autoinstall_failed。
> 2026-11-18 **阶段 E 跑通**（同一台 m1000，192.168.81.82，脚本 v1.12.0 三修，SPEC v1.6，multi 取证轮）：设备 OpenClaw 2026.5.7 + 网关接本地 llama-server(17701)，**E1~E6 全过（5/5，独立分节不计 C 通过率）**——E2 端到端 79.6s（1+1=2）、E3 单工具 81.4s（无内置 calc，用 shell 算术得 3288）、E4 多步链 75.7s（590）、E5 输出预算 805 字符未截断、E6 纯文本回退 68.5s（北京）。端到端单轮 68~81s（35B 的 Agent 框架开销，正常）。同轮阶段 C：C1 加载 110s、C2 解码 170tok/7.04s≈24.1 tok/s、TTFT 0.36s、并发 2 路 10.2s / 4 路 19.7s 全过、工具/多轮过、显存 4810MiB/31367MiB、温度峰值 37.6℃、档位 D4。本轮修 3 坑（#12 CLI 形式 / #13 wall_s 子 shell / #14 PATH）；**前两轮阶段 E 其实全过但 JSON 组装失败无法归档**——教训：阶段 E "全过" 要用修复后 `json.loads` 能正常解析校验，不能只看各 ok 字段。

### 🎯 本平台选型结论（2026-11-11，利用率优先）

- **生产首选：Qwen3.6-35B-A3B(W4A8)**——解码 23.6 tok/s 是 27b-mtp 的 ~5 倍，显存仅占 3.6G/30G，4 路并发无衰减，设备跑它绰绰有余
- **27b-mtp 解码仅 4.8 tok/s**：MTP（multi-token prediction）在该引擎/芯片组合上未兑现速度优势，无场景需求不选
- **不要再向下测更小模型**（用户决策）：35B 都绰绰有余时，GPT-OSS_20b/Qwen3.5_9b 级别属于大材小用，浪费测试时间
- 有场景需求时按"特化方向"补测（如 Qwen-AgentWorld_35b-a3b 做 Agent 对比），而不是按"更小参数"补测

### ☁️ 云端可测模型全景（1chip Stable，2026-11-11 快照）

**LLM（文本生成）**：
| 模型 | ID | 参数 | 量化 | 上下文 | 备注 |
|---|---|---|---|---|---|
| Qwen3.6_35b-a3b | 6 | 35B | W4A8 | 256k | ✅ 已测，生产首选 |
| Qwen3.8_27b-mtp | 9 | 27B | W4A8 | 128k | ✅ 已测 |
| Qwen-AgentWorld_35b-a3b | 59 | 35B | W4A8 | 256k | Agent 特化，引擎要求 1.4.0（本机 1.5.0 兼容） |
| GPT-OSS_20b | 91 | 20B | W4A8 | 256k | 引擎 1.4.0 |
| Gemma4_26b-a4b | 79 | 26B | W4A8 | 256k | 视觉档(768×2520)，⚠️ 引擎 -mm 必挂坑可能影响 |
| Qwen3.5_9b | 98 | 9B | W4A8 | 256k | 视觉档(448×448) |
| Qwen3-Coder-30B | — | 30B | — | — | ❌ 云端无 xh2 版，本机不可测 |

**多模态/语音/嵌入式配套**：Z-Image-Turbo_6b（ID 12，文生图）、PaddleOCR-VL_0.9b（ID 11）、Qwen3-Embedding_8b（ID 64）、Qwen3-Reranker_8b（ID 67）、Qwen3-ASR_1.7b（ID 62）、Qwen3-TTS_1.7b（ID 4）、GLM-ASR_1.9b（ID 61）、Whisper-Turbo_0.8b（ID 66）等——RAG/语音/OCR 场景配套，按需选测。

**2chips+ 专属（1chip 设备不可跑）**：Qwen3.6_35b W8A8/W5A8（ID 56/57）、Qwen3-Next_80b-a3b（ID 7）、Qwen3.5_122b-a10b（ID 13）、GPT-OSS_120b（ID 117）、Gemma4_31b（ID 88）

---

<!-- BOXBENCH-COMMONS:BEGIN platform=houmo-HLIELLama-xh2 -->
> 🤖 公共经验池自动同步（机器生成，勿手改；与本机冲突时以本地实测为准）

### BoxBench Commons — houmo-HLIELLama-xh2

> Auto-generated from the public Commons. Trust tiers: verified (≥2 independent sources) / curated (operator-confirmed).
> Local measurements always win on conflict; Commons entries are advisory.

#### Capabilities (works)
- ran on houmo-HLIELLama-xh2 [curated ×1]

#### Baselines
- Qwen3.8-27b-mtp(W4A8): **2.16 tok/s** [curated ×1]
- Qwen3.6-35B-A3B(W4A8) w4a8: **23.59 tok/s** [curated ×3]
- unknown: **24.02 tok/s** [verified ×2]
<!-- BOXBENCH-COMMONS:END -->


## 回写格式

测完新平台后追加：

```
## `<引擎名>-<芯片>` — <厂商/产品线> + <引擎>

**验证设备**：<型号>（<关键配置>）
**引擎版本**：<版本>

### 🚫 已踩坑（直接避）
1. ...

### ✅ 已验证可用
- ...

### 📊 实测基线
| 模型 | 加载 | 解码 | TTFT | 并发4路 | 显存 |
|---|---|---|---|---|---|
```

规则：
- 只记**实测验证过**的事实，标注验证日期；推测内容不写入
- 同平台复测发现新坑/旧坑已修，直接更新该条目并刷新验证日期
- 模型快照过时（云端列表变化）时更新"可跑大模型"清单
