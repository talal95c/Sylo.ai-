"""Coarse Ghanaian institution geography owned by the risk package."""

from __future__ import annotations

from dataclasses import dataclass


GH_REGIONS = (
    "Ashanti",
    "Bono",
    "Central",
    "Eastern",
    "Greater Accra",
    "Northern",
    "Upper East",
    "Volta",
    "Western",
    "Savannah",
)
BORDER_REGIONS = frozenset({"Upper East", "Volta"})
_REGION_CODES = {f"{index:02d}": region for index, region in enumerate(GH_REGIONS)}

GH_REGION_CENTROIDS = {
    "Ashanti": (6.7, -1.6),
    "Bono": (7.8, -2.4),
    "Central": (5.6, -1.4),
    "Eastern": (6.2, -0.5),
    "Greater Accra": (5.7, -0.2),
    "Northern": (9.2, -0.8),
    "Upper East": (10.8, -0.8),
    "Volta": (6.6, 0.6),
    "Western": (5.0, -2.2),
    "Savannah": (8.2, -1.9),
}

INSTITUTION_REGION = {
    "bank_gh": "Ashanti",
    "supplier_ssx": "Northern",
    "mule_bank": "Volta",
}


@dataclass(frozen=True)
class Geography:
    region: str | None
    border: bool
    known: bool


def institution_geography(institution_id: str | None) -> Geography:
    if institution_id in INSTITUTION_REGION:
        region = INSTITUTION_REGION[institution_id]
        return Geography(region, region in BORDER_REGIONS, True)
    if institution_id:
        prefix, _, code = institution_id.rpartition("-")
        if prefix in {"gh-bank", "gh-supplier"} and code in _REGION_CODES:
            region = _REGION_CODES[code]
            return Geography(region, region in BORDER_REGIONS, True)
    return Geography(None, True, False)


def geography_features(bank_institution_id: str | None, supplier_institution_id: str | None) -> tuple[float, float]:
    bank = institution_geography(bank_institution_id)
    supplier = institution_geography(supplier_institution_id)
    border = bank.border or not bank.known
    mismatch = not bank.known or not supplier.known or bank.region != supplier.region
    return float(border), float(mismatch)
