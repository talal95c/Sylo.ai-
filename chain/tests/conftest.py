"""Shared fixtures: a throwaway Anvil chain with the contracts deployed by the same Foundry scripts as Fuji."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sylo_chain import FujiChain
from sylo_spec.canonical import hash_record, keccak_text, to_hex
from sylo_spec.devkeys import MNEMONIC, dev_address, dev_key
from sylo_spec.eip712 import digest, sign
from sylo_spec.models import (
    PaymentIntent,
    Tier,
    TxRef,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
FOUNDRY_BIN = Path.home() / ".foundry" / "bin"
ANVIL_CHAIN_ID = 31337


def _tool(name: str) -> str | None:
    return shutil.which(name) or (str(FOUNDRY_BIN / name) if (FOUNDRY_BIN / name).exists() else None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass(frozen=True)
class AnvilDeployment:
    rpc_url: str
    registry: str
    escrow: str
    token: str

    def chain(self, **overrides: object) -> FujiChain:
        options: dict[str, object] = {
            "rpc_urls": [self.rpc_url],
            "registry": self.registry,
            "escrow": self.escrow,
            "keys": {role: dev_key(name) for role, name in DEV_ROLE_KEYS.items()},
            "chain_id": ANVIL_CHAIN_ID,
            "poll_latency": 0.05,
        }
        options.update(overrides)
        return FujiChain(**options)  # type: ignore[arg-type]


DEV_ROLE_KEYS = {"relayer": "relayer", "attacker": "attacker", "analyst": "analyst_signer", "guardian": "guardian"}


def _forge_script(forge: str, script: str, rpc_url: str, env: dict[str, str]) -> None:
    result = subprocess.run(
        [forge, "script", script, "--rpc-url", rpc_url, "--broadcast"],
        cwd=CONTRACTS,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"forge script {script} failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="session")
def anvil() -> Iterator[AnvilDeployment]:
    anvil_bin, forge = _tool("anvil"), _tool("forge")
    if not (anvil_bin and forge):
        pytest.skip("Foundry (anvil, forge) is not installed")
    port = _free_port()
    rpc_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [anvil_bin, "--port", str(port), "--mnemonic", MNEMONIC, "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.1)
        env = {
            **os.environ,
            "PATH": f"{FOUNDRY_BIN}{os.pathsep}{os.environ.get('PATH', '')}",
            "DEPLOYER_PK": dev_key("deployer"),
            "RELAYER_ADDRESS": dev_address("relayer"),
            "ROUTER_SIGNER_ADDRESS": dev_address("router_signer"),
            "VERIFIER_SIGNER_ADDRESS": dev_address("verifier_signer"),
            "ANALYST_SIGNER_ADDRESS": dev_address("analyst_signer"),
            "GUARDIAN_ADDRESS": dev_address("guardian"),
            "EU_CASP_ADDRESS": dev_address("eu_casp"),
            "EU_CASP_PK": dev_key("eu_casp"),
        }
        _forge_script(forge, "script/Deploy.s.sol", rpc_url, env)
        _forge_script(forge, "script/Approve.s.sol", rpc_url, env)
        addresses = json.loads((CONTRACTS / "deployments" / f"{ANVIL_CHAIN_ID}.json").read_text())
        yield AnvilDeployment(rpc_url, addresses["registry"], addresses["escrow"], addresses["token"])
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def make_intent(chain: FujiChain, token: str, tier: Tier = Tier.MEDIUM, amount: int = 1_000 * 10**6) -> PaymentIntent:
    label = f"CHAIN-TEST-{uuid.uuid4()}"
    return PaymentIntent(
        payment_id=to_hex(keccak_text(label)),
        corridor_id=to_hex(keccak_text(f"TEST-{uuid.uuid4()}")),
        beneficiary=dev_address("gh_vasp"),
        token=token,
        amount=amount,
        offchain_hash=hash_record({"label": label, "part": "offchain"}),
        decision_hash=hash_record({"label": label, "part": "decision"}),
        approval_hash=hash_record({"label": label, "part": "approval"}),
        tier=int(tier),
        valid_until=int(time.time()) + 600,
        nonce=int.from_bytes(os.urandom(7), "big"),
    )


def commit(chain: FujiChain, intent: PaymentIntent) -> TxRef:
    return chain.commit(intent, sign(intent, chain.domain(), dev_key("router_signer")))


def confirm(chain: FujiChain, intent: PaymentIntent) -> None:
    att = VerificationAttestation(
        payment_id=intent.payment_id,
        intent_hash=to_hex(digest(intent, chain.domain())),
        method=int(VerificationMethod.OOB_KNOWN_CONTACT),
        result=int(VerificationResult.CONFIRMED),
        sim_swap_checked=True,
        evidence_hash=hash_record({"paymentId": intent.payment_id}),
        verified_at=int(time.time()),
        nonce=int.from_bytes(os.urandom(7), "big"),
    )
    chain.record_verification(att, sign(att, chain.domain(), dev_key("verifier_signer")))
