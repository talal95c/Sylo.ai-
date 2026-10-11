"""After a restart on a registry that outlives the engine (Fuji): no payment id and no nonce of an earlier
session is used again.

The label scheme of the ids (``id``, ``id#2``, ``id#3``...) is the one Lane C's guardian recomputes, so it
stays as it is: the engine takes the first id the registry does not know. Nonces only have to be unique
per signer, so each session numbers its messages from its own base."""

import pytest

from sylo_spec.canonical import keccak_text, to_hex
from sylo_spec.models import Status

from sylo import orchestrator as orchestrator_module
from sylo.chain_mock import MockChain
from sylo.config import Settings
from sylo.orchestrator import GUARDIAN_KNOWN_RUNS, UnknownPayment, build_orchestrator
from sylo.signer import Signer

from .conftest import LEGIT_SEQUENCE, events_of, make_orchestrator, types

LEGIT = "PAY-2026-0001"
DIVERTED = "PAY-2026-0002"


def restarted(previous, new_nonce_base=True):
    """A new engine process on the registry the previous one used (what a restart on Fuji is)."""
    engine = make_orchestrator()
    engine.chain = previous.chain
    engine.rails = type(previous.rails)(engine.norms.pack, engine.chain, clock=lambda: engine.now().timestamp())
    if new_nonce_base:  # what build_orchestrator does on a chain that outlives the engine
        engine.signer.start_nonces_at(previous.signer.next_nonce("router_signer") + 1_000_000)
    return engine


def guardian_ids(order_id):
    """The ids the guardian knows for an order (chain/sylo_chain/guardian.py, EngineRecords)."""
    return {to_hex(keccak_text(order_id if n == 1 else f"{order_id}#{n}")) for n in range(1, GUARDIAN_KNOWN_RUNS + 1)}


class Counting:
    """Counts the registry reads made while a run looks for its id."""

    def __init__(self, chain):
        self._chain, self.reads = chain, 0

    def __getattr__(self, name):
        return getattr(self._chain, name)

    def status(self, payment_id):
        self.reads += 1
        return self._chain.status(payment_id)


async def test_within_one_session_the_ids_are_the_ones_the_guardian_expects():
    engine = make_orchestrator()
    first = await engine.run_to_end("diverted")
    second = await engine.run_to_end("diverted")
    third = await engine.run_to_end("diverted", auto_answer="confirm")
    assert [run.chain_index for run in (first, second, third)] == [1, 2, 3]
    assert to_hex(first.chain_pid) == to_hex(keccak_text(DIVERTED)) and to_hex(third.chain_pid) == to_hex(keccak_text(f"{DIVERTED}#3"))
    assert not events_of(engine, "tx.reverted")


async def test_the_first_run_after_a_restart_does_not_reuse_an_id_of_an_earlier_session():
    before = make_orchestrator()
    await before.run_to_end("diverted")
    await before.run_to_end("legit")

    after = restarted(before)
    diverted = await after.run_to_end("diverted", auto_answer="confirm")
    legit = await after.run_to_end("legit")
    assert not events_of(after, "tx.reverted"), "commit must not revert InvalidTransition"
    assert (diverted.chain_index, diverted.status) == (2, "credited") and after.chain.status(diverted.chain_pid) == Status.EXECUTED
    assert (legit.chain_index, legit.status) == (2, "credited") and types(after)[-len(LEGIT_SEQUENCE) :] == LEGIT_SEQUENCE
    assert to_hex(diverted.chain_pid) in guardian_ids(DIVERTED) and to_hex(legit.chain_pid) in guardian_ids(LEGIT)
    assert (await after.proof(DIVERTED))["chainPaymentLabel"] == f"{DIVERTED}#2"


async def test_many_earlier_runs_are_skipped_with_few_registry_reads():
    before = make_orchestrator()
    for _ in range(11):
        await before.run_to_end("diverted")

    after = restarted(before)
    after.chain = Counting(after.chain)
    run = await after.run_to_end("diverted")
    looking = after.chain.reads
    assert run.chain_index == 12 and run.status == "stopped" and not events_of(after, "tx.reverted")

    after.chain.reads = 0
    again = await after.run_to_end("diverted")
    assert again.chain_index == 13 and looking <= 20, "doubling then halving, not one read per earlier run"


