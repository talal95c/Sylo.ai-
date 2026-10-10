"""Norms engine: which routes are legal at origin and destination, and which signals the norms raise.

Profiles (one YAML per country) and packs (one YAML per corridor) are data. The checks they
name are the small functions below. Every check returns PASS, FAIL or NEEDS_DOCUMENT; anything
but PASS excludes the route, and an unknown check counts as FAIL (unknown is never safe).

Norms come first: no risk score and no price can bring an excluded route back.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from sylo_spec.models import Account, Hop, Payee, PaymentOrder

from . import texts

ENGINE_DIR = Path(__file__).resolve().parents[1]
PROFILES_DIR = ENGINE_DIR / "profiles"
PACKS_DIR = ENGINE_DIR / "packs"

PASS, FAIL, NEEDS_DOCUMENT = "PASS", "FAIL", "NEEDS_DOCUMENT"


@dataclass(frozen=True)
class RouteDef:
    id: str
    name: str
    settlement: str  # NONE | FIAT_HOLD | ONCHAIN_ESCROW
    credits: str  # bank | wallet
    eta_label: str
    fixed_fee_eur: float
    pct_fee: float
    time_days: float
    p_fail: float
    p_unusable: float
    hops: tuple[dict[str, str], ...]
    extra: dict[str, Any] = field(default_factory=dict)

    def fees_eur(self, amount_eur: float) -> float:
        return self.fixed_fee_eur + self.pct_fee * amount_eur


@dataclass(frozen=True)
class Pack:
    id: str
    version: str
    profiles: dict[str, dict[str, Any]]
    routes: tuple[RouteDef, ...]
    rules: tuple[dict[str, Any], ...]
    tax_notices: tuple[dict[str, Any], ...]
    weights: dict[str, float]
    fx: dict[str, float]
    leg_durations_ms: dict[str, float]
    flags: dict[str, Any]

    def route(self, route_id: str) -> RouteDef:
        return next(r for r in self.routes if r.id == route_id)


@dataclass
class RouteEval:
    route: RouteDef
    hops: list[Hop]
    hop_labels: list[str]
    status: str = "PASS"  # PASS | EXCLUDED
    excluded_by: Optional[str] = None
    reason: Optional[str] = None
    legal_ref: Optional[str] = None
    checks: list[dict[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_event(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "routeId": self.route.id,
            "name": self.route.name,
            "settlement": self.route.settlement,
            "hops": [h.to_json() for h in self.hops],
            "status": self.status,
        }
        if not self.passed:
            out.update({"excludedBy": self.excluded_by, "reason": self.reason, "legalRef": self.legal_ref})
        return out


@dataclass
class NormsResult:
    pack_version: str
    routes: list[RouteEval]
    signals: list[dict[str, str]]
    tax_notices: list[dict[str, str]]

    @property
    def signal_codes(self) -> list[str]:
        return [s["code"] for s in self.signals]

    def route(self, route_id: str) -> RouteEval:
        return next(r for r in self.routes if r.route.id == route_id)

    def to_event(self) -> dict[str, Any]:
        return {
            "packVersion": self.pack_version,
            "routes": [r.to_event() for r in self.routes],
            "signals": self.signals,
            "taxNotices": self.tax_notices,
        }


# --------------------------------------------------------------------------- loading


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def load_pack(pack_id: str = "FR-GH") -> Pack:
    raw = _load_yaml(PACKS_DIR / f"{pack_id}.yaml")
    profiles = {pid: _load_yaml(PROFILES_DIR / f"{pid}.yaml") for pid in raw["profiles"]}
    routes = tuple(
        RouteDef(
            id=r["id"],
            name=r["name"],
            settlement=r["settlement"],
            credits=r["credits"],
            eta_label=r["etaLabel"],
            fixed_fee_eur=float(r["fees"].get("fixedEur", 0.0)),
            pct_fee=float(r["fees"].get("pctOfAmount", 0.0)),
            time_days=float(r["timeDays"]),
            p_fail=float(r["pFail"]),
            p_unusable=float(r["pUnusable"]),
            hops=tuple(r["hops"]),
            extra={k: v for k, v in r.items() if k in ("casp", "vasp", "token")},
        )
        for r in raw["routes"]
    )
    return Pack(
        id=raw["id"],
        version=str(raw["version"]),
        profiles=profiles,
        routes=routes,
        rules=tuple(raw["rules"]),
        tax_notices=tuple(raw.get("taxNotices", [])),
        weights={k: float(v) for k, v in raw["weights"].items()},
        fx={k: float(v) for k, v in raw.get("fx", {}).items()},
        leg_durations_ms={k: float(v) for k, v in raw["leg"]["durationsMs"].items()},
        flags=dict(raw.get("flags", {})),
    )


# --------------------------------------------------------------------------- checks


@dataclass
class _Ctx:
    pack: Pack
    order: PaymentOrder
    account: Account
    payee: Optional[Payee]
    route: Optional[RouteDef] = None


def _route_credits_bank_with_loc(c: _Ctx) -> str:
    if c.route.credits != "bank":
        return FAIL
    return PASS if c.order.loc_ref else NEEDS_DOCUMENT


def _creditor_is_nominated_account(c: _Ctx) -> str:
    registered = c.payee is not None and c.payee.account(c.account.id) is not None
    return PASS if registered and c.account.nominated_for_exports else FAIL


def _wallet_daily_cap(c: _Ctx) -> str:
    rate = c.pack.fx.get("EURGHS")
    cap = c.pack.profiles["GH"].get("wallets", {}).get("dailyCapGhs")
    if rate is None or cap is None:
        return FAIL
    return PASS if c.order.amount.as_float() * rate <= float(cap) else FAIL


def _vasp_licensed(c: _Ctx) -> str:
    licensed = c.pack.profiles["GH"].get("crypto", {}).get("licensedVasps", [])
    return PASS if c.route.extra.get("vasp") in licensed else FAIL


def _mica_emt_casp(c: _Ctx) -> str:
    crypto = c.pack.profiles["FR"].get("crypto", {})
    casp_ok = c.route.extra.get("casp") in crypto.get("authorisedCasps", [])
    token_ok = c.route.extra.get("token") in crypto.get("authorisedEmoneyTokens", [])
    return PASS if casp_ok and token_ok else FAIL


def _travel_rule_fields(c: _Ctx) -> str:
    present = all([c.order.payer.name, c.order.creditor.payee_name, c.order.creditor.account_id, c.order.uetr])
    return PASS if present else NEEDS_DOCUMENT


def _sanctions_screen(c: _Ctx) -> str:
    listed = {
        name.upper()
        for profile in c.pack.profiles.values()
        for name in profile.get("sanctions", {}).get("names", [])
    }
    names = {c.order.payer.name.upper(), c.order.creditor.payee_name.upper(), c.order.creditor.account_holder.upper()}
    return FAIL if names & listed else PASS


CHECKS: dict[str, Callable[[_Ctx], str]] = {
    "route_credits_bank_with_loc": _route_credits_bank_with_loc,
    "creditor_is_nominated_account": _creditor_is_nominated_account,
    "wallet_daily_cap": _wallet_daily_cap,
    "vasp_licensed": _vasp_licensed,
    "mica_emt_casp": _mica_emt_casp,
    "travel_rule_fields": _travel_rule_fields,
    "sanctions_screen": _sanctions_screen,
}

EXCLUSION_TEXTS = {
    ("GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", FAIL): texts.EXCLUDED_WALLET_EXPORT_PROCEEDS,
    ("GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", NEEDS_DOCUMENT): texts.EXCLUDED_MISSING_LOC,
    ("GH_WALLET_DAILY_CAP", FAIL): texts.EXCLUDED_WALLET_CAP,
}

TAX_TEXTS = {"no_withholding_goods": texts.TAX_NO_WITHHOLDING, "dac8_casp_leg": texts.TAX_DAC8}


def _run(check: str, ctx: _Ctx) -> str:
    fn = CHECKS.get(check)
    if fn is None:
        return FAIL  # unknown check: not safe
    try:
        return fn(ctx)
    except Exception:
        return FAIL  # a check that cannot run is a failed check


def _applies(rule: dict[str, Any], ctx: _Ctx) -> bool:
    cond = rule.get("appliesTo", {})
    if "purpose" in cond and ctx.order.purpose != cond["purpose"]:
        return False
    if "creditorCountry" in cond and ctx.order.creditor.country != cond["creditorCountry"]:
        return False
    return True


# --------------------------------------------------------------------------- evaluation


def concrete_hops(route: RouteDef, order: PaymentOrder, account: Account, payee: Optional[Payee], payee_institution_id: Optional[str]) -> tuple[list[Hop], list[str]]:
    """Fill the hop templates of a route for one order."""
    fill = {
        "{PAYER}": order.payer.institution_id,
        "{PAYER_BANK}": order.payer.bank_institution_id,
        "{CRED}": account.institution_id,
    }
    hops = [Hop(src=fill.get(h["from"], h["from"]), dst=fill.get(h["to"], h["to"]), kind=h["kind"]) for h in route.hops]
    labels = [h.get("label", "") for h in route.hops]
    registered = payee is not None and payee.account(account.id) is not None
    if route.credits == "bank" and registered and payee_institution_id:
        hops.append(Hop(src=account.institution_id, dst=payee_institution_id, kind="bank"))
        labels.append("Funds available to the supplier")
    return hops, labels


def evaluate(order: PaymentOrder, account: Account, payee: Optional[Payee], payee_institution_id: Optional[str] = None, pack: Optional[Pack] = None) -> NormsResult:
    pack = pack or load_pack(order.corridor)
    ctx = _Ctx(pack=pack, order=order, account=account, payee=payee)
    supplier_name = (payee.short_name or payee.legal_name) if payee else order.creditor.payee_name

    signals: list[dict[str, str]] = []
    evaluations: list[RouteEval] = []
    for route in pack.routes:
        hops, labels = concrete_hops(route, order, account, payee, payee_institution_id)
        evaluation = RouteEval(route=route, hops=hops, hop_labels=labels)
        route_ctx = _Ctx(pack=pack, order=order, account=account, payee=payee, route=route)
        for rule in pack.rules:
            if "routes" in rule and route.id not in rule["routes"]:
                continue
            if not _applies(rule, route_ctx):
                continue
            for check in rule["checks"]:
                if check.get("scope") != "route":
                    continue
                result = _run(check["check"], route_ctx)
                evaluation.checks.append({"ruleId": rule["id"], "check": check["check"], "result": result})
                if result != PASS:
                    if check.get("signal") and not any(s["code"] == check["signal"] for s in signals):
                        signals.append({"code": check["signal"], "text": texts.REASON_HB_01, "ruleId": rule["id"]})
                    if evaluation.passed:  # keep the first failing rule
                        evaluation.status = "EXCLUDED"
                        evaluation.excluded_by = rule["id"]
                        evaluation.legal_ref = rule.get("legalRef")
                        evaluation.reason = EXCLUSION_TEXTS.get((rule["id"], result), texts.EXCLUDED_GENERIC.format(rule_id=rule["id"]))
        evaluations.append(evaluation)

    # Payment-level checks raise signals; they never exclude a route.
    for rule in pack.rules:
        if not _applies(rule, ctx):
            continue
        for check in rule["checks"]:
            if check.get("scope") != "payment":
                continue
            if _run(check["check"], ctx) != PASS and check.get("signal"):
                text = texts.signal_r1(supplier_name) if check["signal"] == "R1" else rule["id"]
                signals.append({"code": check["signal"], "text": text, "ruleId": rule["id"]})

    notices = []
    for notice in pack.tax_notices:
        when = notice.get("when", {})
        if "purpose" in when and order.purpose != when["purpose"]:
            continue
        if "routeCandidate" in when and not any(e.route.id == when["routeCandidate"] and e.passed for e in evaluations):
            continue
        notices.append({"text": TAX_TEXTS.get(notice["text"], notice["text"]), "reference": notice["reference"]})

    return NormsResult(pack_version=pack.version, routes=evaluations, signals=signals, tax_notices=notices)
