"""Guardian (C2.1) on a throwaway Anvil chain: forged confirmations are frozen before the thief's release."""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from conftest import AnvilDeployment, commit, confirm, make_intent
from sylo_chain.envfile import load_env_file
from sylo_chain.guardian import EngineRecords, EngineUnavailable, Guardian
from sylo_chain.stolen_verifier_key import forge_confirmation, try_release
from sylo_spec.canonical import hash_record, keccak_text, to_hex
from sylo_spec.devkeys import dev_address, dev_key
from sylo_spec.eip712 import digest, sign
from sylo_spec.models import PaymentIntent, VerificationAttestation, VerificationMethod, VerificationResult
from web3 import Web3

KNOWN = [dev_address(name) for name in ("deployer", "relayer", "router_signer", "verifier_signer", "analyst_signer", "guardian")]


class FakeRecords:
    def __init__(self, digests: set[str] | None = None, down: bool = False) -> None:
        self.digests = digests or set()
        self.down = down
        self.posted: list[dict[str, Any]] = []

    def order_id(self, chain_pid: str) -> str | None:
        return None

    def attestation_digests(self, chain_pid: str) -> set[str]:
        if self.down:
            raise EngineUnavailable("ConnectionError")
        return self.digests

    def post_incident(self, body: dict[str, Any]) -> None:
        self.posted.append(body)


def held_payment(anvil: AnvilDeployment) -> PaymentIntent:
    chain = anvil.chain()
    intent = make_intent(chain, anvil.token)
    commit(chain, intent)
    chain.deposit(intent, dev_address("eu_casp"))
    return intent


def guardian_for(anvil: AnvilDeployment, records: FakeRecords, **chain_options: Any) -> Guardian:
    return Guardian(anvil.chain(**chain_options), records, known_callers=KNOWN)


def receipt_status(anvil: AnvilDeployment, tx_hash: str) -> int:
    return int(Web3(Web3.HTTPProvider(anvil.rpc_url)).eth.get_transaction_receipt(tx_hash)["status"])


def test_freezes_a_confirmation_the_engine_never_signed_and_the_release_reverts(anvil: AnvilDeployment) -> None:
    intent = held_payment(anvil)
    records = FakeRecords()
    guardian = guardian_for(anvil, records, rpc_urls=[anvil.rpc_url, anvil.rpc_url])
    thief = anvil.chain()

    forged = forge_confirmation(thief, intent.payment_id, dev_key("verifier_signer"))
    [incident] = guardian.poll_once()

    assert incident.rule == "CONFIRMED_WITHOUT_OOB_RECORD"
    assert incident.action == "FREEZE_AND_PAUSE" and len(incident.action_txs) == 2
    assert incident.tx_hash == forged.tx_hash and incident.payment_id == intent.payment_id.lower()
    assert thief.hold(intent.payment_id)["frozen"] and thief.corridor_paused(intent.corridor_id)

    released, reason, tx = try_release(thief, intent.payment_id)
    assert not released and reason == "PaymentNotReleasable"
    assert tx is not None and receipt_status(anvil, tx.tx_hash) == 0
    assert guardian.poll_once() == []

    [posted] = records.posted
    assert posted["rule"] == "CONFIRMED_WITHOUT_OOB_RECORD" and posted["action"] == "FREEZE_AND_PAUSE"
    assert posted["txHash"] == forged.tx_hash and posted["simulated"] is True and "paymentId" not in posted


def test_leaves_a_confirmation_the_engine_signed_alone(anvil: AnvilDeployment) -> None:
    intent = held_payment(anvil)
    engine = anvil.chain()
    attestation = VerificationAttestation(
        payment_id=intent.payment_id,
        intent_hash=to_hex(digest(intent, engine.domain())),
        method=int(VerificationMethod.OOB_KNOWN_CONTACT),
        result=int(VerificationResult.CONFIRMED),
        sim_swap_checked=True,
        evidence_hash=hash_record({"paymentId": intent.payment_id, "answer": "confirm"}),
        verified_at=int(time.time()),
        nonce=int.from_bytes(os.urandom(7), "big"),
    )
    records = FakeRecords({to_hex(digest(attestation, engine.domain())).lower()})
    guardian = guardian_for(anvil, records)

    engine.record_verification(attestation, sign(attestation, engine.domain(), dev_key("verifier_signer")))
    assert guardian.poll_once() == []
    engine.release(intent.payment_id)
    assert guardian.poll_once() == [] and records.posted == []


