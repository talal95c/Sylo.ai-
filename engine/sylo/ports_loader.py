"""Pick the RiskPort and ChainPort implementations from the flags, with fail-safe fallbacks (v0 spec §5.2).

If the model or the Fuji client cannot be loaded, the engine uses the rules (made stricter) or the
mock chain, and reports the dependency in ``system.mode.degraded`` so the banner turns amber.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping

from sylo_spec.ports import CasePort, ChainPort, RiskPort

from .chain_mock import MockChain
from .config import Settings
from .risk_rules import CombinedRisk, RulesRisk
from .signer import Signer

log = logging.getLogger("sylo.ports")


def load_ports(
    settings: Settings,
    *,
    signer: Signer,
    clock: Callable[[], float],
    env: Mapping[str, str] | None = None,
) -> tuple[RiskPort, ChainPort, CasePort | None, list[str]]:
    degraded: list[str] = []
    environment = os.environ if env is None else env

    risk: RiskPort = RulesRisk()
    if settings.risk_mode == "model":
        try:
            from sylo_risk import ModelRisk

            risk = CombinedRisk(RulesRisk(), ModelRisk())
        except Exception as err:
            log.warning("RISK_MODE=model but the model is unavailable (%s); using stricter rules", err)
            risk = RulesRisk(strict=True)
            degraded.append("risk")

    chain: ChainPort | None = None
    if settings.chain_mode == "fuji":
        try:
            from sylo_chain import FujiChain

            chain = FujiChain.from_env()
        except Exception as err:
            log.warning("CHAIN_MODE=fuji but the Fuji client is unavailable (%s); using the mock chain", err)
            degraded.append("chain")
    if chain is None:
        chain = MockChain(
            chain_id=settings.chain_id,
            registry_address=settings.registry_address,
            router_signers=[signer.address("router_signer")],
            verifier_signers=[signer.address("verifier_signer")],
            analyst_signers=[signer.address("analyst_signer")],
            hold_seconds=settings.escrow_hold_seconds,
            clock=clock,
        )

    case: CasePort | None = None
    try:
        from sylo_risk import CaseWriter

        api_key = environment.get("MISTRAL_API_KEY")
        case_mode = settings.llm_mode
        if case_mode == "live" and not api_key:
            log.warning("LLM_MODE=live but MISTRAL_API_KEY is not configured; trying cached then template")
        case = CaseWriter(
            mode=case_mode,
            api_key=api_key,
            model=environment.get("MISTRAL_MODEL"),
        )
    except Exception as err:
        log.warning("LLM_MODE=%s CasePort is unavailable (%s); running without case files", settings.llm_mode, type(err).__name__)
        degraded.append("llm")

    return risk, chain, case, degraded
