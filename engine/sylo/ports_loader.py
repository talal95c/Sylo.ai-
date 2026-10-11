"""Pick the RiskPort and ChainPort implementations from the flags, with fail-safe fallbacks (v0 spec §5.2).

If the model, the Fuji client or the case writer cannot be loaded, the engine uses the rules (made
stricter), the mock chain or a case file built from the rules, and reports the dependency in
``system.mode.degraded`` so the banner turns amber.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sylo_spec.ports import ChainPort, RiskPort

from .chain_mock import MockChain
from .config import Settings
from .risk_rules import CombinedRisk, RulesRisk
from .signer import Signer

log = logging.getLogger("sylo.ports")


def load_ports(settings: Settings, *, signer: Signer, clock: Callable[[], float]) -> tuple[RiskPort, ChainPort, list[str]]:
    degraded: list[str] = []

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

    return risk, chain, degraded


def load_case_writer(settings: Settings) -> tuple[Any | None, bool]:
    """Lane B's ``CasePort`` for ``LLM_MODE=cached|live``. Returns (writer or None, degraded).

    The writer (``sylo_risk.CaseWriter``, the Mistral investigator) is optional: without it the
    engine builds the case file from the rules and reports ``llm`` as degraded.
    """
    if settings.llm_mode == "off":
        return None, False
    try:
        try:
            from sylo_risk import CaseWriter
        except ImportError:
            from sylo_risk.case import CaseWriter

        return CaseWriter(), False
    except Exception as err:
        log.warning("LLM_MODE=%s but the case writer is unavailable (%s); case files come from the rules", settings.llm_mode, err)
        return None, True
