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

### ✅ 已验证可用

- **引擎启动**：`LD_LIBRARY_PATH=<engine>/lib llama-server -m <model.gguf> -dev 0 -ngl 999 --host 0.0.0.0 --port 17701 --jinja --ctx-size 8192`
- **模型获取**：引擎自带 `model-cli`（bin/ 目录）：
  - `model-cli query "target=xh2"` 列云端模型（140+，含 Stable/Temporary 状态、chips 数、W4A8 量化）
  - `model-cli pull <ID>` 下载（自动 MD5 校验）
  - `model-cli list` / `ps` / `run` / `stop` 管理本地模型
- **1chip Stable 可跑大模型**（2026-11 快照）：Qwen3.6-35b-a3b（W4A8）、Qwen3.8-27b-mtp（W4A8）、GPT-OSS_20b、Gemma4_26b-a4b、Qwen3.5_9b
- **磁盘清理参考**：旧版模型/tar 包在 `~/houmoAI/houmo/` 下，当前版本模型在 `1_model/`，删除旧版不影响现役服务

### 📊 实测基线（可用作跨设备对比锚点）

| 模型 | 加载 | 解码（usage 口径） | TTFT | 并发4路 | 显存 | 温度峰值 |
|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B(W4A8) v1.5.0 | 130s | 23.6 tok/s | 0.40s | ✅ 无衰减 | 3.6G/31.4G | 32.9℃ |
| Qwen3.8-27b-mtp(W4A8) 20260911 | 136s | 4.8 tok/s | 1.12s | ✅ 无衰减 | 5.8G/31.4G | 34.5℃ |

> 2026-11-11 boxbench v1.5 复测（usage 口径覆盖旧估算值）。NPU 利用率计数器不可用（见已踩坑 #7）。
> 2026-11-17 再次复测（同一台 m1000，v1.9.1 脚本 collect 模式）：C2 解码 174tok/7.26s≈24 tok/s、TTFT 0.4s、显存 3.8G/31.4G、并发 2/4 全过、温度峰值 28.6℃——与基线一致，复现稳定。注意并发段 usage.completion_tokens 返回 0（引擎并发响应不回 usage），并发速度只能按 wall_s 判衰减。
> 2026-11-17 三次复测（同一台 m1000，192.168.81.82，v1.10.1 脚本 collect 模式，SPEC v1.4）：C2 解码 164tok/6.92s=23.7 tok/s、TTFT 0.40s、显存 3880MiB/31367MiB、并发 2 路 9.6s / 4 路 22.4s 全过、工具调用/多轮召回通过、温度峰值 29.9℃、设备档位 D4——与基线一致，复现稳定（当天第三次独立验证）。HTML 报告已产出并过脱敏/离线自检。

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

#### Baselines
- Qwen3.6-35B-A3B(W4A8) w4a8: **23.59 tok/s** [curated ×1]
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
