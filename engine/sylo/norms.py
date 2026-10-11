"""Norms engine: corridor pack + country profiles -> which routes are legal (v0 spec §5.5).

A rule returns PASS, FAIL or NEEDS_DOCUMENT; anything but PASS excludes the route, and an unknown
check counts as FAIL (fail safe). Norm signals inform the risk engine but never exclude routes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sylo_spec import SPEC_DIR
from sylo_spec.models import PaymentOrder
from sylo_spec.scenarios import ACCOUNTS, PAYEES, normalize_name

from . import ENGINE_DIR, texts

PASS, FAIL, NEEDS_DOCUMENT = "PASS", "FAIL", "NEEDS_DOCUMENT"
CRED = "{CRED}"


@dataclass(frozen=True)
class RouteModel:
    lam: float
    mu: float
    nu: float
    sigma: float


@dataclass(frozen=True)
class RouteDef:
    id: str
    name: str
    settlement: str
    fees_eur: float | None
    fees_pct: float | None
    minutes: float
    p_fail: float
    p_unusable: float
    eta_label: str
    credits_wallet: bool
    hops: tuple[tuple[str, str, str], ...]

    def fees(self, amount: float) -> float:
        if self.fees_eur is not None:
            return self.fees_eur
        return (self.fees_pct or 0.0) * amount

    @property
    def days(self) -> float:
        return self.minutes / 1440


@dataclass(frozen=True)
class Rule:
    id: str
    jurisdiction: str
    check: str
    legal_ref: str
    routes: tuple[str, ...] | None
    when: dict[str, Any]
    params: dict[str, Any]
    signal: dict[str, Any] | None


@dataclass(frozen=True)
class Pack:
    id: str
    version: str
    fx_eur_ghs: float
    route_model: RouteModel
    routes: tuple[RouteDef, ...]
    rules: tuple[Rule, ...]
    tax_notices: tuple[dict[str, Any], ...]
    profiles: dict[str, dict[str, Any]]

    @property
    def pack_version(self) -> str:
        return f"{self.id}@{self.version}"

    def route(self, route_id: str) -> RouteDef:
        return next(r for r in self.routes if r.id == route_id)


def load_pack(corridor: str = "FR-GH", base: Path = ENGINE_DIR) -> Pack:
    raw = yaml.safe_load((base / "packs" / f"{corridor}.yaml").read_text(encoding="utf-8"))
    profiles = {
        pid: yaml.safe_load((base / "profiles" / f"{pid}.yaml").read_text(encoding="utf-8")) for pid in raw["profiles"]
    }
    enabled = {rule_id for profile in profiles.values() for rule_id in profile.get("rules", [])}
    defined = {r["id"] for r in raw["rules"]}
    if missing := enabled - defined:
        raise ValueError(f"profiles reference rules missing from pack {corridor}: {sorted(missing)}")
    model = raw["routeModel"]
    return Pack(
        id=raw["id"],
        version=str(raw["version"]),
        fx_eur_ghs=float(raw["fx"]["EUR_GHS"]),
        route_model=RouteModel(
            lam=float(model["lambda"]), mu=float(model["mu"]), nu=float(model["nu"]), sigma=float(model["sigma"])
        ),
        routes=tuple(
            RouteDef(
                id=r["id"],
                name=r["name"],
                settlement=r["settlement"],
                fees_eur=float(r["feesEur"]) if "feesEur" in r else None,
                fees_pct=float(r["feesPct"]) if "feesPct" in r else None,
                minutes=float(r["minutes"]),
                p_fail=float(r["pFail"]),
                p_unusable=float(r.get("pUnusable", 0)),
                eta_label=r["etaLabel"],
                credits_wallet=bool(r.get("creditsWallet", False)),
                hops=tuple((h[0], h[1], h[2]) for h in r["hops"]),
            )
            for r in raw["routes"]
        ),
        rules=tuple(
            Rule(
                id=r["id"],
                jurisdiction=r["jurisdiction"],
                check=r["check"],
                legal_ref=r["legalRef"],
                routes=tuple(r["routes"]) if "routes" in r else None,
                when=dict(r.get("when", {})),
                params=dict(r.get("params", {})),
                signal=dict(r["signal"]) if "signal" in r else None,
            )
            for r in raw["rules"]
            if r["id"] in enabled
        ),
        tax_notices=tuple(raw.get("taxNotices", [])),
        profiles=profiles,
    )


# --- Checks ----------------------------------------------------------------------------------

Hop = dict[str, str]
CheckFn = Callable[[RouteDef, list[Hop], PaymentOrder, dict[str, Any], Pack], str]


def _export_proceeds_route(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    if route.credits_wallet:
        return FAIL
    if not order.documents.loc_ref:
        return NEEDS_DOCUMENT
    return PASS


def _wallet_daily_cap(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    amount_ghs = order.amount.as_float * pack.fx_eur_ghs
    return PASS if amount_ghs <= float(params["capGhs"]) else FAIL


def _vasp_licensed(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    vasps = [h["to"] for h in hops if h["kind"] == "chain"]
    return PASS if vasps and all(v in params.get("licensed", []) for v in vasps) else FAIL


def _casp_authorised(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    casps = [h["from"] for h in hops if h["kind"] == "chain"]
    token_ok = "EURC" in params.get("tokens", [])
    return PASS if casps and token_ok and all(c in params.get("casps", []) for c in casps) else FAIL


def _travel_rule_fields(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    fields = (order.debtor.name, order.debtor.id, order.creditor.name, order.creditor_account_id, order.uetr)
    return PASS if all(fields) else FAIL


def _sanctions_screen(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    listed = {normalize_name(name) for name in params.get("list", [])}
    account = ACCOUNTS.get(order.creditor_account_id)
    names = [order.debtor.name, order.creditor.name] + ([account.holder_name] if account else [])
    return FAIL if any(normalize_name(name) in listed for name in names) else PASS


@lru_cache(maxsize=1)
def institution_countries() -> dict[str, str]:
    """Institution id -> ISO country, from the registry the globe draws (``spec/geo/institutions.json``)."""
    raw = json.loads((SPEC_DIR / "geo" / "institutions.json").read_text(encoding="utf-8"))
    return {item["id"]: item["country"] for item in raw["institutions"]}


def _high_risk_country(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    """A route through a listed country needs an enhanced due diligence file; an unknown institution fails."""
    listed = set(params.get("listed", []))
    countries = institution_countries()
    on_route = {institution for hop in hops for institution in (hop["from"], hop["to"])}
    if any(institution not in countries for institution in on_route):
        return FAIL
    return NEEDS_DOCUMENT if any(countries[institution] in listed for institution in on_route) else PASS


def _payee_name_check_scope(route: RouteDef, hops: list[Hop], order: PaymentOrder, params: dict, pack: Pack) -> str:
    """Informative: whether the bank's own payee name check reaches the corridor never excludes a route."""
    return PASS


