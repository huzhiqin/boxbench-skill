# Changelog

All notable changes to BoxBench Skill will be documented in this file.

## [1.10.2] - 2026-11-17

### Added
- **阶段 E：OpenClaw Agent 框架集成测试**（SPEC v1.5 / boxbench.sh v1.7）——Linux 设备默认执行
  - E1 网关探活 / E2 端到端单轮问答 / E3 单工具真实执行 / E4 多步工具链 / E5 输出预算截断 / E6 纯文本回退
  - 未装 OpenClaw、非 Linux 或 `BOX_AGENT_SKIP=1` 自动跳过，不阻塞其他测试
  - 设计动机：C8 通过 ≠ Agent 能用——阶段 E 验证 C8 覆盖不到的真实工具执行循环与 tool parser 问题（如 MiniCPM5 专用 parser）
- 渲染器：每模型新增"Agent 框架集成（阶段 E）"分节（跳过/E2 失败提前收尾均有明确说明），多模型对比表新增"Agent 集成 E"行；E 结果独立于 C 通过率
- live 看板新增 `agent` 阶段（latency 与 archive 之间）
- SPEC §4.5 阶段 E 完整定义（触发条件/测试项/判定标准）；SKILL.md 执行流程、E 失败判读与经验库回写指引

## [1.10.1] - 2026-11-17

### Changed
- SKILL.md 新增硬性规则 #9：真实测试必须用 live 工作台包装并把看板交给用户（内置浏览器打开/系统浏览器弹出/URL 原文发给用户，三选一），"collect 很快""复采"等理由不再构成跳过借口
- 第 2 步示例命令补充说明：内置浏览器 Agent 用 --no-open 并自行打开 URL，无内置浏览器时省略让系统浏览器弹出

## [1.10.0] - 2026-11-17

### Added
- 本机实时测试工作台 `boxbench_live.py`：包装本地/SSH命令、回环HTTP服务、自动浏览器打开、动态蛇形流程、节点详情、运行耗时、实时日志与快照导出。
- Linux / Windows 采集脚本通过结构化 stderr 事件上报阶段状态；Windows 按实际执行顺序调整流程，支持未就绪跳过、异常和多模型切换历史。
- 全部前端资源与 Tabler 图标本地分发，无运行时 CDN；提供明确标注的 `--demo` 动效演示。CI 可继续用原脚本或 `--linger 0`。

## [1.9.0] - 2026-11-16

### Added（参赛合规与可复现强化）
- **报告默认脱敏**：`render_report.py` 渲染前对整个结果 JSON 递归脱敏——IP/IPv6/MAC 替换为占位符（回环地址保留），`phase_a.hostname` 定向替换为 `<主机·设备型号>`；`--no-redact` 可关闭（产物尾注标"⚠ 未脱敏版"）。经验池上传路径本有双重脱敏，现报告交付路径对齐同一口径，报告可直接对外提交。
- **人工复核环节（合规硬要求）**：报告尾部新增"人工复核记录"表（数字一致性抽查/敏感信息检查/C12 人工已读/复核人与日期）；SKILL.md 新增第 5.5 步交付前人工复核，明确"助手不得自动外发"。
- **管理层摘要**：报告首屏新增"30 秒版"白话结论（整体判定/推荐模型/能支撑什么业务/加载耗时），管理层无需读懂 prefill/TTFT 即可决策。
- **过程留痕**：`boxbench.sh` 与 `boxbench_windows.py` 的日志全部带时间戳落盘 `boxbench_run_*.log`，作为真实执行的过程记录与 JSON/报告一并归档。
- **RUNBOOK.md**：一页复现 SOP——前置条件→逐步命令→每步预期输出→10 类异常对照表（SSH 密码/CRLF/服务未就绪/资源不足/vendor 丢失/UTF-16LE 陷阱/NPU 格式崩溃等），换人可 100% 复现。
- **AUTOMATION.md**：定时回归模板（WorkBuddy 定时任务 / cron 双形态），在管盒子周期自动跑分+四项硬指标趋势对比。

