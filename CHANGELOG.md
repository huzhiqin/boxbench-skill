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
