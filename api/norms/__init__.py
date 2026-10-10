from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

API_ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = API_ROOT / "packs" / "FR-GH.yaml"
TAX_NOTICE_TEXT = (
    "No Ghanaian withholding on this goods payment; "
    "France–Ghana tax convention in force."
)
TAX_NOTICE_SOURCE = (
    "https://bofip.impots.gouv.fr/bofip/456-PGP.html/"
    "identifiant=BOI-INT-CVB-GHA-20120912"
)


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


def _account_for(order: dict[str, Any], payee_registry: dict[str, Any]) -> dict[str, Any] | None:
    account_id = order.get("creditor", {}).get("accountId")
    return next(
        (
            account
            for account in payee_registry.get("accounts", [])
            if account.get("id") == account_id
        ),
        None,
    )


def norm_r1_signal(order: Any, payee_registry: Any) -> bool:
    order_data = _plain(order)
    registry = _plain(payee_registry)
    if (
        order_data.get("purpose") != "GOODS"
        or order_data.get("creditor", {}).get("country") != "GH"
    ):
        return False
    account = _account_for(order_data, registry)
    return not bool(
        account
        and account.get("nominatedForExports")
        and order_data.get("documents", {}).get("locRef")
    )


def _load_pack() -> dict[str, Any]:
    with PACK_PATH.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def evaluate(order: Any, routes: Any, payee_registry: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    order_data = _plain(order)
    registry = _plain(payee_registry)
    if isinstance(routes, dict):
        route_items = list(routes.values())
    else:
        route_items = list(routes)
    normalized_routes = []
    for item in route_items:
        route = _plain(item)
        if isinstance(route, str):
            route = {"id": route}
        normalized_routes.append(route)

    account = _account_for(order_data, registry)
    nominated_and_documented = bool(
        account
        and account.get("nominatedForExports")
        and order_data.get("documents", {}).get("locRef")
    )
    pack = _load_pack()
    norm_checks: list[dict[str, Any]] = []

    for route in normalized_routes:
        route_id = route.get("id") or route.get("routeId")
        for rule in pack["rules"]:
            applies = rule["applies_to"]
            if route_id not in applies["routes"] or order_data["purpose"] not in applies["purpose"]:
                continue

            result = rule["result"]
            if rule["id"] == "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK":
                if order_data["purpose"] == "GOODS":
                    if route_id == "R4":
                        result = "FAIL"
                    elif nominated_and_documented:
                        result = "PASS"
                    elif (
                        route_id == "R3"
                        and pack["flags"]["allowVaspPathForExportProceeds"]
                        and route.get("licensedVasp", True)
                    ):
                        result = "PASS"
                    elif route_id == "R1" and route.get("conditionalSettlement") == "FIAT_HOLD":
                        result = "PASS"
                    elif not order_data.get("documents", {}).get("locRef"):
                        result = "NEEDS_DOCUMENT"
                    else:
                        result = "FAIL"
            elif rule["id"] == "GH_VASP_LICENSED":
                result = "PASS" if route.get("licensedVasp", route_id == "R3") else "FAIL"
            elif rule["id"] == "GH_WALLET_DAILY_CAP":
                result = "NEEDS_DOCUMENT" if order_data["amount"]["currency"] != "GHS" else "PASS"
            elif rule["id"] == "SANCTIONS_SCREEN":
                ctx = order_data.get("riskContext", {})
                result = "FAIL" if ctx.get("sanctions_hit") else "PASS"

            norm_checks.append(
                {
                    "routeId": route_id,
                    "ruleId": rule["id"],
                    "result": result,
                    "legalRef": rule["legalRef"],
                }
            )

    tax_notices: list[dict[str, str]] = []
    if (
        order_data["purpose"] == "GOODS"
        and order_data.get("debtor", {}).get("country") == "FR"
        and order_data.get("creditor", {}).get("country") == "GH"
    ):
        tax_notices.append(
            {
                "text": TAX_NOTICE_TEXT,
                "reference": "France–Ghana tax convention (1993)",
                "source": TAX_NOTICE_SOURCE,
            }
        )
    if any((route.get("id") or route.get("routeId")) == "R3" for route in normalized_routes):
        tax_notices.append(
            {
                "text": "Any EU CASP leg is reportable under DAC8.",
                "reference": "DAC8 (since 1 January 2026)",
                "source": "https://taxation-customs.ec.europa.eu/taxation/tax-transparency-cooperation/administrative-co-operation-and-mutual-assistance/directive-administrative-cooperation-dac/dac8_en",
            }
        )
    return norm_checks, tax_notices