### Changed
- README 新增"价值量化"段：人工 ~5h/台 vs BoxBench ~30min/台的环节级对比表。

## [1.8.0] - 2026-11-16

### Fixed
- **跨语言哈希不一致（严重）**：Python 客户端把整数值浮点序列化成 `0.0`，JS 服务端写成 `0`，同一份实测两侧算出的 `evidence_hash` 不同，客户端预填的哈希会被服务端 G4 判为不符。`canonical_json` 现按 JCS（RFC 8785）把整数值浮点规范为整数，三向（Python / TS / atom_id）哈希全部对齐。
- **女巫攻击（严重）**：发布者身份是客户端自选 token 的哈希，换个 token 就是“新的独立发布者”，单机数据即可升 T2。独立性改为按**设备指纹**（从证据硬件字段推导）计数，换 token 无效。受影响的 `facts.publishers` 正名为 `devices`。

### Added
- `sync --all`：先拉平台目录，再逐个把公共经验合并进 `PLATFORM_NOTES.md`。
- `selftest`：离线自测 PLATFORM_NOTES 合并的不变量（手写内容保留、顺序、标题层级、幂等、原位替换、新平台追加）与 canonical JSON 浮点规范。已接入 `exp-verify.sh`。
- 服务端 `GET /api/exp/pull` 不带 `platform_key` 时返回平台目录概览（trust / facts / devices / last_seen），供客户端自动发现。
- 仲裁台新增「仲裁记录」区块（`/api/exp/queue` 返回最近 30 条 `curator_log`），人工裁决可追溯。

### Fixed（续）
- `curator_log` 表建了但**从未写入**，人工把数据提到 T3 没有任何审计轨迹。现每次 approve/reject/quarantine 都落一条。
- **`min_trust=0` 源过过滤漏洞（严重）**：raw 模式只比 `trust >= min_trust`，被隔离的篡改原子 `trust=0` 会被 `0 >= 0` 放行、对外公开。现在公开规则统一为“必须 status=accepted”，并抽成可测函数 `publicAtoms()`。
- `min_trust=abc` 静默返回空池（`NaN` 比较恒假），看起来像“没有数据”。参数现夹在 1–3，非法值回落默认 2。
- 补传（`flush`）原来**逐条发请求**，outbox 有 N 条就串行发 N 次 HTTP。现按服务端上限每批 20 条发送；网络失败整批保留、部分应答只删已确认的，不丢数据。
- **合并进 PLATFORM_NOTES 的位置与层级**：机器块原来紧贴在平台标题下方，把手写笔记挤到后面、割裂了人写的内容；且 digest 的 `#` 标题会**高过**包裹它的 `##` 章节。现改为插到章节末尾，并把 digest 标题整体降两级。新增 `selftest` 守护这些不变量。

## [1.7.0] - 2026-11-16

### Added
- **公共经验池（BoxBench Commons）**：全网经验共享。`scripts/boxbench_exp.py` 提供 `sync` / `pull` / `push` / `flush` / `status`，零第三方依赖。
- `sync` 把公共经验幂等合并进 `PLATFORM_NOTES.md`，用 `<!-- BOXBENCH-COMMONS:BEGIN/END -->` 标记隔离，**绝不覆盖手写内容**，支持 `--dry-run`。
- 平台键自动推断：从 `engine.engine_name` 首词推导（与 PLATFORM_NOTES 索引方式一致）；推断不出时明确报错，不编造键名。
- 默认上传、可退出：`BOXBENCH_CONTRIBUTE=0` 只拉不传。离线自动进本地 outbox，`flush` 补传。
- 服务端门控 G1–G12 + 信任阶梯 T0–T3；仲裁台 `/exp-admin`（批量操作、证据详情展开）。

