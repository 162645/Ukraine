# Own-traceroute intermediate-hop evidence rebuild

## Scope and non-mutation rule

This experiment reads the authoritative ClickHouse table `active_measurement.UKRAINE__quarter-traceroute_AWS_frankfurt_2024-06-22` and the frozen manuscript master. It does not modify the frozen master, fit a model, select a threshold, or generate/replace a figure.

An observed intermediate-hop IP is a syntactically valid public IPv4 address returned in `hop_path`, strictly before the final recorded path element, and unequal to `dst_ip`. `*` is ignored. Missing hops are not imputed and adjacency across missing hops is never inferred. Ukraine mapping means membership in the frozen Ukraine target registry; it is not a new geolocation claim.

## Three manuscript questions

1. **How many network-side IPs does own traceroute add inside the main sample?** 7,430 of 1,170,227 frozen main-sample IPs (0.634920%) were directly observed as public pre-terminal traceroute hops.
2. **How many are not covered by CAIDA 2024-08 transit evidence?** 3,980 are own-traceroute-only; 3,450 are observed by both; 508 are CAIDA-only; the union is 7,938 IPs. `P(own | CAIDA)` is 87.165235%; `P(CAIDA | own)` is 46.433378%.
3. **Does the existing descriptive S2 relationship remain?** The fixed-bin endpoint direction is retained. The complete result uses the exact frozen Freedman-Diaconis availability bins and Wilson intervals in `OWN_TRACEROUTE_S2_DESCRIPTIVE_BINS.csv`; no new model or threshold is introduced.

## Scale

- All unique public observed intermediate-hop IPs: **50,825**
- Ukraine-mapped under the frozen target registry: **16,918**
- Intersecting the frozen 1,170,227-IP main sample: **7,430**

## Frozen-label identity

The direct ClickHouse set differs from the frozen field. The frozen master was not modified; all differing IPs and reasons are listed.

- Frozen positives: 10,697
- Rebuilt positives: 7,430
- Frozen-only: 3,267
- Rebuilt-only: 0

The old monthly CSV sets are compared independently in `LEGACY_MONTHLY_SET_IDENTITY_QA.csv`; every differing address is retained in `LEGACY_MONTHLY_SET_DIFFERENCES.csv`.

## Interpretation boundary

These are IPs actually observed in intermediate positions on own traceroute paths, not infrastructure ground truth. CAIDA remains the external primary topology source; own traceroute is a measurement-period- and vantage-aligned secondary source that is not fully independent of the active-measurement environment.
