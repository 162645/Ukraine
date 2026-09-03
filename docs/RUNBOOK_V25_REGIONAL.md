# v2.5 区域停电校准一键运行手册

## 研究问题保持不变

论文仍回答：互联网主动测量能否校准出对供电冲击具有可重复响应的端点，并用于
刻画后续能源冲击下的网络韧性。v2.5 只修复 treatment assignment：全国 B2 保留
为原始对照，新主校准在州内比较 `B2_region` 与 `B1_region`，不会以地区化结果
事后更换原论文阈值、攻击事件、结局指标或模型。

## 单命令

配置好只读 ClickHouse 连接后：

```bash
cd /Users/bytedance/WorkPlace/code_file/TTADK/else/ukraine/ukraine_resilience_experiment_v2_4
./run_v25_regional.sh paper_v25_regional_01
```

`run_v25_regional.sh` 直接委托给 v2.4 正式入口 `scripts/run_paper.sh`，因此沿用
v2.4 的 `.env.local`/`UR_CH_*` 加载、连通性检查、失败重试和 Python 运行环境。
同一条命令也用于中断恢复：脚本默认启用安全续跑；首次运行会创建 run，之后会跳过
同一 run-id 下已经完成的阶段，并复用各阶段校验通过的本地缓存。不要更换 run-id，
否则会创建隔离的新实验目录。

执行顺序优先完成数据库交互：`preflight → audit → panels → expA → expRegional →
sensorPanels`，之后在本地生成 `features` 和 `expB` 匹配。`expE` 是唯一较晚的
ClickHouse 阶段，因为其查询前缀依赖这两个本地产物；依赖满足后立即执行，剩余
`expG/expF/expD/expC/figures/validate` 均放在后面。

连接参数继续使用 `config/experiment_v2.local.yaml` 或 `UR_CH_*` 环境变量。数据库
客户端保持 readonly；地区查询按 `/24` 分批，并把逐事件 IP 得分与稀疏响应写入
`runs/<run-id>/data_derived/regional_calibration/`。恢复运行会复用这些缓存。

## 第一数据库动作：时间戳硬门

程序在自动冻结映射和任何实验查询之前执行：

1. 从 ping 表首尾抽取 `measure_time`；
2. 同行计算 Unix microsecond epoch；
3.读取 ClickHouse `timezone()` 和 `system.columns` 列类型；
4. 分别按 UTC、ClickHouse server zone、Europe/Kyiv、Asia/Shanghai 解释客户端返回值；
5. 只有唯一匹配 epoch 的语义为 UTC 时继续。

该检测不使用任何停电计划或事件标签。失败会直接退出，并在成功时生成
`timestamp_contract_bootstrap.json`；preflight 阶段会再复核一次。北京时间仅是运行
机器时区，不能改变测量周期或事件窗口。

## 地区标签规则

证据优先级固定为：

`同日 DSO 命令 > 最终 DSO 更新 > DSO 公布队列表∩最终 Ukrenergo 调度 > 州级窗口 > 全国调度`

- Volyn：六个夏季核心日期均有州级官方窗口，可运行 LOO；19–21 Aug 叠加日内修订。
- Khmelnytskyi：六日公布队列表与最终全国调度取交集，冲突区间硬屏蔽；仍标记为
  published plan，不写成实际断电。
- Lviv：8/20 单事件验证，不进入重复性主门。
- Ivano-Frankivsk、Zaporizhzhia、Ternopil：仅作混杂、成员漂移和数据缺口敏感性。

IP 只有 Admin1 定位时，输出含义是“该州计划停电环境下的重复可达性响应”，不是
IP 实际失电真值，也不会从城市猜测队列或地址。

## 地区 B2 与验证

每次独立地区事件分别保存 `pN,pP,S,S_lo,in_B1`。LOO 的训练端要求：

- IP 出现在全部训练事件；
- 所有训练事件正常期均满足 B1 稳定性；
- 至少 3 个训练事件；
- 至少 2/3 事件 `S_lo>0`；
- median S > 0。

留出事件完全不参与成员选择。地区内报告 B1/B2 AUPRC 和 ΔAUPRC；最后按州等权
做分层 bootstrap，防止大州因 IP 多而支配结果。主边界缓冲为 ±30 分钟，±60 分钟
独立重跑并单列结果。

## 关键输出

- `results/tables/preflight_report.json`
- `results/tables/regional_calibration_cycle_audit.csv`
- `results/tables/regional_calibration_loo.csv`
- `results/tables/regional_b2_membership_stability.csv`
- `results/tables/regional_calibration_meta_summary.csv`
- `results/tables/regional_calibration_provenance.json`
- `data_derived/regional_calibration/ip_sensor_scores_by_training_event/*.parquet`
- `data_derived/regional_calibration/responses_by_event/*.parquet`
- `data_derived/regional_calibration/regional_sensor_membership.parquet`

若地区主结果仍不优于 B1，论文核心结论会被加强：即使将监督从全国细化到州级，
互联网端点仍未形成可重复的供电敏感传感器。若 Volyn 等地区明显改善，则结论应
限定为“全国标签稀释了地区性信号”，而不是宣称已获得 IP 级供电真值。