### Fixed
- **自我佐证漏洞**：晋升 T2 原按 `evidence_hash` 去重，而哈希含时间戳，同一设备重跑一次即可自我佐证。改为按不同 `publisher_id` 计数（回归测试已覆盖）。
- `publisherCount` 缺 `status='accepted'` 过滤，会把隔离条目计入。
- 客户端 ETag 只读不写，`.etag` 永不生成，304 缓存优化完全失效。`_request` 现返回响应头并持久化。
- `release.sh` 会把 `__pycache__/*.pyc` 当发布文件上传。
- SKILL.md 资产表多行合并成一行的 Markdown 损坏；SPEC 版本标注过时（v1.2 → v1.4）。

### Changed
- SKILL.md 第 0 步由「pull 只读」改为「sync 合并」；第 6 步 push 不再要求手填 `--platform`。

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

## [1.6.1] - 2026-11-11

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

## [1.6.2] - 2026-11-11

### Changed
- CHANGELOG 补全 v1.3.8/v1.3.9（Windows 优化线）历史条目；[1.6.1] 为 Windows 融合版主体说明

## [1.6.3] - 2026-11-11

### Changed
- CHANGELOG 追加 1.6.2 明细说明（由 release.sh 自动触发的版本递增）

## [1.6.4] - 2026-11-11

### Changed
- README 双份梳理：skill/README.md 修正 SPEC 版本误标（1.6.3→1.4）、架构图与目录结构补 boxbench_windows.py/PLATFORM_NOTES/HARDWARE_MODEL_MATRIX/vendor、旧目录名 box-bench/ 更正为 skill/、阶段C 更新为 C1~C14、快速开始补 Windows 采集路径、移除过时的"4 个文件 <30KB"；主 README 测试范围同步 C1~C14
- boxbench.sh: NPU 利用率后台采样静默输出、并发 wait 改精确 PID 等待

## [1.6.5] - 2026-11-11

### Changed
- README 双份梳理与 CHANGELOG 明细补充（1.6.4 明细、清理自动占位条目）
- boxbench.sh: NPU 利用率后台采样静默输出、并发 wait 改精确 PID 等待（含 1.6.4 主体内容）



## [1.9.1] - 2026-11-16

### Fixed
- **release.sh bump 污染 SPEC 版本**：bump_version 曾把 skill/README.md 的 "SPEC 1.4" 覆盖为 skill 版本号，现固定为 SPEC 1.4。
- **渲染器功能移植回归**：把 HEAD(v1.6.1) 独有而 11-11 实战线丢失的 4 块功能移植回 render_report.py——C1 首请求就绪回退口径(c1_probe_s)、C5 流式分段 prefill+解码衰减、并发单路衰减超 30% 按 SPEC 判失败、运行配置表权重构建日期+Windows 路径兼容。合成数据验证全部通过。

### Changed
- 12 个文件同步 GitHub + Gitee（含新增 RUNBOOK.md / AUTOMATION.md / boxbench_exp.py）。

## [1.10.2] - 2026-11-17

### Changed
- SKILL.md 新增硬性规则 #9：真实测试必须用 live 工作台包装并把看板交给用户（内置浏览器打开/系统浏览器弹出/URL 原文发给用户，三选一），"collect 很快""复采"等理由不再构成跳过借口
- 第 2 步示例命令补充说明：内置浏览器 Agent 用 --no-open 并自行打开 URL，无内置浏览器时省略让系统浏览器弹出

## [1.10.1] - 2026-11-17

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.10.3] - 2026-11-17

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.10.4] - 2026-11-18

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.10.5] - 2026-11-18

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.10.6] - 2026-11-18

### Added
- **阶段 E0：OpenClaw 自动安装**（SPEC v1.6 / boxbench.sh v1.8）——Linux 未装 OpenClaw 时自动执行官方 `openclaw.ai/install.sh --no-onboard`（约1~3分钟），装完刷新 PATH 重探测；失败才跳过（新 skipped 原因 `openclaw_autoinstall_failed`）。`BOX_AGENT_AUTOINSTALL=0` 恢复"未装即跳过"旧行为
- **版本自更新机制**：新增 `scripts/check_update.sh`（本地 vs GitHub/Gitee 版本对比，`--verbose`/`--upgrade`；离线输出 unknown 不阻塞）；SKILL.md 新增第 0.5 步"实测前版本自检"；boxbench.sh 设备端后台异步自检（24h 缓存，脚本过旧时日志提示）

