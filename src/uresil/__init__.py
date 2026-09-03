"""乌克兰能源冲击与互联网韧性实验代码包。

Ukraine Energy Shock & Internet Resilience — experiment code package.

模块概览:
  config   : 冻结配置加载 (experiment_v2.yaml + event_registry + mapping_manifest)
  db       : 内存感知的 ClickHouse 客户端 (流式 / 分块 / 进度条 / 服务端内存限制)
  progress : 统一进度条与日志
  audit    : P1 数据质量审计 + cycle_quality
  baseline : IP 基线响应概率 q(i,h) 与 /24 预期响应
  panels   : prefix_cycle_panel / group_cycle_panel 构建
  events   : 事件注册表、窗口、周期标签
  features : 事件特征 (immediate_drop / max_deficit / AUC / T90 ...)
  stats    : 块自助法、生存分析、FDR 等推断工具
  exp_a_calibration      : 实验A 计划停电弱监督校准
  exp_b_event_study      : 实验B 攻击事件影响量化 (事件研究/匹配)
  exp_c_fingerprint      : 实验C ASN×Admin1 韧性指纹与留一事件预测
  exp_d_recovery_debt    : 实验D 重复冲击与恢复债务
  exp_e_path             : 实验E 保守 AS/ASGeo 转发适应分析
  viz      : 论文级双语 (中/英) 绘图 (F1-F15)
  demo_data: 合成面板生成器,用于验证绘图管线 (非真实结果)
"""

__version__ = "2.4.0"
