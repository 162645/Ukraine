# v2.4 formal-run decision

Do not start the one-shot formal run until `./scripts/run_paper.sh --check` passes.
The direction remains aligned with the paper: scheduled-outage calibration → frozen sensors →
held-out attacks → ASN×Admin1 repeatability/prediction → recovery debt → quality-admissible
AS/ASGeo adaptation.

## Integrated from the supplied v2.4.2 package

- restartable ERA5-Land download and hashed Admin1×2-hour aggregation;
- negative-control weather residualization, heat strata and August-cluster exclusion;
- exact 24 July operator falsification as pipeline stage `expG`;
- public-byte snapshots, Telegram JSON ingestion and evidence verification;
- `statsmodels==0.14.6` and a formal supervision audit.

## Corrections made during integration

- Zaporizhzhia message `966` is not the 24 July update; the exact post is `974`;
- the supplied weather builder used a different schema and omitted the required anomaly;
  the integrated version records geometry/raw hashes and produces `temperature_anomaly_c`;
- wholesale extraction was rejected because it would remove the segmented national schedule
  and regress newer closure fixes.

The 24 July contrast never trains B2 and Queue 1 is not full-oblast or IP-level outage truth.
The 30 August contrast remains attack-recovery-confounded. The proposed 11 December event is
not promoted to an independent clean validation event without complete operator evidence.

## Remaining blockers

1. Install the frozen environment; `statsmodels` is missing in the current interpreter.
2. Freeze a Ukraine Admin1 GeoJSON and generate `data_derived/weather_admin1_2h.parquet`.
3. Complete critical Volyn/weather public snapshots.
4. Export Zaporizhzhyaoblenergo in Telegram Desktop and ingest message 974.
5. Pass the formal preflight and ClickHouse capacity checks.

If B2 passes independent holdouts and weather robustness, freeze B2 before attacks. If it
fails, freeze B1 and report a valid negative calibration. A positive full-chain claim also
requires estimable operator falsification, attack inference, prediction/repeatability,
recovery and path-quality gates. Failed estimability is incomplete evidence, not a null.