### Fixed
- **报告"本轮无推荐清单内模型被实测"误报**（2026-11-18 实测反馈）：collect 模式模型名曾硬编码"预装模型"，与分档推荐清单匹配必落空。渲染器新增 `infer_model_name`——从引擎启动命令行 `-m` 参数反解真实模型名（HiModel_xh2_qwen3.6-35b-a3b_w4a8_... → Qwen3.6 35B A3B）；分档匹配增加 norm_loose（去连字符/点/括号）兜底。已用真实数据验证：推荐表正确显示"✅ 已测（100% 通过）"
- boxbench_live.py 日志时间戳从完整日期简化为时分秒（可读性）

### Changed
- **看板必须在测试命令启动前打开**（硬性规则 #9 追加）：collect 全程仅约 1 分钟，先跑后开看板用户只会看到最终静态画面（教训：2026-11-18 用户反馈"看板没有任何变化"）
- **正式测试用 multi，不用 collect**（新增硬性规则 #12）：multi 是唯一能计时 C1 加载耗时的单模型模式；collect 仅限"服务外部启动且无法重启"的补采场景，报告须标注"补采"
- **新增硬性规则 #10**：用户质疑看板"没进展"时用 `--replay <journal>` 按真实时间轴重演，不重跑真实测试（boxbench_live.py 新增 `--replay`/`--replay-speed`）
- **新增硬性规则 #11**：报告实测模型名必须真实，禁止"预装模型"等占位名入正式报告

## [1.10.7] - 2026-11-18

### Changed
- CHANGELOG.md 补充 [1.10.6] 变更明细（E0 自动安装/版本自检/三处渲染与规则修复）；README 微调

## [1.10.8] - 2026-11-18

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.10.9] - 2026-11-18

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）
## [1.10.11] - 2026-11-18

### Fixed
- **阶段 E 三修（2026-11-18 m1000 实测，5/5 跑通）**：
  1. `oc_send` 的 OpenClaw CLI 形式随版本漂移：`openclaw --non-interactive --message` 在 2026.5.x 起报 `Unknown command`。改为按 `--help` 自动选新旧形式（agent 模式用 `openclaw agent --session-id bb_<ts> --message`，每条用例独立 session，避免历史累积拖慢+污染判据）
  2. `wall_s` 空值导致最终 JSON `json.loads` 失败（`$(...)` 捕获 stdout 时 `OC_WALL_S` 在子 shell 丢失）：改为 `$TMPD/oc_wall` 落盘回读，且写入必须在计时计算之后
  3. 非交互 SSH 下 `openclaw`/`node` 不在 PATH（用户态装于 `~/.local`）：`phase_agent` 开头补齐 `~/.local/node/bin`、`~/.local/bin`、`~/.npm-global/bin`、`/usr/local/bin`
- `collect_engine_info`：`--version` 首行是构建号（`version: 6043 (hash) ...`）时不得当 engine_name（会让经验库平台键变成 `version:`）；改为优先取产品标识，取不到回退引擎目录名（houmo-HLIELLama-xh2）；EBUILD 记录完整版本串

### Added
- PLATFORM_NOTES `houmo-HLIELLama-xh2`：新增已踩坑 #12/#13/#14（上述三修）、OpenClaw 阶段 E 接入本地 llama-server 的可复用配方（provider 短 id 映射 + gateway --allow-unconfigured + agent --session-id）、阶段 E 跑通基线（E2~E6 68~81s/轮，5/5）

## [1.11.0] - 2026-11-19

