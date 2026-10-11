"""Engine flags, read from the environment (v0 spec §5.1)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from . import ENGINE_DIR


ORANGE_PLAYGROUND_PHONE_NUMBERS = {
    "+233 •• ••• 4471": {
        "default": "+990100000000",
        "diverted_simswap": "+990100000001",
    }
}
ORANGE_PLAYGROUND_MIN_MAX_AGE_HOURS = 240


def orange_playground_number(msisdn: str, scenario: str) -> str:
    """Map the demo supplier contact to the Playground's documented test profiles."""
    numbers = ORANGE_PLAYGROUND_PHONE_NUMBERS.get(msisdn)
    if numbers is None:
        return msisdn
    profile = "diverted_simswap" if scenario == "diverted_simswap" else "default"
    return numbers[profile]


def _get(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    return default if value is None or not value.strip() else value.strip()


def _journal_path(env: Mapping[str, str]) -> str | None:
    """The decision log is written by default when the engine runs from the environment; "off" disables it."""
    value = _get(env, "JOURNAL_PATH", str(ENGINE_DIR / "data" / "log.jsonl"))
    return None if value.lower() == "off" else value


@dataclass(frozen=True)
class Settings:
    """``human_steps``: ``auto`` simulates the payer approvals and the analyst's confirmation (v0 behaviour);
    ``manual`` waits for them on the API unless the scenario runs with ``auto: true``."""

    risk_mode: str = "rules"
    chain_mode: str = "mock"
    llm_mode: str = "off"
    telecom_mode: str = "mock"
    demo_speed: float = 1.0
    engine_port: int = 8000
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    seed: int = 42
    escrow_hold_seconds: int = 86_400
    chain_id: int = 43113
    registry_address: str | None = None
    token_address: str | None = None
    explorer_base_url: str = "https://testnet.snowtrace.io"
    # v1: human steps, dual control, out-of-band check, decision log
    human_steps: str = "auto"
    dual_control_eur: float = 20_000.0
    dual_control_new_payee_eur: float = 5_000.0
    sim_swap_max_age_hours: int = 168
    journal_path: str | None = None
    # Business rules of the playbook (PRD §12.3), configurable per institution
    time_lock_from_eur: float = 5_000.0
    time_lock_long_from_eur: float = 50_000.0
    time_lock_hours: float = 4.0
    time_lock_long_hours: float = 24.0
    reroute_max_fees_eur: float = 500.0
    reroute_max_days: float = 3.0
    # P1: the chain leg of a payment that needs no hold as an eERC confidential transfer (off | simulated | eerc)
    confidential_mode: str = "off"
    eerc_url: str = "http://127.0.0.1:8010"
    # v2: "auto" uses Lane B's cluster detector when it is installed, "sample" always uses the sample cluster
    cluster_mode: str = "auto"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        origins = _get(env, "CORS_ORIGINS", ",".join(cls.cors_origins))
        telecom_mode = _get(env, "TELECOM_MODE", "mock").lower()
        if telecom_mode not in {"mock", "orange-playground"}:
            raise ValueError("TELECOM_MODE must be 'mock' or 'orange-playground'")
        return cls(
            risk_mode=_get(env, "RISK_MODE", "rules").lower(),
            chain_mode=_get(env, "CHAIN_MODE", "mock").lower(),
            llm_mode=_get(env, "LLM_MODE", "off").lower(),
            telecom_mode=telecom_mode,
            demo_speed=float(_get(env, "DEMO_SPEED", "1")),
            engine_port=int(_get(env, "ENGINE_PORT", "8000")),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            seed=int(_get(env, "SEED", "42")),
            escrow_hold_seconds=int(_get(env, "ESCROW_HOLD_SECONDS", "86400")),
            chain_id=int(_get(env, "CHAIN_ID", "43113")),
            registry_address=env.get("REGISTRY_ADDRESS") or None,
            token_address=env.get("TOKEN_ADDRESS") or None,
            explorer_base_url=_get(env, "EXPLORER_BASE_URL", "https://testnet.snowtrace.io"),
            human_steps=_get(env, "HUMAN_STEPS", "auto").lower(),
            dual_control_eur=float(_get(env, "DUAL_CONTROL_EUR", "20000")),
            dual_control_new_payee_eur=float(_get(env, "DUAL_CONTROL_NEW_PAYEE_EUR", "5000")),
            sim_swap_max_age_hours=int(_get(env, "SIM_SWAP_MAX_AGE_HOURS", "168")),
            journal_path=_journal_path(env),
            cluster_mode=_get(env, "CLUSTER_MODE", "auto").lower(),
            confidential_mode=_get(env, "CONFIDENTIAL_MODE", "off").lower(),
            eerc_url=_get(env, "EERC_URL", "http://127.0.0.1:8010"),
            time_lock_from_eur=float(_get(env, "TIME_LOCK_FROM_EUR", "5000")),
            time_lock_long_from_eur=float(_get(env, "TIME_LOCK_LONG_FROM_EUR", "50000")),
            time_lock_hours=float(_get(env, "TIME_LOCK_HOURS", "4")),
            time_lock_long_hours=float(_get(env, "TIME_LOCK_LONG_HOURS", "24")),
            reroute_max_fees_eur=float(_get(env, "REROUTE_MAX_FEES_EUR", "500")),
            reroute_max_days=float(_get(env, "REROUTE_MAX_DAYS", "3")),
        )
