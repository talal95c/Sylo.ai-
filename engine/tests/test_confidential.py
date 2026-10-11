"""eERC confidential chain leg (PRD §13.6, roadmap A3.3): only for a payment that needs no hold."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sylo import texts
from sylo.confidential import (
    ConfidentialReceipt,
    ConfidentialUnavailable,
    EercServiceLeg,
    SimulatedConfidentialLeg,
    load_confidential_leg,
)

from .conftest import events_of, make_orchestrator, types

LEGIT = "PAY-2026-0001"
TRANSFER = "0x" + "13" * 32
EXPLORER = "https://testnet.snowtrace.io"


@pytest.fixture
def eerc_service():
    """A local stand-in for Lane C's service: answers what ``chain/eerc`` documents. No network is touched."""
    state = {"status": 200, "body": None, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["content-length"])))
            state["requests"].append((self.path, request))
            body = state["body"] or {
                "paymentId": request["paymentId"],
                "txs": {"deposit": "0x" + "40" * 32, "transfer": TRANSFER, "withdraw": "0x" + "68" * 32},
                "links": {"transfer": f"{EXPLORER}/tx/{TRANSFER}"},
                "auditor": {"decryptedAmountEur": request["amountEur"]},
                "receiverMetadata": {"paymentId": request["paymentId"]},
            }
            payload = json.dumps(body).encode()
            self.send_response(state["status"])
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    thread.join(timeout=5)


async def test_a_payment_without_a_hold_crosses_the_chain_as_a_confidential_transfer(event_validator):
    orchestrator = make_orchestrator(confidential_mode="simulated")
    assert orchestrator.mode()["confidential"] == "simulated"
    run = await orchestrator.run_to_end("legit")
    sequence = types(orchestrator)
    at = sequence.index("confidential.transfer")
    assert sequence[at - 1] == "leg.sent" and sequence[at + 1] == "leg.settled" and run.status == "credited"
    event = events_of(orchestrator, "confidential.transfer")[0]
    data = event["data"]
    assert event["simulated"] and (data["hop"], data["from"], data["to"]) == (2, "casp_eu", "vasp_gh")
    assert data["token"] == "eEURC" and data["amountHidden"] and data["auditorMatches"] and data["metadataEncrypted"]
    assert data["auditorDecryptedAmountEur"] == 85000.0 and "transfer amount" in data["hidden"] and len(data["visible"]) == 2
    assert "confidential.transfer" in [tx["event"] for tx in (await orchestrator.proof(LEGIT))["transactions"]]
    for emitted in orchestrator.bus.events:
        errors = list(event_validator.iter_errors(emitted))
        assert not errors, f"{emitted['type']}: {errors[0].message}"


async def test_a_held_payment_keeps_the_public_escrow_and_the_leg_is_off_by_default():
    held = make_orchestrator(confidential_mode="simulated")
    await held.run_to_end("diverted", auto_answer="confirm")
    assert not events_of(held, "confidential.transfer") and events_of(held, "escrow.deposited") and events_of(held, "escrow.released")

    default = make_orchestrator()
    await default.run_to_end("legit")
    assert default.mode()["confidential"] == "off" and not events_of(default, "confidential.transfer")


async def test_without_the_confidential_leg_the_payment_goes_on_in_public_and_says_so():
    class Down:
        mode = "eerc"

        def transfer(self, payment_id, amount_eur):
            raise ConfidentialUnavailable("the eERC service did not answer (TimeoutError)")

    orchestrator = make_orchestrator()
    orchestrator.confidential = Down()
    run = await orchestrator.run_to_end("legit")
    assert run.status == "credited" and not events_of(orchestrator, "confidential.transfer")
    assert "confidential" in orchestrator.mode()["degraded"]
    alert = events_of(orchestrator, "alert.raised")[0]["data"]
    assert alert["audience"] == "analyst" and "public transfer" in alert["text"] and "TimeoutError" in alert["text"]


async def test_an_amount_the_auditor_does_not_recognise_stops_the_payment_before_the_next_leg():
    class Wrong:
        mode = "eerc"

        def transfer(self, payment_id, amount_eur):
            return ConfidentialReceipt(TRANSFER, None, 1.0, payment_id, simulated=False)

    orchestrator = make_orchestrator()
    orchestrator.confidential = Wrong()
    run = await orchestrator.run_to_end("legit")
    assert run.status == "stopped" and not events_of(orchestrator, "payment.credited")
    assert not events_of(orchestrator, "confidential.transfer")[0]["data"]["auditorMatches"]
    assert events_of(orchestrator, "payment.stopped")[0]["data"]["headline"] == texts.CONFIDENTIAL_MISMATCH_HEADLINE
    assert types(orchestrator).count("leg.sent") == 3, "no leg after the chain leg"


def test_the_service_client_reads_the_documented_answer(eerc_service):
    receipt = EercServiceLeg(eerc_service["url"], EXPLORER).transfer(LEGIT, 85000.0)
    assert eerc_service["requests"] == [("/transfer", {"paymentId": LEGIT, "amountEur": 85000.0})]
    assert receipt.tx_hash == TRANSFER and receipt.explorer_url == f"{EXPLORER}/tx/{TRANSFER}" and not receipt.simulated
    assert receipt.auditor_amount_eur == 85000.0 and receipt.metadata_payment_id == LEGIT
    assert receipt.deposit_tx_hash == "0x" + "40" * 32 and receipt.withdraw_tx_hash == "0x" + "68" * 32

    eerc_service["body"] = {"txs": {"transfer": TRANSFER}, "auditorDecryptedAmountEur": 12.5}
    shorter = EercServiceLeg(eerc_service["url"], EXPLORER).transfer(LEGIT, 12.5)
    assert shorter.auditor_amount_eur == 12.5 and shorter.deposit_tx_hash is None and shorter.explorer_url.endswith(TRANSFER)


def test_the_service_client_fails_safe(eerc_service):
    eerc_service["body"] = {"txs": {}}
    with pytest.raises(ConfidentialUnavailable, match="no confidential transfer hash"):
        EercServiceLeg(eerc_service["url"], EXPLORER).transfer(LEGIT, 1.0)
    eerc_service["status"], eerc_service["body"] = 502, {"error": "rpc"}
    with pytest.raises(ConfidentialUnavailable, match="HTTP 502"):
        EercServiceLeg(eerc_service["url"], EXPLORER).transfer(LEGIT, 1.0)
    with pytest.raises(ConfidentialUnavailable, match="did not answer"):
        EercServiceLeg("http://127.0.0.1:9", EXPLORER, timeout=2).transfer(LEGIT, 1.0)
    assert load_confidential_leg("eerc", "ftp://nope", EXPLORER) == (None, True)
    assert load_confidential_leg("mystery", "http://127.0.0.1:8010", EXPLORER) == (None, True)
    assert load_confidential_leg("off", "", EXPLORER) == (None, False)
    assert isinstance(load_confidential_leg("simulated", "", EXPLORER)[0], SimulatedConfidentialLeg)


async def test_with_the_service_the_event_carries_the_real_transaction(eerc_service):
    orchestrator = make_orchestrator(confidential_mode="eerc", eerc_url=eerc_service["url"])
    run = await orchestrator.run_to_end("legit")
    event = events_of(orchestrator, "confidential.transfer")[0]
    assert run.status == "credited" and not event["simulated"] and event["data"]["txHash"] == TRANSFER
    assert event["data"]["explorerUrl"] == f"{EXPLORER}/tx/{TRANSFER}" and event["data"]["depositTxHash"]