### Changed
- **C6/C7 并发测试重设计（SPEC v1.7 / boxbench.sh v1.8 / boxbench_windows.py v1.7.0）**：由固定 2/4 路"能不能撑住"改为**并发能力上探**——单路基准（与阶梯同规格 200 max_tokens 请求）→ 2/4/8/16/32 倍增阶梯，每档全部成功且单路衰减 <30% 才继续，首个失败档的前一档即**最大无衰减并发 conc_max**
  - JSON 新增 `conc_baseline` / `c6c7_concN.verdict` / `conc_max` 字段；阶梯上界 32 路，触顶标注"实际可能更高"
  - 衰减口径：有 usage 按"本档完成 token 量折算串行基准份数"修正；无 usage 退化 wall/路数（引擎并发响应不回 usage 的已知坑兜底）
- 渲染器：C6 行改阶梯各档明细（ok/耗时/单路 tok/s/衰减%），C7 行改"最大并发 conc_max"；KPI 卡/管理层摘要/结论"建议并发规模"/多模型对比表全部切换 conc_max 口径；NPU 利用率分段自动取上探最高档
- 旧 JSON 兼容：无 conc_max 时渲染器自动从 c6c7_conc2/conc4 推导（4 路全过=4，否则 2 路全过=2）
- live 看板并发阶段描述同步更新；SPEC.md 升 v1.7，SKILL.md SPEC 引用同步
- 已用 20261118 真实历史 JSON（旧结构）+ 新结构 mock 数据双路径回归渲染验证

## [1.10.12] - 2026-11-26

### Changed
- **峰值/均值双口径落地（渲染器+采集端，Windows 线）**：boxbench_windows.py C2 改流式 chunk 计时，新增 `speed_peak_tps`（1s 滑动窗口最大瞬时）/`speed_mean_tps`；C5 补峰值统计；KPI 卡「最快解码」→「解码速度（峰值/均值）」，摘要行/多模型对比表/结论行同步双口径，旧数据（无峰值字段）优雅降级
- 渲染器 `infer_model_name()` 路径来源加**顶层 `model_path` 兜底**（引擎段被修正/覆盖时仍能反解模型名，防"预装模型"回退复发）；品牌名连字符恢复 Gyro-S/Inkling-2/Flash-Next；量化段正则支持 TQ1_0 尾段
- SKILL.md 硬性规则 #13：解码速度必须峰值/均值并列，禁止把均值标成"最快"（推测解码引擎峰值可达均值 1.3~2 倍，实测 46.2 vs 36.3 教训）
- 实测验证：百应 AI Max 395 Gyro-S 重测，C2 峰值 43.8 / 均值 35.6 tok/s（158 chunks），C5 峰值 47.7 / 均值 38.6，报告模型名/峰值字段全链路正确

## [1.10.14] - 2026-11-26

### Added
- **C10/GPU 采样 AMD/核显支持（Windows 线）**：nvidia-smi 不可用时自动回退 Windows GPU Engine 性能计数器（零安装，核显/独显通吃）——`_ps_gpu_engine_sample()` 按显存最大进程自动锁定推理进程 PID，聚合其 compute 引擎实例利用率；`gpu_vram_counters()` 读专用显存。C10 在 AMD 设备不再跳过
- 渲染器 `build_util_section` 支持 `runtime_metrics.source=gpu-counter` 路径：全场综合利用率行 + 计数器口径判读；计数器路径不触发"恒 0"警告；显存判读兼容计数器口径文案

### Fixed
- **计数器实例名多实例后缀坑**：实例名形如 `engtype_compute 0`（带空格+编号），通配必须 `*pid_X*engtype_compute*` 宽松匹配；严格 `engtype_compute` 尾匹配会全部落空 → util 恒 0（百应 395 首轮验证踩中并修复）

### Verified
- 百应 AI Max 395（Radeon 8060S 核显）实测：util avg 128.5% / max 158.6%（多调度器聚合口径 >100%），显存 37.1GB；NVIDIA 路径 mock 回归不变，全失败兜底返回 None 不阻塞

## [1.10.14] - 2026-11-26

### Changed
- 发布更新（由 release.sh 自动记录，建议手动补充变更明细）

## [1.10.15] - 2026-11-26