CHECKS: dict[str, CheckFn] = {
    "export_proceeds_route": _export_proceeds_route,
    "wallet_daily_cap": _wallet_daily_cap,
    "vasp_licensed": _vasp_licensed,
    "casp_authorised": _casp_authorised,
    "travel_rule_fields": _travel_rule_fields,
    "sanctions_screen": _sanctions_screen,
    "high_risk_country": _high_risk_country,
    "payee_name_check_scope": _payee_name_check_scope,
}


def _applies(rule: Rule, order: PaymentOrder) -> bool:
    if "purpose" in rule.when and order.purpose != rule.when["purpose"]:
        return False
    if "creditorCountry" in rule.when and order.creditor.country != rule.when["creditorCountry"]:
        return False
    return True


def _is_nominated_account(order: PaymentOrder) -> bool:
    account = ACCOUNTS.get(order.creditor_account_id)
    payee = PAYEES.get(order.payee_id)
    return bool(account and payee and account.nominated_for_exports and payee.owns(account.id))


# --- Results ---------------------------------------------------------------------------------


@dataclass
class RouteEval:
    route: RouteDef
    hops: list[Hop]
    status: str
    excluded_by: str | None = None
    reason: str | None = None
    legal_ref: str | None = None
    checks: list[dict[str, str]] = field(default_factory=list)

    def to_event(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "routeId": self.route.id,
            "name": self.route.name,
            "settlement": self.route.settlement,
            "hops": self.hops,
            "status": self.status,
        }
        if self.status != PASS:
            data.update(excludedBy=self.excluded_by, reason=self.reason, legalRef=self.legal_ref)
        data["checks"] = self.checks
        return data


