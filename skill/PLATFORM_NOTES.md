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

### ✅ 已验证可用

- **引擎启动**：`LD_LIBRARY_PATH=<engine>/lib llama-server -m <model.gguf> -dev 0 -ngl 999 --host 0.0.0.0 --port 17701 --jinja --ctx-size 8192`
- **模型获取**：引擎自带 `model-cli`（bin/ 目录）：
  - `model-cli query "target=xh2"` 列云端模型（140+，含 Stable/Temporary 状态、chips 数、W4A8 量化）
  - `model-cli pull <ID>` 下载（自动 MD5 校验）
  - `model-cli list` / `ps` / `run` / `stop` 管理本地模型
- **1chip Stable 可跑大模型**（2026-11 快照）：Qwen3.6-35b-a3b（W4A8）、Qwen3.8-27b-mtp（W4A8）、GPT-OSS_20b、Gemma4_26b-a4b、Qwen3.5_9b
- **磁盘清理参考**：旧版模型/tar 包在 `~/houmoAI/houmo/` 下，当前版本模型在 `1_model/`，删除旧版不影响现役服务

### 📊 实测基线（可用作跨设备对比锚点）

| 模型 | 加载 | 解码 | TTFT | 并发4路 | 显存 |
|---|---|---|---|---|---|
| Qwen3.6-35B-A3B(W4A8) v1.5.0 | ~131s | ≈44 字/s（估算口径，v1.1 时代） | 0.40s | ✅ 无衰减 | 4.0G/31.4G |
| Qwen3.8-27b-mtp(W4A8) 20260911 | ~116s | ≈9 字/s（估算口径，v1.1 时代） | 1.12s | ✅ 无衰减 | 6.2G/31.4G |

> 注：上表为 v1.1 估算口径（字/s）。下次同平台复测将以 usage 口径（tok/s）覆盖。

### 🎯 本平台选型结论（2026-11-11，利用率优先）

- **生产首选：Qwen3.6-35B-A3B(W4A8)**——显存仅占 4G/30G，TTFT 0.40s，4 路并发无衰减，设备跑它绰绰有余
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
