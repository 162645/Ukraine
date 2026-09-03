"""Compact bilingual labels used by all publication figures."""
from __future__ import annotations

TEXT = {
"zh": {
 "time":"时间（UTC）","relative":"相对事件时间（小时）","reach":"标准化可达率",
 "effect":"处理组相对对照组的可达率差","prefix":"有效 /24 数","ci":"95% 置信区间",
 "planned":"计划停电","attack":"能源攻击","precision":"精确率","recall":"召回率",
 "auprc":"AUPRC","admin1":"一级行政区","event":"事件","auc":"可达缺口面积（小时）",
 "t90":"恢复至 90%（小时）","pred":"预测值","actual":"观测值","model":"模型",
 "variance":"方差比例","exposure":"事件前累计停电小时","survival":"尚未恢复比例",
 "path_jsd":"ASGeo 边分布 JSD","trace":"有效 Traceroute 数","phase":"阶段",
 "edge_rate":"每千条有效 Trace 的入口边次数","baseline":"基线","recovery":"恢复期",
 "quality":"数据质量","national":"全国标准化可达率","coverage":"测量覆盖",
 "unknown":"未知/AS0 比例","n_event":"留出事件数",
 "trace_reached":"Traceroute 目标到达率","geo_unknown":"Geo 未知","group":"ASN｜国家｜一级行政区",
 "event_equal_mae":"事件等权 MAE","hours_after_event":"事件后小时数",
 "external_time_offset":"内部异常起点减外部起点（小时）","spatial_jaccard":"一级行政区空间 Jaccard",
 "event_component":"事件","asn_component":"ASN","admin1_component":"一级行政区",
 "interaction_component":"ASN×一级行政区","residual_component":"残差",
 "delta_auprc":"B2 相对 B1 的 ΔAUPRC","validation_event":"留出计划停电事件","target_universe":"目标宇宙","max_deficit":"最大可达缺口",
},
"en": {
 "time":"Time (UTC)","relative":"Hours relative to event","reach":"Normalized reachability",
 "effect":"Reachability difference: treated minus control","prefix":"Eligible /24s","ci":"95% CI",
 "planned":"Scheduled outage","attack":"Energy attack","precision":"Precision","recall":"Recall",
 "auprc":"AUPRC","admin1":"First-level administrative region","event":"Event","auc":"Reachability-deficit AUC (h)",
 "t90":"Time to 90% recovery (h)","pred":"Predicted","actual":"Observed","model":"Model",
 "variance":"Fraction of variance","exposure":"Prior cumulative outage hours","survival":"Fraction not yet recovered",
 "path_jsd":"ASGeo edge-distribution JSD","trace":"Valid traceroutes","phase":"Phase",
 "edge_rate":"Ingress occurrences per 1,000 valid traces","baseline":"Baseline","recovery":"Recovery",
 "quality":"Data quality","national":"National normalized reachability","coverage":"Measurement coverage",
 "unknown":"Unknown/AS0 share","n_event":"Held-out events",
 "trace_reached":"Traceroute target-reached rate","geo_unknown":"Unknown Geo","group":"ASN | Country | Admin1",
 "event_equal_mae":"Event-equal MAE","hours_after_event":"Hours after event",
 "external_time_offset":"Internal onset minus external onset (h)","spatial_jaccard":"Admin1 spatial Jaccard",
 "event_component":"Event","asn_component":"ASN","admin1_component":"Admin1",
 "interaction_component":"ASN × Admin1","residual_component":"Residual",
 "delta_auprc":"ΔAUPRC: B2 minus B1","validation_event":"Held-out scheduled-outage event","target_universe":"Target universe","max_deficit":"Maximum reachability deficit",
}}

def L(lang: str, key: str) -> str:
    return TEXT[lang][key]
