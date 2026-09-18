# Figure captions (English)

## Figure 1. Current study design and evidence boundaries
Three independent chains—active ICMP measurement, verified power-event/window definitions, and topology evidence—meet only at association/discrimination. Availability is ICMP reachability, not physical uptime; ITDK `T=0` is no observed transit evidence, not confirmed non-infrastructure; and a power window is not IP-level physical power loss.

## Figure 2. Timeline of Verified Power- and War-Related Events
Frozen event marker positions are retained; the legend distinguishes a circle (power-related event) from a cross (war-related event). Event records have different time precision and do not share a common 2-hour measurement cycle; this cannot be interpreted as absence of real-world mechanism overlap.

## Figure 3. Descriptive Association Between Power-Window Availability and Observed ITDK Transit Evidence
Frozen V2 Freedman–Diaconis descriptive bins, points, and Wilson 95% intervals are shown. Bins are descriptive only; the primary association model uses continuous availability. The figure does not establish causality or infrastructure ground truth.

## Figure 4. Observed ITDK Transit Evidence: Normal vs Power-Window Availability
The panels share axes and point/Wilson-interval encoding. Normal-period availability is a descriptive comparison using the inherited normal summary and is not a strict raw-probe matched case-crossover outcome.

## Figure 5. ROC Curves for Power and Normal Availability
Frozen ROC artifacts are shown. Power AUC is approximately 0.873692 and Normal AUC approximately 0.868867; the figure does not support an inferential Power-over-Normal claim.

## Figure 6. Precision–Recall Curves for Power and Normal Availability
Panel A shows the full range and Panel B enlarges precision ≤0.05. X is Recall, Y is Precision, curves use the frozen `precision_recall_curve` ordering and step rendering, and the dashed line is positive prevalence. Values are Average Precision (AP), not PR-AUC; class imbalance limits interpretation.

## Figure 7. Robustness Across ITDK Temporal Snapshots
Frozen Power AUC and intervals for 2024-02, 2024-08, and 2025-03 are shown. Uncertainty is `/24` cluster bootstrap, B=200; snapshots are not independent datasets.

## Supplement S1. ITDK Router Evidence
Uses frozen master `itdk_202408_router` and the exact Figure 3 display bins, with Wilson 95% intervals and no connecting line. Router membership is secondary topology evidence, not infrastructure ground truth.

## Supplement S2. Own Traceroute Intermediate-Hop Evidence
Uses frozen master `own_traceroute_intermediate` and the exact Figure 3 display bins, with Wilson 95% intervals and no connecting line. This is secondary validation and is not fully independent of the active-measurement environment.

## Supplement S3. Cross-event Endpoint-loss Rank Repeatability
Uses an existing frozen `h1_repeatability.csv` when available. The event-pair heatmap and dot plot are descriptive; missing/non-estimable pairs remain blank/NA, and no cutoff, significance ranking, or H1 recomputation is introduced.