@dataclass
class NormsResult:
    pack_version: str
    routes: list[RouteEval]
    signals: list[dict[str, str]]
    tax_notices: list[dict[str, str]]
    controls: list[dict[str, str]] = field(default_factory=list)
    """Controls a rule asks for without excluding a route (for example the out-of-band check outside SEPA)."""

    def route(self, route_id: str) -> RouteEval:
        return next(r for r in self.routes if r.route.id == route_id)

    @property
    def signal_codes(self) -> list[str]:
        return [s["code"] for s in self.signals]

    def to_event_data(self) -> dict[str, Any]:
        return {
            "packVersion": self.pack_version,
            "routes": [r.to_event() for r in self.routes],
            "signals": self.signals,
            "taxNotices": self.tax_notices,
            "controls": self.controls,
        }


class NormsEngine:
    def __init__(self, pack: Pack | None = None) -> None:
        self.pack = pack or load_pack()

    def resolve_hops(self, route: RouteDef, order: PaymentOrder) -> list[Hop]:
        account = ACCOUNTS.get(order.creditor_account_id)
        creditor_inst = account.institution_id if account else order.creditor.institution_id
        hops = [
            {"from": creditor_inst if a == CRED else a, "to": creditor_inst if b == CRED else b, "kind": kind}
            for a, b, kind in route.hops
        ]
        payee = PAYEES.get(order.payee_id)
        if not route.credits_wallet and account and payee and payee.owns(account.id) and payee.institution_id != creditor_inst:
            hops.append({"from": creditor_inst, "to": payee.institution_id, "kind": "bank"})
        return hops

    def evaluate(self, order: PaymentOrder) -> NormsResult:
        evaluations: list[RouteEval] = []
        for route in self.pack.routes:
            hops = self.resolve_hops(route, order)
            checks: list[dict[str, str]] = []
            first_failure: Rule | None = None
            for rule in self.pack.rules:
                if rule.routes is not None and route.id not in rule.routes:
                    continue
                if not _applies(rule, order):
                    continue
                check = CHECKS.get(rule.check)
                result = check(route, hops, order, rule.params, self.pack) if check else FAIL
                checks.append({"ruleId": rule.id, "result": result})
                if result != PASS and first_failure is None:
                    first_failure = rule
            if first_failure is None:
                evaluations.append(RouteEval(route, hops, PASS, checks=checks))
            else:
                evaluations.append(
                    RouteEval(
                        route,
                        hops,
                        "EXCLUDED",
                        excluded_by=first_failure.id,
                        reason=texts.EXCLUSION_REASONS.get(first_failure.id, f"Excluded by {first_failure.id}."),
                        legal_ref=first_failure.legal_ref,
                        checks=checks,
                    )
                )

        signals: list[dict[str, str]] = []
        for rule in self.pack.rules:
            if rule.signal and _applies(rule, order):
                if rule.signal.get("check") == "nominated_account" and not _is_nominated_account(order):
                    payee = PAYEES.get(order.payee_id)
                    signals.append(
                        {
                            "code": rule.signal["code"],
                            "text": texts.SIGNAL_R1.format(payee_short=texts.payee_short(payee)),
                            "ruleId": rule.id,
                        }
                    )
                if rule.signal.get("check") == "account_country":
                    account = ACCOUNTS.get(order.creditor_account_id)
                    held_in = institution_countries().get(account.institution_id) if account else None
                    if held_in in rule.params.get("listed", []) and held_in != order.creditor.country:
                        signals.append(
                            {
                                "code": rule.signal["code"],
                                "text": texts.SIGNAL_R4.format(country=held_in, expected=order.creditor.country),
                                "ruleId": rule.id,
                            }
                        )

        controls = [
            {"ruleId": rule.id, "text": texts.CONTROL_NOTICES[rule.id], "legalRef": rule.legal_ref}
            for rule in self.pack.rules
            if rule.check == "payee_name_check_scope"
            and rule.params.get("available") is False
            and rule.id in texts.CONTROL_NOTICES
            and _applies(rule, order)
        ]

        passing = {e.route.id for e in evaluations if e.status == PASS}
        notices = [
            {"text": n["text"], "reference": n["reference"]}
            for n in self.pack.tax_notices
            if not n.get("whenRoutePasses") or n["whenRoutePasses"] in passing
        ]
        return NormsResult(self.pack.pack_version, evaluations, signals, notices, controls)
