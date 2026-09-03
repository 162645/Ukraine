"""Canonical country/Admin1 handling for target and traceroute geography.

Target geography is read only from the frozen IP mapping table.  ASGeo path
text, city names, and ISP domains are never used to assign a target region.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
PUNCT_SPACE = re.compile(r"[\s\u00a0]+")


def _norm(s: object) -> str:
    if s is None:
        return ""
    x = unicodedata.normalize("NFKC", str(s))
    x = ZERO_WIDTH.sub("", x).strip()
    x = PUNCT_SPACE.sub(" ", x)
    # Harmonise common punctuation variants without fuzzy geographic matching.
    x = x.replace("’", "'").replace("`", "'")
    return x.casefold()


class Admin1Canonicalizer:
    COUNTRY_ONLY_UA = "COUNTRY_ONLY_UA"
    UNKNOWN = "UNKNOWN_ADMIN1"
    UNMAPPED_UA = "UNMAPPED_UA_ADMIN1"

    def __init__(self, alias_csv: Path, unknown_labels: list[str], country_aliases: list[str],
                 country_only_labels: list[str] | None = None):
        aliases = pd.read_csv(alias_csv, dtype=str, keep_default_na=False)
        self.map = {(_norm(r.country), _norm(r.alias)): r.canonical_admin1
                    for r in aliases.itertuples(index=False)}
        self.ua_country_aliases = {_norm(x) for x in country_aliases}
        self.unknown = {_norm(x) for x in unknown_labels}
        self.country_only = {_norm(x) for x in (country_only_labels or country_aliases)}
        self.valid_ua = set(aliases.loc[aliases["country"].eq("Ukraine"), "canonical_admin1"])

    def canonical_country(self, country: object) -> str:
        n = _norm(country)
        if not n or n in self.unknown:
            return "UNKNOWN"
        if n in self.ua_country_aliases:
            return "Ukraine"
        return str(country).strip()

    def canonical_admin1(self, country: object, admin1: object) -> str:
        c = self.canonical_country(country)
        a = _norm(admin1)
        if not a or a in self.unknown:
            return self.UNKNOWN
        # Some mapping providers return only the country name in geo_region.
        # Preserve it as country-only coverage; never reinterpret it as a region.
        if c == "Ukraine" and a in self.country_only:
            return self.COUNTRY_ONLY_UA
        hit = self.map.get((_norm(c), a))
        if hit:
            return hit
        if c != "Ukraine":
            return str(admin1).strip()
        return self.UNMAPPED_UA

    def canonicalize_frame(self, df: pd.DataFrame, country_col: str, admin1_col: str,
                           out_country: str = "target_country",
                           out_admin1: str = "target_admin1") -> pd.DataFrame:
        out = df.copy()
        out[out_country] = out[country_col].map(self.canonical_country)
        out[out_admin1] = [self.canonical_admin1(c, a)
                           for c, a in zip(out[country_col], out[admin1_col])]
        return out

    def valid_target(self, country: object, admin1: object) -> bool:
        return self.canonical_country(country) == "Ukraine" and str(admin1) in self.valid_ua

    def national_eligible(self, country: object, asn: object) -> bool:
        try:
            good_asn = int(asn) > 0
        except Exception:
            good_asn = False
        return self.canonical_country(country) == "Ukraine" and good_asn

    def regional_eligible(self, country: object, admin1: object, asn: object) -> bool:
        return self.national_eligible(country, asn) and str(admin1) in self.valid_ua
