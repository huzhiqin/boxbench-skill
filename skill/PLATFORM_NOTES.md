# PLATFORM_NOTES — 推理引擎×芯片平台经验库

> **目的**：避免重复踩坑。同一引擎+芯片的盒子，测过的坑、规则、可用模型直接复用，不重新探索。
> **索引键**：`引擎名+芯片`（见下方目录）。**每次实测完成后必须回写本文件**（SKILL.md 第 6 步）。
> 本文件是事实记录（全部来自实测），与 SPEC.md（规范）、HARDWARE_MODEL_MATRIX.md（分档）互补。

## 目录

| 平台键 | 芯片 | 引擎 | 状态 |
|---|---|---|---|
| `houmo-HLIELLama-xh2` | MTT E300K / M1000 NPU | HLIELLama (llama.cpp 衍生) | ✅ 已验证（ZYSJ-E300K，2026-11-11） |
| `lmstudio-llamacpp-rtx5060ti-x2` | NVIDIA RTX 5060 Ti ×2 (16GB/卡) | LM Studio 0.4.24 / llama.cpp CUDA12 | ✅ 已验证（DESKTOP-7D1MG3D / Windows 11，2026-11-11） |

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

## `lmstudio-llamacpp-rtx5060ti-x2` — NVIDIA RTX 5060 Ti ×2 + LM Studio / llama.cpp（Windows 侧）

**验证设备**：DESKTOP-7D1MG3D（Windows 11 家庭版 build 26200 / 10.0.26200，Intel Core Ultra 7 270K Plus 24 核，63.3GB DDR5，双 RTX 5060 Ti 各 16311 MiB，C: 350GB + D: 601.5GB）
**引擎版本**：LM Studio 0.4.24 + llama.cpp-win-x86_64-nvidia-cuda12-avx2-2.73.0（b7011），本地服务 127.0.0.1:1234
**验证日期**：2026-11-11（OS：Windows，非工控 Linux 盒子；走 SKILL.md「被测设备是 Windows」路径 2）

### 🚫 已踩坑（直接避）

1. **`boxbench.sh` 在 Windows 本机完全不可用**：依赖 `/proc`、`lscpu`、`free`、`lsblk`、`ss`、`mthreads-gmi`，本机均无。必须走 PowerShell（Get-CimInstance / Get-NetIPAddress / Get-NetTCPConnection / nvidia-smi）+ Python 等价采集，产出同结构 JSON 再交给 render_report.py——v1.3.8 起用 `scripts/boxbench_windows.py` 一键完成。
2. **WSL 路径 1 在本环境不可用**（wsl.exe 被安全策略禁用）；只能走路径 2。
3. **LM Studio 没有 `/health` 端点**：`GET /health` 返回 `{"error":"Unexpected endpoint or method. (GET /health)"}`。boxbench.sh 的 `curl $API/health | grep '"ok"'` 会误判「服务未就绪」。正确探测：`GET /v1/models` 判断已加载模型 + 一次短 `/v1/chat/completions` 探测。
4. **Qwen3.6-35B-A3B GGUF 强制思考模式**（最坑）：`chat_template_kwargs.enable_thinking=false`、顶层 `enable_thinking=false`、prompt 加 `/no_think`、system prompt 禁止思考 **四种方式全部无效**，reasoning_tokens 吃满 max_tokens，`message.content` 为空，导致首轮 C2/C4/C6/C7/C8/C9 全部假失败（C8 变成 finish_reason=length）。**唯一有效：`"reasoning_effort": "none"`**，实测 reasoning_tokens=0，0.44s 出正文。
5. **Win32_VideoController.AdapterRAM 32 位溢出**：16GB 卡报 4GB，且 WDDM 重复报同名卡。显存/型号必须用 `nvidia-smi --query-gpu=...` 读。
6. **`Win32_OperatingSystem.FreePhysicalMemory` 单位是 KB 不是 MB**；按 MB 换算会得到 0GB 空闲的错误结论。
7. 渲染器 C6/C7 判定必须实现 SPEC §4.3 的「聚合 tok/s ÷ 路数 衰减 <30%」基线（仅判请求全部成功会把衰减超标误判 ✅）。本平台实测 4 路全成功但单路衰减 55.2%，按 SPEC 应判 ❌。v1.6.0 起渲染器已内置该判定，可直接采信 KPI 卡。
8. 渲染器内 `SPEC_VERSION` 已随主版本对齐 SPEC.md，报告中无需再标注不一致。

### ✅ 已验证可用

