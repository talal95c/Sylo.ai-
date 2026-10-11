from __future__ import annotations

import asyncio
from threading import Event
from types import SimpleNamespace

from sylo_spec.canonical import corridor_id_of
from sylo_spec.ports import ChainReverted
from sylo_spec.scenarios import CORRIDOR

from sylo import orchestrator as orchestrator_module

from .conftest import make_orchestrator, until

DIVERTED = "PAY-2026-0002"


class _FujiStub:
    mode = "fuji"

    def __init__(self, backing):
        self._backing = backing
        self.calls = []
        self.recorded = Event()
        self.frozen = False
        self.paused_corridors = set()
        self.unpaused_corridors = []
        self.raise_on_unpause = False

    def __getattr__(self, name):
        return getattr(self._backing, name)

    def address(self, role):
        return "0x" + "11" * 20 if role == "attacker" else None

    def record_verification(self, att, verifier_sig, caller="relayer"):
        self.calls.append(("record_verification", caller))
        self.recorded.set()
        return SimpleNamespace(
            tx_hash="0x" + "ab" * 32,
            explorer_url="https://test.snowtrace.io/tx/" + "ab" * 32,
        )

    def hold(self, payment_id):
        return {"frozen": self.frozen}

    def freeze(self, payment_id, caller="analyst"):
        self.calls.append(("freeze", caller))
        self.frozen = True
        return SimpleNamespace(tx_hash="0x" + "cd" * 32, explorer_url=None)

    def pause_corridor(self, corridor_id, caller="guardian"):
        self.calls.append(("pause_corridor", caller))
        self.paused_corridors.add(corridor_id)
        return SimpleNamespace(tx_hash="0x" + "ef" * 32, explorer_url=None)

    def release(self, payment_id, caller="relayer"):
        self.calls.append(("release", caller))
        raise ChainReverted("PaymentNotReleasable", function="release")

    def corridor_paused(self, corridor_id):
        return corridor_id in self.paused_corridors

    def unpause_corridor(self, corridor_id, caller="admin"):
        self.unpaused_corridors.append(corridor_id)
        if self.raise_on_unpause:
            raise RuntimeError("unpause unavailable")
        self.paused_corridors.discard(corridor_id)


async def _held_fuji():
    orchestrator = make_orchestrator(human_steps="auto")
    orchestrator.start("diverted", auto=False)
    run = await until(orchestrator, DIVERTED, "awaiting_supplier")
    chain = _FujiStub(orchestrator.chain)
    orchestrator.chain = chain
    orchestrator.chain_simulated = False
    return orchestrator, run, chain


async def test_fuji_attack_waits_for_the_guardian_and_only_uses_the_attacker_for_attack_calls():
    orchestrator, run, chain = await _held_fuji()

    async def guardian():
        await asyncio.to_thread(chain.recorded.wait)
        await asyncio.sleep(0.01)
        assert run.intent is not None
        chain.frozen = True
        chain.paused_corridors.add(run.intent.corridor_id)
        orchestrator.guardian_incident(
            {
                "rule": "CONFIRMED_WITHOUT_OOB_RECORD",
                "action": "FREEZE_AND_PAUSE",
                "txHash": "0x" + "ab" * 32,
                "explorerUrl": "https://test.snowtrace.io/tx/" + "ab" * 32,
                "paymentId": run.order.id,
                "simulated": False,
            }
        )

    guardian_task = asyncio.create_task(guardian())
    result = await orchestrator.attack("stolen_verifier_key", DIVERTED)
    await guardian_task
    assert orchestrator._task is not None
    await orchestrator._task

    assert result["reverted"] is True
    assert result["reason"] == "PaymentNotReleasable"
    assert ("record_verification", "attacker") in chain.calls
    assert ("release", "attacker") in chain.calls
    assert not any(name in {"freeze", "pause_corridor"} for name, _ in chain.calls)
    assert run.incident_id == result["incidentId"]


async def test_fuji_attack_freezes_and_pauses_before_release_if_guardian_does_not_react(monkeypatch):
    orchestrator, run, chain = await _held_fuji()
    monkeypatch.setattr(orchestrator_module, "GUARDIAN_WAIT_S", 0.01)

    result = await orchestrator.attack("stolen_verifier_key", DIVERTED)
    assert orchestrator._task is not None
    await orchestrator._task

    names = [name for name, _ in chain.calls]
    assert result["reverted"] is True
    assert names.index("freeze") < names.index("pause_corridor") < names.index("release")
    assert run.frozen and run.incident_id == result["incidentId"]
    incident = next(event for event in orchestrator.bus.events if event["type"] == "guardian.incident")
    assert incident["simulated"] is False


async def test_reset_unpauses_current_and_pre_restart_fuji_corridors():
    orchestrator = make_orchestrator()
    chain = _FujiStub(orchestrator.chain)
    orchestrator.chain = chain
    orchestrator.chain_simulated = False
    tracked_corridor = "0x" + "22" * 32
    default_corridor = corridor_id_of(CORRIDOR)
    orchestrator._paused_corridors["R3"] = tracked_corridor
    chain.paused_corridors.update({tracked_corridor, default_corridor})

    await orchestrator.reset()

    assert set(chain.unpaused_corridors) == {tracked_corridor, default_corridor}


async def test_reset_survives_a_failed_fuji_unpause():
    orchestrator = make_orchestrator()
    chain = _FujiStub(orchestrator.chain)
    orchestrator.chain = chain
    orchestrator.chain_simulated = False
    corridor_id = corridor_id_of(CORRIDOR)
    orchestrator._paused_corridors["R3"] = corridor_id
    chain.paused_corridors.add(corridor_id)
    chain.raise_on_unpause = True

    await orchestrator.reset()

    assert chain.unpaused_corridors == [corridor_id]
