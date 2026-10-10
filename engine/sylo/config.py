"""Engine flags, read from the environment (v0 spec §5.1)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


def _get(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    return default if value is None or not value.strip() else value.strip()


@dataclass(frozen=True)
class Settings:
    risk_mode: str = "rules"
    chain_mode: str = "mock"
    llm_mode: str = "off"
    demo_speed: float = 1.0
    engine_port: int = 8000
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    seed: int = 42
    escrow_hold_seconds: int = 86_400
    chain_id: int = 43113
    registry_address: str | None = None
    token_address: str | None = None
    explorer_base_url: str = "https://testnet.snowtrace.io"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        origins = _get(env, "CORS_ORIGINS", ",".join(cls.cors_origins))
        return cls(
            risk_mode=_get(env, "RISK_MODE", "rules").lower(),
            chain_mode=_get(env, "CHAIN_MODE", "mock").lower(),
            llm_mode=_get(env, "LLM_MODE", "off").lower(),
            demo_speed=float(_get(env, "DEMO_SPEED", "1")),
            engine_port=int(_get(env, "ENGINE_PORT", "8000")),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            seed=int(_get(env, "SEED", "42")),
            escrow_hold_seconds=int(_get(env, "ESCROW_HOLD_SECONDS", "86400")),
            chain_id=int(_get(env, "CHAIN_ID", "43113")),
            registry_address=env.get("REGISTRY_ADDRESS") or None,
            token_address=env.get("TOKEN_ADDRESS") or None,
            explorer_base_url=_get(env, "EXPLORER_BASE_URL", "https://testnet.snowtrace.io"),
        )