async def test_an_id_that_was_never_committed_can_be_taken_again():
    before = make_orchestrator()
    before.start_payee_verification("payee-ssx", "acc-mensah-aflao")
    before.record_payee_verification("payee-ssx", "acc-mensah-aflao", "DENIED")
    blocked = await before.run_to_end("diverted")  # stopped before any commit: its id never reached the registry
    assert blocked.chain_index == 1 and before.chain.status(blocked.chain_pid) == Status.NONE

    after = restarted(before)
    run = await after.run_to_end("diverted")
    assert run.chain_index == 1 and after.chain.status(run.chain_pid) == Status.REVOKED


async def test_when_the_registry_cannot_be_read_the_run_keeps_its_id_and_goes_on():
    engine = make_orchestrator()

    class Unreadable(Counting):
        def status(self, payment_id):
            self.reads += 1
            if self.reads == 1:
                raise ConnectionError("rpc down")
            return self._chain.status(payment_id)

    engine.chain = Unreadable(engine.chain)
    engine.rails = type(engine.rails)(engine.norms.pack, engine.chain, clock=lambda: engine.now().timestamp())
    run = await engine.run_to_end("legit")
    assert run.chain_index == 1 and run.status == "credited" and "chain" not in engine.mode()["degraded"]


async def test_a_payment_is_found_by_its_on_chain_id():
    engine = make_orchestrator()
    run = await engine.run_to_end("diverted")
    chain_id = to_hex(run.chain_pid)
    info = await engine.payment_info(chain_id.upper().replace("0X", "0x"))
    assert info["paymentId"] == DIVERTED and info["chainPaymentId"] == chain_id and info["chainRunIndex"] == 1
    proof = await engine.proof(chain_id)
    assert proof["paymentId"] == DIVERTED and proof["chainPaymentId"] == chain_id and proof["log"]
    with pytest.raises(UnknownPayment):
        await engine.payment_info("0x" + "00" * 32)


# --- nonces ------------------------------------------------------------------------------------


def test_a_session_numbers_its_messages_from_its_own_base():
    signer = Signer({})
    assert [signer.next_nonce("router_signer"), signer.next_nonce("router_signer"), signer.next_nonce("analyst_signer")] == [1, 2, 1]
    signer.start_nonces_at(5_000)
    assert [signer.next_nonce(role) for role in ("router_signer", "verifier_signer", "analyst_signer")] == [5_001] * 3


async def test_with_the_nonces_of_an_earlier_session_the_registry_refuses_the_commit():
    before = make_orchestrator()
    await before.run_to_end("diverted")
    after = restarted(before, new_nonce_base=False)
    run = await after.run_to_end("diverted")
    assert run.chain_index == 2, "the id is new"
    assert events_of(after, "tx.reverted")[0]["data"]["reason"] == "NonceUsed" and run.status == "stopped"


async def test_after_a_restart_the_supplier_answer_and_the_revocation_are_accepted_too():
    before = make_orchestrator()
    await before.run_to_end("diverted", auto_answer="deny")  # used one nonce of each signer
    after = restarted(before)
    denied = await after.run_to_end("diverted", auto_answer="deny")
    confirmed = await after.run_to_end("diverted", auto_answer="confirm")
    assert not events_of(after, "tx.reverted")
    assert after.chain.status(denied.chain_pid) == Status.REVOKED and after.chain.status(confirmed.chain_pid) == Status.EXECUTED
    assert [e["data"]["result"] for e in events_of(after, "verification.recorded")] == ["DENIED", "CONFIRMED"]


def test_the_engine_takes_a_new_nonce_base_only_on_a_chain_that_outlives_it(monkeypatch):
    assert build_orchestrator(Settings(), env={}).signer.next_nonce("router_signer") == 1  # mock chain: reproducible

    def persistent_chain(settings, *, signer, clock):
        risk, chain, degraded = load_ports(settings, signer=signer, clock=clock)
        assert isinstance(chain, MockChain)
        chain.mode = "anvil"  # stands for a registry that is still there after a restart
        return risk, chain, degraded

    load_ports = orchestrator_module.load_ports
    monkeypatch.setattr(orchestrator_module, "load_ports", persistent_chain)
    first = build_orchestrator(Settings(), env={}).signer.next_nonce("router_signer")
    second = build_orchestrator(Settings(), env={}).signer.next_nonce("router_signer")
    assert first > 10**15 and second > first, "microseconds since the epoch: later sessions start higher"