- **`scripts/boxbench_windows.py` 已在本平台端到端验证**（2026-11-11）：一条命令完成阶段A/B/classify + C2~C12，JSON 直接渲染成功；本报告即由该脚本产出。Windows 复测直接运行 `python scripts/boxbench_windows.py --api http://127.0.0.1:1234`。
- **报告空字段修复已验证**（2026-11-11）：Windows 独立 GPU 无 NPU 标称值时 KPI 卡改用实测「长上下文 prefill ≈9555 tok/s（C4 折算）/ 加速卡显存合计 31.9 GiB」，不再显示 N/A；「统一内存」改为「系统内存 + 独立显存，取较小值」；C1 服务预启动时显示「首请求就绪 0.71s（含 JIT 加载）」并注明不计入通过率；未测权重按 SPEC §4.2 自动聚合 shard 并写入「二·补」区块。
- **C5 阶段C 增强已验证**（2026-11-11）：C5 用流式同请求分段实测可行——LM Studio 支持 `stream_options.include_usage`，本平台实测 prefill 0.143s / decode 88.5 tok/s / 较 C2 衰减 1.1% ✅；C4 prefill 改由该分段给出（≈14559 tok/s），折算值仅作交叉校验。服务若有 prompt cache 会影响 prefill 绝对值，不影响 decode 段。
- **GPU 运行时采样**：阶段C 全程 nvidia-smi 采样（25 次）得利用率平均 45.9% / 峰值 71.5%、单卡功耗平均 56.9W / 峰值 86.7W（TDP 180W）、温度 28.5→39.5°C —— 证明算力仍有余量（详见「模型推荐清单」）。
- **`lms` CLI 可用**（`~/.lmstudio/bin/lms.exe`）：`lms ps` 可读 CONTEXT/PARALLEL 还原等价加载参数（`lms load <key> --gpu max -c <ctx> --parallel <n> --identifier <id>`），`lms load --estimate-only` 可看资源估算，`lms get <name>@<quant> --gguf -y` 可下载；GUI 无原生启动命令行。
- **backend 选择坑**：`~/.lmstudio/extensions/backends/` 排序后第一个是 CPU avx2 版，直接取会误报引擎 build；必须优先选含 cuda/nvidia 的目录名。
- OpenAI 兼容接口：`/v1/models`、`/v1/chat/completions`（含 streaming、tools API、多轮 messages）；tools 正常返回 `finish_reason=tool_calls` + `tool_calls`。
- `usage` 返回 `prompt_tokens` / `completion_tokens` / `completion_tokens_details.reasoning_tokens`，可直接用 SPEC 的 tok/s 口径，无需字/s 估算。
- 加载配置可读：`~/.lmstudio/.internal/user-concrete-model-default-config/<publisher>/<model>/<file>.gguf.json` → `llm.load.contextLength=262144`、`evalBatchSize=4096`。
- 权重盘点路径：`~/.lmstudio/models/...`（本机 Qwen3.6-35B-A3B-Q4_K_M.gguf 19.71GB + mmproj 0.84GB）。
- 推理服务首次请求触发 JIT 加载：加载前 nvidia-smi 显示 0 MiB，加载后双卡各约 14GB；因此「C1 冷启动耗时」若服务已预启动则无法实测，禁止估算。

### 📊 实测基线（2026-11-11，Qwen3.6-35B-A3B Q4_K_M GGUF，19.71GB，双卡 offload，ctx 256K，全部带 reasoning_effort=none）

| 项 | 实测 |
|---|---|
| C1 加载 | 未测（服务预先启动） |
| C2 解码 | 168 tok / 1.62s = **103.7 tok/s**（usage 口径） |
| C3 TTFT | **0.16s**（流式首个非空 content chunk） |
| C4 长上下文 | 2082 prompt tok / 0.93s，摘要 ✅；C5 流式实测 prefill ≈14559 tok/s |
| C5 解码衰减 | 88.5 tok/s（较 C2 衰减 1.1% ✅） |
| C6 并发 2 | 2/2 成功，248 tok / 1.67s，聚合 148.5 tok/s，单路 74.3（衰减 28.4% ✅） |
| C7 并发 4 | 4/4 成功，509 tok / 2.74s，聚合 185.8 tok/s，单路 46.4（衰减 **55.2% ❌ 超 SPEC 基线**） |
| C8 / C9 / C12 | 工具调用 ✅ / 多轮记忆 ✅（BX-7788）/ 中文输出通顺 ✅ |
| C10 显存 | GPU0 14434/16311 MiB、GPU1 13951/16311 MiB |

### 🎯 本平台结论（2026-11-11）

- **建议并发 ≤2 路**：4 路虽不失败但单路吞吐衰减 55.2%，不满足 SPEC 的 30% 基线；KPI 卡「4/4 通过」只代表请求成功。
- **跳过模型**：`Qwen3.8-Flash-Next 去对齐微调版(IQ3_S)` 权重 77.87GB（2 shards），×1.15 ≈ 需 89.6GB 推理内存，实际可用 32GB → ⏭ 内存不足暂未测试；磁盘 D: 余 523.3GB 充足。模型未加载，U1~U3 附加项未执行。
- C1 / C11 未实测（服务未以视觉模式启动），按硬性规则不估算、不计入通过率。

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
