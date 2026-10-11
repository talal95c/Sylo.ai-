"""Pick the RiskPort and ChainPort implementations from the flags, with fail-safe fallbacks (v0 spec §5.2).

If the model, the Fuji client or the case writer cannot be loaded, the engine uses the rules (made
stricter), the mock chain or a case file built from the rules, and reports the dependency in
``system.mode.degraded`` so the banner turns amber.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
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


def load_case_writer(
    settings: Settings, env: Mapping[str, str] | None = None
) -> tuple[Any | None, bool, Any | None, bool]:
    """Load the normal and optional jury-live case writers.

    The writer (``sylo_risk.CaseWriter``, the Mistral investigator) is optional: without it the
    engine builds the case file from the rules and reports ``llm`` as degraded. Live invoice caches
    stay in a private temporary directory rather than the shared Lane B cache.
    """
    env = os.environ if env is None else env
    if settings.llm_mode == "off" and not settings.live_invoice:
        return None, False, None, False
    try:
        try:
            from sylo_risk import CaseWriter
            from sylo_risk import TextScreen
        except ImportError:
            from sylo_risk.case import CaseWriter
            from sylo_risk.case import TextScreen

        api_key = env.get("MISTRAL_API_KEY") or None
        writer = None
        degraded = False
        if settings.llm_mode != "off":
            writer = CaseWriter(mode=settings.llm_mode, api_key=api_key, model=env.get("MISTRAL_MODEL") or None)
        if settings.llm_mode == "live" and not api_key:
            log.warning("LLM_MODE=live but MISTRAL_API_KEY is not set; the case writer falls back to cached, then template")
        live_writer = None
        live_writer_ready = False
        if settings.live_invoice:
            cache_root = tempfile.TemporaryDirectory(prefix="sylo-live-invoice-")
            cache_dir = Path(cache_root.name)
            try:
                live_writer = CaseWriter(
                    mode="live",
                    api_key=api_key,
                    model=env.get("MISTRAL_MODEL") or None,
                    cache_dir=cache_dir / "sylo-mistral",
                    text_screen=TextScreen(mode="live", cache_dir=cache_dir / "sylo-jev-jury"),
                )
                live_writer._sylo_cache_tempdir = cache_root
                live_writer_ready = bool(api_key and env.get("JEV_API_KEY"))
            except Exception:
                cache_root.cleanup()
                raise
        return writer, degraded, live_writer, live_writer_ready
    except Exception as err:
        if settings.llm_mode != "off":
            log.warning(
                "LLM_MODE=%s but the case writer is unavailable (%s); case files come from the rules",
                settings.llm_mode,
                type(err).__name__,
            )
            return None, True, None, False
        log.warning("live invoice writer is unavailable (%s)", type(err).__name__)
        return None, False, None, False
