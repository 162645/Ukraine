# Latest real-run diagnosis and v2.3 decision

## Observed facts from run `20260802T101138Z`

- Preflight passed, including schema, full-scan denominator declaration, and frozen mapping checksum.
- Nominal expected cycles: 2,940.
- The old audit marked 2,208 cycles complete (75.10% of the nominal window).
- Positive Ping-response rows were observed from 2024-06-22 08:00 UTC to 2025-01-09 14:00 UTC.
- Under the old response-row-based rule, 2,208 / 2,416 cycles inside that span were marked complete (91.39%).
- Valid ASN mapping: 95.93%.
- Old valid-Admin1 ratio: 54.67%.
- Old prefix exact-modal mapping pass share: 55.05%.

The 91.39% value is a diagnosis of the old output, not the v2.3 acquisition-completeness result. v2.3 must recompute support from `import_files.import_status`, `has_ping`, and `has_trace`.

## What the audit stop actually revealed

The stop did not show that the dataset is unusable. It showed that the old gates mixed three different quantities:

1. **Acquisition quality** — whether the full-scan artifact was imported successfully.
2. **Network response volume** — how many targets responded, which is the scientific outcome.
3. **Geographic resolution** — whether a target can support national or regional inference.

Because the Ping table stores only responses, a missing destination row in an import-complete full-scan cycle is a non-response. Low or zero aggregate response volume must therefore remain in the outcome data and must not be discarded as a quality failure. Only a missing/failed Ping acquisition is an acquisition gap.

Country-only geography such as `乌克兰` is sufficient for national calibration and national attack analysis, but not for Admin1 treatment assignment. A mixed `/24` must not be forced into one ASN/Admin1 tuple; endpoint-level mapping and `/24×ASN×Admin1` split units are required.

## Event chain supported by the previous response span

Expected to be available after the v2.3 import-ledger audit:

- Training scheduled outage: 2024-08-19.
- Held-out scheduled outage: 2024-12-09.
- Contextual confounded planned-outage window: 2024-06-24; excluded from sensor training and the main calibration gate because it overlaps the 22 June attack-recovery period.
- Main attacks: 2024-08-26, 2024-09-17, 2024-11-17, 2024-11-28.
- Stress tests: 2024-12-13, 2024-12-25.

Expected unavailable from the previous response span:

- 2024-06-10 and 2024-06-21.
- 2025-01-15.

The new `event_data_availability.csv` also checks endpoint-mapping coverage in each treated Admin1, so later regional experiments cannot silently produce empty treatment groups.

## Next decision sequence

1. Re-run preflight and audit with a new immutable run ID.
2. Confirm acquisition support and event availability from `quality_report.json` and `event_data_availability.csv`.
3. Train endpoint sensitivity on 2024-08-19 using only pre-19-August normal cycles.
4. Validate without refitting on 2024-12-09.
5. Keep 2024-06-24 as a contextual/confounded robustness window only.
6. Freeze B2 if it beats B1 under the operational holdout gate; otherwise freeze B1.
7. Treat a positive B2 result as **provisional**, because only one independent clean held-out planned outage is currently registered. A second clean held-out planned outage is required for a publication-grade positive calibration claim.
8. Apply the frozen method to 8/26, 9/17, 11/17, and 11/28.
9. Build ASN×Admin1 repeatability and prediction only from region-eligible endpoint groups.
10. Run recovery-debt and AS/ASGeo adaptation as conditional extensions after the main reachability chain is valid.
