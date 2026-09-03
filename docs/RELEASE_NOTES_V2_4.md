# Release notes v2.4

v2.4 responds to the first complete real run. That run showed that B2 did not outperform B1, all attack pretrend gates failed under a single collapsed event anchor, 28 November power and external network geographies differed, repeatability was weak, the preregistered prediction model did not beat the simple group baseline, recovery models were not estimated in the runtime environment, and only a small path subset met strict quality criteria.

The release fixes the design rather than tuning results:

- attack/outage/network time separation;
- clean-baseline pair-centered DID;
- power and external-network estimand separation;
- equivalence-based pretrend;
- target-universe counts and U2/U3 effect sensitivity;
- stronger repeatability/prediction requirements;
- dependency preflight and recovery fallback;
- path FDR;
- negative-result-aware closure;
- safer secrets handling;
- bilingual vector-first graphics and explicit CJK font resolution.