def test_freezes_when_the_engine_cannot_be_asked(anvil: AnvilDeployment) -> None:
    intent = held_payment(anvil)
    guardian = guardian_for(anvil, FakeRecords(down=True))
    confirm(anvil.chain(), intent)

    [incident] = guardian.poll_once()
    assert incident.action.startswith("FREEZE") and "engine unreachable" in incident.detail


def test_freeze_only_mode_leaves_the_corridor_open(anvil: AnvilDeployment) -> None:
    intent = held_payment(anvil)
    guardian = Guardian(anvil.chain(), FakeRecords(), known_callers=KNOWN, pause=False)
    forge_confirmation(anvil.chain(), intent.payment_id, dev_key("verifier_signer"))

    [incident] = guardian.poll_once()
    assert incident.action == "FREEZE" and not anvil.chain().corridor_paused(intent.corridor_id)


def test_reports_an_unknown_caller_on_a_privileged_function(anvil: AnvilDeployment) -> None:
    intent = held_payment(anvil)
    guardian = guardian_for(anvil, FakeRecords())
    thief = anvil.chain()

    with pytest.raises(Exception):
        thief.freeze(intent.payment_id, caller="attacker")
    [incident] = guardian.poll_once()
    assert incident.rule == "UNKNOWN_CALLER_ON_PRIVILEGED_FUNCTION"
    assert incident.action == "NONE" and "escrow.freeze" in incident.detail and "refused" in incident.detail


def test_the_guardian_loop_wins_the_race_against_a_waiting_thief(anvil: AnvilDeployment) -> None:
    intent = held_payment(anvil)
    guardian = guardian_for(anvil, FakeRecords())
    stop = threading.Event()
    loop = threading.Thread(target=guardian.run, kwargs={"interval": 0.2, "stop": stop}, daemon=True)
    loop.start()
    try:
        thief = anvil.chain()
        forge_confirmation(thief, intent.payment_id, dev_key("verifier_signer"))
        time.sleep(2.0)
        released, reason, _ = try_release(thief, intent.payment_id)
    finally:
        stop.set()
        loop.join(timeout=10)
    assert not released and reason == "PaymentNotReleasable"
    assert [i.rule for i in guardian.incidents] == ["CONFIRMED_WITHOUT_OOB_RECORD"]


# --- engine records and .env, without a chain ------------------------------------------------------


class _Proofs(BaseHTTPRequestHandler):
    proofs: dict[str, dict[str, Any]] = {}
    incidents: list[dict[str, Any]] = []

    def do_GET(self) -> None:  # noqa: N802
        proof = self.proofs.get(self.path)
        self._answer(200 if proof else 404, proof or {"detail": "unknown payment"})

    def do_POST(self) -> None:  # noqa: N802
        self.incidents.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self._answer(200, {"ok": True})

    def _answer(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        pass


def test_engine_records_match_the_current_run_and_only_verification_digests() -> None:
    second_run = to_hex(keccak_text("PAY-X#2"))
    _Proofs.proofs = {
        "/v1/payments/PAY-X/proof": {
            "chainPaymentId": second_run,
            "signed": [
                {"type": "PaymentIntent", "digest": "0xAA"},
                {"type": "VerificationAttestation", "digest": "0xBB"},
            ],
        }
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Proofs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        records = EngineRecords(f"http://127.0.0.1:{server.server_port}", order_ids=["PAY-X", "PAY-Y"])
        assert records.order_id(second_run.upper().replace("0X", "0x")) == "PAY-X"
        assert records.attestation_digests(second_run) == {"0xbb"}
        assert records.attestation_digests(to_hex(keccak_text("PAY-X"))) == set()  # an older run
        assert records.attestation_digests(to_hex(keccak_text("PAY-Y"))) == set()  # 404
        assert records.attestation_digests("0x" + "12" * 32) == set()  # not an engine payment
        records.post_incident({"rule": "R"})
        assert _Proofs.incidents == [{"rule": "R"}]
    finally:
        server.shutdown()

    with pytest.raises(EngineUnavailable):
        EngineRecords("http://127.0.0.1:9", order_ids=["PAY-X"], timeout=0.5).attestation_digests(second_run)


def test_env_file_keeps_existing_values_and_strips_comments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("# c\nA_SYLO=1   # note\nB_SYLO='x # y'\nexport C_SYLO=3\nD_SYLO=new\n")
    monkeypatch.setenv("D_SYLO", "kept")
    for key in ("A_SYLO", "B_SYLO", "C_SYLO"):
        monkeypatch.delenv(key, raising=False)
    load_env_file(env)
    assert (os.environ["A_SYLO"], os.environ["B_SYLO"], os.environ["C_SYLO"], os.environ["D_SYLO"]) == ("1", "x # y", "3", "kept")
