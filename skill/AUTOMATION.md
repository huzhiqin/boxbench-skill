# AUTOMATION — 定时回归跑分（可选能力）

> 目的：在管的多台盒子定期自动回归，趋势对比，防"引擎升级/模型更新后性能悄悄劣化没人发现"。
> 这是 BoxBench 的第四种使用形态（手动 / Agent 编排 / CI 之外的**定时任务**）。

## 方案 A：WorkBuddy 定时任务（推荐，零脚本）

对 WorkBuddy 说一句话即可创建，例如：

> 每周一早上 9 点，对 192.168.x.x 这台 ZYSJ-E300K（SSH 账号 dev，密码见密码库）跑一次 boxbench 回归：SSH 上设备执行 `bash ~/boxbench.sh`，取回 JSON，用 boxbench-skill 渲染报告，与上次结果对比解码速度/加载/并发/通过率，输出趋势简报。设备不可达时在简报里标注"跳过本次"，不要重试轰炸。

要点：
- 提示词里必须**自包含**设备信息（IP/账号/模型名），定时任务看不到当次对话
- 让任务自己处理失败（标注跳过），避免失败重试风暴
- 报告统一落 `reports/回归/` 目录，文件名带日期，自然形成时间序列

## 方案 B：cron / 任务计划（无 AI 工具环境）

设备端 cron（Linux 盒子自带 cron 时）：

```cron
# 每周一 09:00 自动跑分, 结果留设备上, 周报时统一取回
0 9 * * 1 cd ~ && bash boxbench.sh >> boxbench_cron.log 2>&1
```

执行机 cron（负责取回+渲染+趋势）：

```bash
#!/bin/bash
# weekly_regression.sh — 每周取回各盒子结果并渲染
set -u
HOSTS="dev@192.168.x.x dev@192.168.x.y"     # 在管盒子清单
for h in $HOSTS; do
  name=$(ssh "$h" hostname)
  scp "$h:~/boxbench_results_*.json" "results/${name}_$(date +%Y%m%d).json" || echo "SKIP $h 不可达"
done
for f in results/*_$(date +%Y%m%d).json; do
  [ -e "$f" ] || continue
  python3 scripts/render_report.py "$f" "reports/$(basename "${f%.json}").html" --device "$(basename "${f%%_*}_*")"
done
```

## 趋势对比口径（简报里写什么）

只比四个硬指标，全部来自 JSON，禁止估算：
1. **C2 解码速度**（usage 口径 tok/s）— 环比变化 >10% 需要写原因
2. **C1 加载耗时** — 变慢说明引擎/磁盘状态变化
3. **C7 并发 4 路通过数** — 从 4/4 掉到 2/4 即劣化
4. **C12 之外的通过率** — 任何新增 ❌ 项单独列出

## 注意

- 回归测试会占满设备算力几分钟，**避开业务高峰**（夜间/周末）
- 多台盒子串行跑，不要并行（网络与执行机都吃不消）
- 趋势数据同样走经验库回写流程，长期形成"设备健康史"
