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
