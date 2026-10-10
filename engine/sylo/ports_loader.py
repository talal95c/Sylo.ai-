"""Picks the risk and chain implementations from the flags, with a safe fallback.

If a real component cannot be loaded, the engine falls back to the rules or the mock and
reports it in `system.mode.degraded`, so the UI shows a banner. Nothing is released by default.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sylo_spec.models import PaymentOrder, RiskContext, RiskReason, RiskResult
from sylo_spec.ports import ChainPort, RiskPort

from .chain_mock import MockChain
from .config import Settings
from .risk_rules import RulesRisk, band


class CombinedRisk:
    """Rules give the floor; the model adds its score and reasons. tier = max(floor, band(score))."""

    def __init__(self, rules: RulesRisk, model: RiskPort):
        self.rules = rules
        self.model = model
        self.name = getattr(model, "name", "model")

    def score(self, order: PaymentOrder, ctx: RiskContext) -> RiskResult:
        floor = self.rules.score(order, ctx)
        scored = self.model.score(order, ctx)
        seen = {r.text for r in floor.reasons}
        extra = [RiskReason(ref=r.ref, text=r.text, rule_id=r.rule_id) for r in scored.reasons if r.text not in seen]
        return RiskResult(
            score=scored.score,
            tier=max(floor.floor_tier, band(scored.score)),
            floor_tier=floor.floor_tier,
            rules_fired=floor.rules_fired,
            reasons=(floor.reasons if floor.rules_fired else []) + extra,
            model=self.name,
        )


@dataclass
class Ports:
    risk: RiskPort
    chain: ChainPort
    risk_mode: str  # what actually runs: "rules" | "model"
    chain_mode: str  # "mock" | "fuji"
    llm_mode: str
    degraded: list[str] = field(default_factory=list)

    def mode_data(self) -> dict[str, Any]:
        return {
            "risk": self.risk_mode,
            "chain": self.chain_mode,
            "llm": self.llm_mode,
            "rails": "simulated",
            "degraded": list(self.degraded),
        }


def load_ports(settings: Settings, clock: Optional[Callable[[], float]] = None, addresses: Any = None) -> Ports:
    degraded: list[str] = []
    rules = RulesRisk()

    risk: RiskPort = rules
    risk_mode = "rules"
    if settings.risk_mode == "model":
        try:
            from sylo_risk import ModelRisk  # type: ignore[import-not-found]

            risk = CombinedRisk(rules, ModelRisk())
            risk_mode = "model"
        except Exception:
            degraded.append("risk")

    def mock() -> MockChain:
        kwargs: dict[str, Any] = {}
        if addresses is not None:
            kwargs = {
                "router_signer": addresses.router_signer,
                "verifier_signer": addresses.verifier_signer,
                "analyst_signer": addresses.analyst_signer,
                "payer_treasury": addresses.payer_treasury,
            }
        return MockChain(
            chain_id=settings.chain_id,
            registry_address=settings.registry_address,
            token_address=settings.token_address,
            hold_seconds=settings.escrow_hold_seconds,
            clock=clock,
            **kwargs,
        )

    chain: ChainPort
    chain_mode = "mock"
    if settings.chain_mode == "fuji":
        try:
            from sylo_chain import FujiChain  # type: ignore[import-not-found]

            chain = FujiChain()
            chain_mode = "fuji"
        except Exception:
            degraded.append("chain")
            chain = mock()
    else:
        chain = mock()

    llm_mode = settings.llm_mode if settings.llm_mode in ("off", "cached", "live") else "off"
    return Ports(risk=risk, chain=chain, risk_mode=risk_mode, chain_mode=chain_mode, llm_mode=llm_mode, degraded=degraded)
