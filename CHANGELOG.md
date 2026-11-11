# Changelog

All notable changes to BoxBench Skill will be documented in this file.

## [1.2] - 2026-11-11

### Added
- `PLATFORM_NOTES.md` 平台经验库：按引擎×芯片索引，测前必查、测后必回写
- `HARDWARE_MODEL_MATRIX.md` 硬件分档与模型矩阵（D1~D5，8000~50000 元价位段）
- multi 模式：多模型顺序测试 + 横向对比报告（KPI 卡/对比表/对比图表/每模型运行配置）
- 前置硬件适配性检查：硬件不支持/磁盘不足/内存不足自动跳过并注明原因，不计通过率
- 利用率优先选型策略：首选档位最大可用模型，默认不向下测小模型
- 运行配置采集（engine 段）：模型权重/量化/引擎版本/启动命令行，保证横向对比公平性
- U1-U3 附加测试：去对齐微调版模型的合规验证（红线抽测/越狱抵抗/能力对比）

### Changed
- 速度口径统一为 API usage（tok/s）：C2/C4/并发均以 completion_tokens/耗时 计
- 旧数据自动降级标注"估算（字/s）"

## [1.1] - 2026-11-11

### Added
- 多模型顺序测试（multi 模式），boxbench.sh 自动管理服务生命周期
- 资源预检（磁盘/内存不足自动跳过）

## [1.0] - 2026-11-11

### Added
- 初版：SPEC.md 规范 + boxbench.sh 采集脚本 + render_report.py 渲染器
- 阶段A 硬件指纹（9 项）/ 阶段B 环境盘点（5 项）/ 阶段C 模型实测（12 项）/ 阶段D 容量结论
- 基线数据校准自 ZYSJ-E300K（Qwen3.6-35B v1.5.0：24.0 tok/s，4 路并发）

## [1.3.1] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.3.2] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.3.3] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.3.4] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.3.5] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.3.6] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.6.0] - 2026-11-11

### Added
- **合并 Windows 实测优化线（v1.3.8/v1.3.9）到主线**：本版本起单一分支同时覆盖 Linux 工控盒与 Windows 设备两类被测平台
- `scripts/boxbench_windows.py`（随 v1.3.8 引入、v1.3.9 增强）：被测设备为 Windows 时的一键等价脚本——阶段A/B/classify + 阶段C（C2~C12）一条命令完成，PowerShell 5.1 + Python 标准库零依赖，产出与 boxbench.sh 同结构 JSON；支持 `--api/--model/--thinking none|keep/--all`；已内置 Windows 实测踩坑修正（显存必须用 nvidia-smi 读、LM Studio 无 /health 用 /v1/models 探测、思考模型仅 `reasoning_effort=none` 可关闭）
- **C5 长上下文解码衰减真实补测**（boxbench_windows.py + 渲染器）：流式同请求分段计时（首 content chunk 之前=prefill，其后=decode），按 SPEC §4.3 衰减 <20% 判定；报告 C4 prefill 优先采用 C5 流式实测值
- **boxbench_windows.py GPU 运行时采样**：阶段C 全程 nvidia-smi 0.4s 间隔采样（利用率/功耗/温度）写入 `runtime_metrics`，报告新增「GPU 运行时（阶段C 实测）」行
- **Windows 环境指纹补全**：A7 GPU 温度、A9 power.limit/TDP、B3 CUDA/驱动栈、engine 权重构建日期、`lms ps` 还原等价加载参数
- PLATFORM_NOTES.md 新增 `lmstudio-llamacpp-rtx5060ti-x2` 平台条目（RTX 5060 Ti ×2 + LM Studio，含强制思考/reasoning_effort、显存 32 位溢出、FreePhysicalMemory KB 陷阱等 8 项坑与实测基线）

### Changed
- render_report.py 融合 Windows 线修复（保持 C13 上下文阶梯 / C14 NPU 利用率等 v1.5 特性不变）：
  - C6/C7 按 SPEC §4.3 增加「单路 tok/s 相对 C2 衰减 <30%」判定（此前仅判请求全部成功，衰减超标被误判 ✅）；结论「建议并发规模」改按衰减基线实测推导
  - C5 无流式分段数据时如实标注「未实测（缺流式分段计时）」不计入通过率；导读文案 C5 修正为「长上下文解码衰减」并补 C13/C14
  - 单模型模式权重文件从 engine 段读取、正反斜杠路径兼容、补权重构建日期与服务端口
  - 无 NPU 标称 TOPS/带宽的设备（Windows 独立 GPU）KPI 卡改用实测「长上下文 prefill / 加速卡显存合计」填卡，不留 N/A；「统一内存」按独立显存架构改写
  - C1 服务预启动时显示「首请求就绪（含 JIT 加载，实测）+ 未测说明」；对比表 C1 的 `—` 改「未测」
  - 标题/摘要显示真实模型 id（原单模型模式写死「预装模型」）；foot 标注原始 JSON 文件名
