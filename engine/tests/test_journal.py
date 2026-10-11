"""Hash-chained decision log and proof endpoint (roadmap A1.6)."""

import json

from sylo_spec.eip712 import recover
from sylo_spec.models import PaymentIntent

from sylo import journal as journal_module
from sylo.journal import GENESIS, Journal, verify

from .conftest import make_orchestrator


def test_entries_chain_and_any_edit_is_detected(tmp_path):
    path = tmp_path / "log.jsonl"
    log = Journal(path)
    for n in range(4):
        log.append("risk.scored", {"paymentId": "PAY-1", "score": 10 + n})
    entries = journal_module.read(path)
    assert entries[0]["prevHash"] == GENESIS and [e["seq"] for e in entries] == [1, 2, 3, 4]
    assert all(entries[i]["prevHash"] == entries[i - 1]["hash"] for i in range(1, 4))
    assert verify(entries)[0] and journal_module.main(["verify", str(path)]) == 0

    edited = json.loads(json.dumps(entries))
    edited[1]["payload"]["score"] = 99
    ok, message = verify(edited)
    assert not ok and "line 2" in message
    assert not verify(entries[:1] + entries[2:])[0], "a removed line breaks the chain"

    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace('"score": 12', '"score": 0')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert journal_module.main(["verify", str(path)]) == 1


def test_an_existing_log_is_continued_and_a_damaged_one_is_set_aside(tmp_path):
    path = tmp_path / "log.jsonl"
    Journal(path).append("a", {"n": 1})
    second = Journal(path)
    second.append("b", {"n": 2})
    assert verify(journal_module.read(path)) == (True, f"2 entries, chain intact, head {second.head}")

    path.write_text("not json\n", encoding="utf-8")
    fresh = Journal(path)
    assert fresh.head == GENESIS and (tmp_path / "log.jsonl.damaged").exists()
    assert journal_module.main(["verify", str(tmp_path / "missing.jsonl")]) == 1


async def test_every_event_is_logged_and_the_engine_writes_the_file(tmp_path):
    path = tmp_path / "data" / "log.jsonl"
    orchestrator = make_orchestrator(journal_path=str(path))
    await orchestrator.run_to_end("legit")
    entries = journal_module.read(path)
    assert [e["type"] for e in entries] == [e["type"] for e in orchestrator.bus.events]
    assert verify(entries)[0] and entries[-1]["hash"] == orchestrator.journal.head


async def test_proof_lets_an_auditor_recompute_and_check_the_signatures():
    orchestrator = make_orchestrator()
    await orchestrator.run_to_end("diverted", auto_answer="deny")
    proof = await orchestrator.proof("PAY-2026-0002")
    assert proof["chainStatus"] == "REVOKED" and proof["simulated"] is True
    assert [s["type"] for s in proof["signed"]] == ["PaymentIntent", "VerificationAttestation", "Revocation"]
    assert [s["role"] for s in proof["signed"]] == ["router_signer", "verifier_signer", "analyst_signer"]

    domain = orchestrator.chain.domain()
    signed_intent = proof["signed"][0]
    intent = PaymentIntent.model_validate(signed_intent["typedData"]["message"])
    assert recover(intent, domain, bytes.fromhex(signed_intent["signature"][2:])) == signed_intent["signer"]
    committed = next(e for e in orchestrator.bus.events if e["type"] == "intent.committed")
    assert signed_intent["digest"] == committed["data"]["intentHash"]

    assert [t["event"] for t in proof["transactions"]] == [
        "intent.committed",
        "escrow.deposited",
        "verification.recorded",
        "intent.revoked",
        "escrow.refunded",
    ]
    assert proof["approval"]["approvalHash"] == intent.approval_hash and len(proof["approval"]["records"]) == 2
    assert proof["offchain"]["fields"]["account"] == "GH•• •••• 9083" and len(proof["offchain"]["salt"]) == 66
    assert verify(orchestrator.journal.entries)[0] and proof["logHead"] == orchestrator.journal.head
    assert [e["payload"]["eventId"] for e in proof["log"]] == [e["id"] for e in orchestrator.bus.events]
