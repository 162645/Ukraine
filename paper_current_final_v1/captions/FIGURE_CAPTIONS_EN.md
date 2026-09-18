# Figure captions (English)

## Figure 1. Current study design and evidence boundaries
This schematic shows the frozen active-measurement, verified power-window, availability, ITDK, and own-traceroute evidence paths. It defines ITDK `T=0` as no observed transit evidence, not confirmed non-infrastructure; Power window as a state-level verified outage window, not IP-level physical power loss; and availability as ICMP reachability, not physical uptime. It supports the study scope and does not establish causality.

## Figure 2. Timeline of Verified Power- and War-Related Events
Uses the frozen V3 event taxonomy and marker geometry. Event records have different time precision; `OVERLAP=0` or no common 2-hour cycle cannot be interpreted as absence of a real-world mechanism overlap. The timeline is contextual, not a claim that all war events or all power events are represented.

## Figure 3. Power-Window Availability and Observed ITDK Transit Evidence
Uses the frozen V2 master and Figure 17 descriptive bins with point estimates and Wilson 95% intervals. Bins are descriptive only; the primary association treats availability as continuous. The figure supports a positive descriptive enrichment pattern, not a causal or ground-truth infrastructure claim.

## Figure 4. Observed ITDK Transit Evidence: Normal vs Power-Window Availability
Uses the frozen V2 master and Figure 18 display bins with identical axes and point/Wilson-interval encoding. This is a descriptive comparison using the inherited normal summary, not a strict matched case-crossover outcome at newly selected control timestamps. It supports similarity of the observed association and does not isolate a power-specific effect.

## Figure 5. ROC Curves for Power and Normal Availability
Uses frozen ROC arrays/artifacts and TABLE_F07. Power AUC is approximately 0.874 and Normal AUC approximately 0.869. Curves describe discrimination of observed ITDK evidence; they do not establish that Power materially outperforms Normal or that ITDK is infrastructure ground truth.

## Figure 6. Precision–Recall Curves for Power and Normal Availability
Uses the frozen V2 master, with `precision, recall, thresholds = precision_recall_curve(...)`; X is Recall and Y is Precision. Step curves display frozen Average Precision (AP) and the positive-prevalence baseline. AP is not called PR-AUC. The plot is subject to severe class imbalance and does not prove a power-specific advantage.

## Figure 7. Robustness Across ITDK Temporal Snapshots
Uses TABLE_F10 with frozen AUC and confidence intervals for 2024-02, 2024-08, and 2025-03. Intervals are `/24` cluster bootstrap, B=200. These are temporal snapshots of the same topology source, not independent datasets; the figure tests Power AUC robustness only.

## Supplement S1. ITDK Router Evidence
Uses frozen TABLE_06 for the 2024-08 primary snapshot, with point and Wilson 95% intervals and no connecting line. This is secondary topology evidence, not a ground-truth infrastructure label.

## Supplement S2. Own Traceroute Intermediate-Hop Evidence
Uses frozen TABLE_07 with point and Wilson 95% intervals and no connecting line. Own traceroute is secondary validation and is not fully independent from the active-measurement infrastructure.
