"""Engine settings, read from the environment with safe defaults (rules, mock chain, no LLM)."""

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

MOCK_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000E0C"
MOCK_REGISTRY_ADDRESS = "0x0000000000000000000000000000000000000001"


def _clean(value: Optional[str]) -> str:
    """Strip whitespace and trailing `# comments` (so a copied .env.example line still works)."""
    return (value or "").split("#", 1)[0].strip()


@dataclass(frozen=True)
class Settings:
    risk_mode: str = "rules"  # rules | model
    chain_mode: str = "mock"  # mock | fuji
    llm_mode: str = "off"  # off | cached | live
    demo_speed: float = 1.0
    engine_port: int = 8000
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    seed: int = 42
    escrow_hold_seconds: int = 86_400
    token_address: str = MOCK_TOKEN_ADDRESS
    registry_address: str = MOCK_REGISTRY_ADDRESS
    chain_id: int = 43113
    env: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    def get(self, key: str) -> str:
        return _clean(self.env.get(key))


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env

    def text(key: str, default: str) -> str:
        return _clean(env.get(key)) or default

    return Settings(
        risk_mode=text("RISK_MODE", "rules").lower(),
        chain_mode=text("CHAIN_MODE", "mock").lower(),
        llm_mode=text("LLM_MODE", "off").lower(),
        demo_speed=float(text("DEMO_SPEED", "1")),
        engine_port=int(text("ENGINE_PORT", "8000")),
        cors_origins=tuple(o.strip() for o in text("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()),
        seed=int(text("SEED", "42")),
        escrow_hold_seconds=int(text("ESCROW_HOLD_SECONDS", "86400")),
        token_address=text("TOKEN_ADDRESS", MOCK_TOKEN_ADDRESS),
        registry_address=text("REGISTRY_ADDRESS", MOCK_REGISTRY_ADDRESS),
        chain_id=int(text("CHAIN_ID", "43113")),
        env=dict(env),
    )