### Added
- **经验池 push 自动化（防漏跑，机制级修复）**：`render_report.py` 渲染成功后自动执行经验池 push（构建 atom → 入 outbox → 上传），不再依赖 Agent 记性执行手动步骤
  - 幂等去重：本地台账 `~/.boxbench/pushed_ledger.json` 按 `evidence_hash` 记录，同一结果 JSON 重渲染不重传（已实测验证：首推成功 + 二次渲染跳过）
  - 失败不阻塞渲染：atom 留 outbox，`flush` 可重传；下次同 JSON 渲染自动补推
  - 退出开关：`BOXBENCH_CONTRIBUTE=0` 或渲染加 `--no-push`；`--model`/`--platform` 精细参数仍走手动 push
  - 无实测数据（phase_c/models 空）或平台键无法推断时跳过并打印原因
- 背景：2026-11-26 Gyro-S 轮因 push 是 SKILL.md 第 6 步纯文字要求，在改 JSON/重渲染循环中被漏掉，经验池缺 11-26 记录

## [1.10.16] - 2026-11-26

### Added
- **live 看板流水线新增第 14 环节「上传经验池」（exp-push）**：位于「结果归档」之后，图标 cloud-upload（Tabler，本地分发）
  - boxbench.sh / boxbench_windows.py 归档完成后发 `exp-push done` 事件（标注：push 挂接在渲染器，设备端不直接联网）
  - `MODEL_STAGES` 切片改为 `[3:-2]`，exp-push 与 archive 一样不随模型切换重置
  - 与 v1.10.15 的渲染器自动 push 配套：看板上用户能看到经验池上传这一步真实存在

## [1.10.17] - 2026-11-26

### Fixed
- **看板 exp-push 事件语义修正（用户反馈驱动）**：归档完成后看板不再直接亮"完成"——boxbench.sh / boxbench_windows.py 归档时改发 `running` 状态（前端 loader 进行中动画），真实上传仍由本机渲染器在渲染报告成功后自动 push
- boxbench_live.py 进程退出处理特判 exp-push：保持 running 并改写文案为"等待本机渲染报告时自动上传"，不再被误标为"执行中断"异常（原逻辑会把进程退出时所有 running 阶段强制标 failed）
- 离线模拟验证 PASS（事件流全链路）+ py_compile / bash -n 语法检查通过

## [1.10.18] - 2026-11-26

### Fixed
- **看板 exp-push 收尾语义再修正（WorkClaw 实测反馈）**：v1.10.17 的"进程退出后保持 running 转圈"被实测判定为"卡死"误观感——收尾时落定为「已执行」+ 详情注明"真实上传由本机渲染报告时自动执行"（与 WorkClaw 本地补丁行为一致，上游采纳）
- 设备端归档时发 running（进行中动画）的行为保持不变：测试运行期间转圈、进程结束落定对勾

## [1.10.19] - 2026-11-26

### Changed
- 1.10.18 补传：GitHub 端 boxbench_live.py 首次上传失败、Gitee 端 CHANGELOG 上传失败，本轮强制同步补齐（内容同 1.10.18）

## [1.10.20] - 2026-11-27

### Added
- **内置浏览器 404 诊断规则（CDP 中继型缺陷，WorkClaw 实测）**：部分 Agent 内置浏览器经 CDP relay 连接，访问看板 `127.0.0.1` URL 时在**中继侧**解析——中继机器上没有看板服务，返回的是中继自己的 404，与看板服务无关
  - SKILL.md 硬性规则 #9 与第 2 步新增降级路径：curl 同 URL 自证 200（服务正常）→ 不要重试内置浏览器（重试必败）→ 立即改系统浏览器弹出或 URL 原文发用户手动打开
  - RUNBOOK 异常对照表新增 A-11：症状/根因/三方对照实验（curl 直连 200、错 token 404、同机静态服务 200）/四步处理
  - 看板保留期已过 → `--replay boxbench_live_*.jsonl` 重演，无需重跑测试
