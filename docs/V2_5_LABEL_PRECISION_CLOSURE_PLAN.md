# v2.5 标签精度实验闭环（缓存优先）

## 当前判定

v2.4 的负向结论仍然成立，但新增官方材料足以启动一个预先冻结的
`label-only reanalysis`。第一阶段不得修改 B2 算法、阈值、模型或评价指标。

本地审计确认：

- 测量周期和实验计算使用 UTC，不受运行机器的 `Asia/Shanghai` 时区影响。
- 包内 93 组“本地时间列—UTC 列”全部通过 `Europe/Kyiv` 转换一致性校验；
  2024 年 7–8 月自动使用 UTC+3，12 月自动使用 UTC+2。该结果只证明两个
  派生字段内部自洽，不是 93 次独立的来源真实性核验，也不能单独证明原网页
  记录的停电时间正确。来源时间必须再与原始网页、图片、文件元数据逐条核对。
- 2024-08-19 的最终全国计划应为 18:00–21:30，而不是 17:00–21:00。
  但在现有 2 小时周期和 50% 重叠规则下，两者选中的缓存周期相同，故全国
  时间修正没有改变任何一行验证标签，也没有改变 AUPRC。
- 冻结映射只有 IP→Admin1/ASN，没有 IP→城市→地址→队列/馈线。城市或州
  定位不能被提升为街道级断电真值。当前诚实上限是 Admin1/DSO 概率暴露。
- 可以按 Admin1 筛选“地区级候选电敏感 IP”：先把 IP 限定在目标州，再用该州
  的最终执行/取消窗口计算 pN、pP 和 S_lo。当前官方更新覆盖 15 个有冻结映射
  的 Admin1，合计约 152 万个 regional-eligible IP。只有 full-oblast 的确定性
  激活/取消能直接作为州级 0/1；特定 queue 的更新在没有 IP→queue 键时必须标
  为概率暴露或 unknown，不能把整个州的 IP 都当作被断电。
- B2 的 q0 平均 deficit 从 7 月 28 日的 0.021 上升至 8 月 19/20/21 的
  0.262/0.282/0.346，再到 12 月 9 日的 0.395；B1 对应为
  0.010/0.071/0.057/0.103/0.162。这支持“B2 后期正常期假阳性/端点漂移”诊断。

## 分层重分析

按以下顺序运行，每层都保留独立结果，不允许用后层结果反调前层阈值：

1. `original_v24`：原冻结结果。
2. `national_final_corrected`：官方最终全国分段；本地缓存可完成。
3. `oblast_final_updates`：Admin1×周期状态。全州取消可确定标 0；只涉及特定
   队列的激活/取消，在没有队列成员键时只能作为暴露概率或 unknown，不能
   把全州 IP 硬标成 0/1。
4. `queue_refined_where_supported`：仅对具有可靠队列映射的端点运行。当前为
   blocked-by-data，不得用城市猜测队列。
5. `queue_refined_plus_nonGPV_mask`：叠加 Ivano-Frankivsk 计划检修/事故档案，
   屏蔽 GPV 之外的停电混杂。

每层固定报告 B1/B2 AUPRC、ΔAUPRC、事件簇 bootstrap CI、置换 p、q0 假阳性、
事件异质性，以及有效 Admin1/IP/周期覆盖率。12 月 9 日单独作为冬季制度层，
不得与夏季事件交换合并。

## Oblast-specific B2 主设计

全国 `B2_Ukraine` 降为对照结果；新主设计在每个州内部构造
`B1_region` 和 `B2_region`。`B2_region` 必须同时满足地区长期正常期稳定、至少
两个独立训练事件中重复 `S_lo>0`、正方向事件比例门槛和 median S>0。单次极大
下降不能入选。达到至少 3 个训练事件和 1 个完全留出事件后才允许确认性的
leave-one-event-out；各州 ΔAUPRC 最后做 meta-analysis，不先混合 IP。

V2 容量门控结果是：15 个州有映射和某种官方更新；Volyn 的六个夏季核心日期
都有州级官方窗口，因此可以执行 3-train + 1-holdout 的区域计划弱监督 LOO。
这不等于六次实际断电确认。Khmelnytskyi 的六个 published-schedule 日期仍须明确
标记 `execution_truth=0`，并与最终全国调度取交集、应用冲突掩码；Lviv 只作
8 月 20 日单事件验证，不进入重复性主门。

正式运行还增加数据库时间戳硬门：从 ClickHouse 同一行读取 `measure_time` 与
Unix epoch，结合服务器时区和列类型推断客户端时间显示语义，不使用停电标签。
只有推断结果唯一为 UTC 才允许继续；Kyiv、Shanghai 或 ambiguous 均立即终止。

一条指令运行完整 v2.5（原论文核心链条保留，另加区域校准阶段）：

```bash
./run_v25_regional.sh paper_v25_regional_01
```

中断后继续：

```bash
./run_v25_regional.sh paper_v25_regional_01 --resume
```

## 缓存与 ClickHouse 边界

无需连接 ClickHouse：

- 官方包 SHA256、来源层级和时区审计；
- 全国最终标签在已缓存验证周期上的重标；
- Admin1 官方证据覆盖率和可识别性审计；
- 已冻结 B1/B2 的 q0 假阳性漂移；
- 已缓存事件面板覆盖的聚合敏感性分析。

必须连接 ClickHouse 并先落本地 Parquet 缓存：

- 分别以 7 月 7 日、7 月 20 日（以及新增独立训练事件）构造逐事件 IP 得分；
- 保存每个事件的 `dst_ip,prefix24,target_admin1,pN,pP,S,S_lo,in_B1,in_B2`，用于
  Jaccard、单向 retention、连续得分秩相关和 clean-q0 survival；
- 新标签需要的周期不在 `paper_v24_real_01` 已查询响应集合中时，补拉这些周期的
  逐 IP 响应计数；
- 只有上游数据库确实存在比 Admin1 更可靠的城市/队列映射键时，才拉取该键并
  开启城市×队列敏感性。若库中仍只有 Admin1，连接数据库也无法制造地址真值。

数据库阶段必须是只读、按 `/24` 分批、查询一次写 Parquet，随后所有统计只读
缓存。缓存文件需同时写入查询 SQL 哈希、源表、时间范围、cycle IDs、生成时间、
行数和 SHA256；禁止每次统计重连数据库。

## 运行入口

```bash
cd ukraine_resilience_experiment_v2_4
python3 scripts/run_label_precision_audit.py --run-id paper_v24_real_01
```

输出位于 `analysis_outputs/v25_label_precision_audit/`。当前机器若未安装 pytest，
可以运行脚本和 `py_compile`；完整测试环境应运行：

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_label_precision.py tests/test_calibration.py
```

## 对新材料中 ChatGPT 判断的核验

“标签粒度不足、B2 选择性拟合、独立事件少，比 IP 数少更关键”与冻结结果一致；
但其中“官方最终时间已经基本正确”的表述需要修正：8 月 19 日确有最终时间错误，
12 月 9 日也不能视为统一全国暴露。更准确的说法是：全国调度时间多数可核验，
但它本来就不是 IP 实际失电标签，并且部分日期存在会改变地区解释的日内修订。

新增官方包能证明 DSO 计划、取消、队列变更和制度断点存在；它不能证明某个 IP
实际失电。Khmelnytskyi 图片是 published schedule，包中 `execution_truth=0` 的处理
是正确的。地址级 PDF/XLSX 也不能在缺少可靠 IP→地址/feed 映射时直接连接到 IP。
