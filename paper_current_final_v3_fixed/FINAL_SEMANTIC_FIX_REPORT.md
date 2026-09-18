# FINAL_SEMANTIC_FIX_REPORT

1. **Figure 1**：将 ITDK、路由器/接口和自有 traceroute 改为三路并列拓扑证据，汇入多源拓扑综合验证；删除证据源之间的串行箭头，不表达因果链。
2. **Figure 2 图例**：核对冻结 V3 SVG 实际对象：绿色圆点（`#2ca02c`）为电力相关事件，红色叉号（`#d62728`）为战争相关事件；图例使用完全相同的 marker/color/label，并写入自动 QA。
3. **Figure 2 主分析事件子集**：从批准的冻结 artifact 无法无歧义恢复登记行到主分析事件的映射（NOT RECOVERABLE）。因此不推断高亮子集，caption 明确这是 registry/temporal coverage，后续 IP 分析还受有效测量、机会和事件匹配条件限制。
4. **Table 2 GEE 尺度**：β=3.160 单独标为 log-odds；OR=23.571 单独列出；95% CI 明确为 OR scale `[19.332, 28.740]`；不生成 β CI。
5. **Table 1/2 格式**：移除科学计数法、过多小数和空值机器表示；使用千位分隔、3 位有效小数、`—`，并区分 target IP universe（NOT VERIFIED）与 frozen master analysis rows（1,170,227）。
6. **失败模型**：Period × ITDK interaction 从 Main Results 移至 `Table_2_analysis_status` 和 QA/status audit，不解读为无效应。
7. **冻结估计保持不变**：AUC、AP、ITDK prevalence、GEE β/OR/OR CI 和 2024-02/08、2025-03 release AUC 均通过 `FROZEN_VALUE_IDENTITY_V2.csv` identity check。
8. **Figure 6 PR 方向**：保持 X=Recall、Y=Precision，使用冻结 `precision_recall_curve` 返回顺序和阶梯显示；AP 保持冻结值。
9. **Figure 7 bootstrap**：保持 `/24` cluster bootstrap, `B=200`，仅展示冻结快照结果。
10. **Legend semantic QA**：新增 `FIGURE2_LEGEND_SEMANTIC_QA.csv`，逐语言核对 actual-vs-legend marker/color/label。
11. **仍无法验证的问题**：Figure 2 登记事件到主分析子集的逐行映射，以及独立 target-universe artifact，均标记 NOT RECOVERABLE/NOT VERIFIED，未进行推断。

**FINAL STATUS: READY_FOR_MANUSCRIPT_WRITING**