- boxbench_windows.py 版本号随主线（1.6.0），SPEC_VERSION 对齐 1.4

## [1.3.9] - 2026-11-11

### Added
- **C5 长上下文解码衰减真实补测**：流式同请求分段计时（首 content chunk 之前=prefill，其后=decode），流式 usage 取 token 数，按 SPEC §4.3 衰减 <20% 判定；C4 prefill 改用该实测分段替代按 C2 速度的折算值
- **阶段C 全程 GPU 运行时采样**（利用率/功耗/温度，nvidia-smi 0.4s 间隔）写入 `runtime_metrics`，报告新增「GPU 运行时（阶段C 实测）」行
- Windows 环境指纹补全：A7 GPU 温度、A9 power.limit/TDP、B3 CUDA/驱动栈、engine 权重构建日期、从 `lms ps` 还原的等价 `lms load` 加载参数（含 --port）
- 报告内置「v1.3.9 报告完善清单」：逐项列出已修复项与仍需用户决策项

### Fixed
- 标题/摘要显示真实模型 id（原写死「预装模型」）
- 运行配置表权重文件：单模型模式改从 engine 段读取、兼容 Windows 反斜杠路径；补权重构建日期与服务端口（原「未记录」）
- `engine_build` 优先选 CUDA backend（原误取排序第一的 CPU avx2 版）
- 导读 C5 文案与 SPEC 对齐（原误写「C5 温度稳定性」）
- 单模型模式误报「boxbench v1.3 之前数据、启动参数未记录」的提示
- Agent 补充段所有数值改为按本轮 JSON 动态计算，消除跨轮硬编码，与徽标通过率口径一致
- 新版驱动 nvidia-smi 头部无 CUDA Version 时，从 LM Studio backend 名推断并标注来源
- foot 标注原始 JSON 文件名

## [1.3.8] - 2026-11-11

### Added
- `scripts/boxbench_windows.py`：被测设备为 Windows 时的一键等价脚本（`boxbench.sh` 依赖 /proc、lscpu、free、ss 等，Windows 不可用）——阶段A/B/classify + 阶段C（C2~C12）一条命令完成，PowerShell 5.1 + Python 标准库零依赖，产出与 boxbench.sh 同结构 JSON 交给 render_report.py 照常渲染；支持 `--api/--model/--thinking none|keep/--all`
- 首次跑通 Windows 全流程：DESKTOP-7D1MG3D（Windows 11 build 26200 / Ultra 7 270K Plus / 63.3GB DDR5 / 双 RTX 5060 Ti 16GB）+ LM Studio 0.4.24 + Qwen3.6-35B-A3B Q4_K_M，C2~C12 真实实测并产出报告

### Fixed
- render_report.py：C6/C7 按 SPEC §4.3 增加「单路 tok/s 相对 C2 衰减 <30%」判定（此前仅判请求全部成功，衰减超标被误判 ✅）；结论「建议并发规模」改按衰减基线实测推导
- render_report.py：内嵌 SPEC_VERSION 1.1 → 1.2，与 SPEC.md 对齐
- Windows 实测踩坑内置修正（详见 PLATFORM_NOTES `lmstudio-llamacpp-rtx5060ti-x2`）：显存必须用 nvidia-smi（Win32_VideoController.AdapterRAM 32 位溢出，16GB 卡报 4GB）；FreePhysicalMemory 单位是 KB；LM Studio 无 /health 端点，服务探测回退 GET /v1/models；Qwen3.6 GGUF 强制思考模式下 chat_template_kwargs / enable_thinking / /no_think 均无效，仅 `reasoning_effort=none` 可关闭
- render_report.py：Windows GPU 工作站无 NPU 标称 TOPS/带宽时，KPI 卡不再留 `N/A`，改用本轮实测的「长上下文 prefill（C4 折算 tok/s）」与「加速卡显存合计（nvidia-smi）」；规格表「统一内存」按独立显存架构改写；C1 未冷启动时显示「首请求就绪耗时（含 JIT 加载，实测）+ 未测说明」而非空白/「见服务日志」；multi 对比表 C1 的 `—` 改为「未测」
- 新增「二·补、本轮未测模型」区块：按 SPEC §4.2 对本地未测权重做 shard 聚合与资源推算，明确列出跳过原因及 §4.4 U1~U3 未执行说明（例：Flash-Next 77.87GB ×1.15 ≈ 需 89.6GB > 实际 31GB）
- KPI 卡「4/4 路通过」改为按 SPEC 衰减口径标注（「4/4 路成功 / 单路衰减 xx% 超基线」），避免把「请求未失败」误读为「无衰减可用」

### Changed
- SKILL.md：v1.3.8；「被测设备是 Windows 系统时」路径 2 更新为运行一键脚本；资产清单加入 boxbench_windows.py

## [1.3.7] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.6.1] - 2026-11-11

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）
