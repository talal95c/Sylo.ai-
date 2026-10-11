"""The chain conformance suite against the live Fuji deployment (opt-in: spends test AVAX)."""

from __future__ import annotations

import json
import os

import pytest
from conftest import CONTRACTS, ROOT
from sylo_chain import FujiChain
from sylo_spec.conformance import ConformanceKeys, run_chain_conformance


def _fuji_env() -> dict[str, str]:
    env = dict(os.environ)
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#"):
                env.setdefault(key.strip(), value.strip().strip('"'))
    return env


@pytest.mark.skipif(not os.environ.get("SYLO_RUN_FUJI_TESTS"), reason="set SYLO_RUN_FUJI_TESTS=1 to run on Fuji")
def test_fuji_chain_passes_the_chain_conformance_suite() -> None:
    env = _fuji_env()
    token = env.get("TOKEN_ADDRESS") or json.loads((CONTRACTS / "deployments" / "43113.json").read_text())["token"]
    run_chain_conformance(
        lambda: FujiChain.from_env(env),
        token=token,
        payer=env["EU_CASP_ADDRESS"],
        keys=ConformanceKeys(
            router=env["ROUTER_SIGNER_PK"],
            verifier=env["VERIFIER_SIGNER_PK"],
            analyst=env["ANALYST_SIGNER_PK"],
            outsider=env["ATTACKER_PK"],
            beneficiary=env["GH_VASP_ADDRESS"],
        ),
    )
