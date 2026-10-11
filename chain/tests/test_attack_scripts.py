"""contracts/script/attacks/*.sh against Anvil: each attack is mined as a failed tx with the expected reason."""

from __future__ import annotations

import os
import subprocess

import pytest
from conftest import CONTRACTS, FOUNDRY_BIN, AnvilDeployment
from sylo_spec.devkeys import dev_address, dev_key

ATTACKS = CONTRACTS / "script" / "attacks"


def _run(script: str, anvil: AnvilDeployment, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{FOUNDRY_BIN}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": os.environ.get("HOME", ""),
        "ENV_FILE": "none",
        "RPC_URL": anvil.rpc_url,
        "RELAYER_PK": dev_key("relayer"),
        "ROUTER_SIGNER_PK": dev_key("router_signer"),
        "ANALYST_SIGNER_PK": dev_key("analyst_signer"),
        "ATTACKER_PK": dev_key("attacker"),
        "ATTACKER_ADDRESS": dev_address("attacker"),
        "EU_CASP_ADDRESS": dev_address("eu_casp"),
        "GH_VASP_ADDRESS": dev_address("gh_vasp"),
        **extra,
    }
    return subprocess.run(
        ["bash", str(ATTACKS / script)], env=env, capture_output=True, text=True, timeout=180, check=False
    )


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ("release-revoked.sh", "PaymentNotReleasable"),
        ("swap-beneficiary.sh", "CommitmentMismatch"),
        ("replay-intent.sh", "InvalidTransition"),
    ],
)
def test_attack_is_refused_on_chain(anvil: AnvilDeployment, script: str, reason: str) -> None:
    result = _run(script, anvil)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"REFUSED by the contract: {reason}" in result.stdout


def test_release_revoked_refuses_a_payment_that_is_not_revoked(anvil: AnvilDeployment) -> None:
    result = _run("release-revoked.sh", anvil, PAYMENT_ID="0x" + "11" * 32)
    assert result.returncode != 0
    assert "not REVOKED" in result.stderr
