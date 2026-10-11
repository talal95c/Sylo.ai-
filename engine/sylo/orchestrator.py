"""Payment state machine and scenario scripts (v0 spec §5.10, roadmap §7.3).

Every wait goes through the run's pacer, every chain call through ``asyncio.to_thread``, and every
step is published on the bus as an event. The web app only draws these events.

Human steps (payer approvals, the supplier's answer, the analyst's decision) arrive through the API
and resolve what the script is waiting on. A scenario started with ``auto`` answers them itself, and
``HUMAN_STEPS=auto`` (the default) does so for the approvals and the analyst only.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import random
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from eth_utils import to_checksum_address

from sylo_spec.canonical import corridor_id_of, hash_record, keccak_text, offchain_hash, to_hex
from sylo_spec.devkeys import dev_address
from sylo_spec.eip712 import Message, digest, primary_type, typed_data
from sylo_spec.models import (
    CaseFile,
    PaymentIntent,
    PaymentOrder,
    Revocation,
    RevocationReason,
    RiskReason,
    RiskResult,
    Status,
    Tier,
    TxRef,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
    WindowPayment,
)
from sylo_spec.ports import ChainPort, ChainReverted, RiskPort
from sylo_spec.scenarios import ACCOUNTS, CORRIDOR, ORDERS, PAYEES, PAYER, build_risk_context

from . import texts
from .approvals import ApprovalSession, required_approvers
from .breakers import BreakerError, Breakers, apply_breaker, apply_degraded
from .bus import EventBus
from .case import CaseService, rules_case_file
from .clusters import cluster_sample, load_cluster_port, wave_payments
from .config import Settings
from .journal import Journal
from .norms import NormsEngine, NormsResult
from .pacer import Pacer, RealPacer, iso_ms
from .ports_loader import load_case_writer, load_ports
from .rails import LegMessage, LegRejected, RailAdapter, Rails
from .risk_rules import CombinedRisk
from .router import RouteDecision, choose_route
from .signer import Signer
from .telecom import SimSwapMock

log = logging.getLogger("sylo.orchestrator")

DEFAULT_TOKEN = to_checksum_address("0x" + "0" * 37 + "e0c")
TOKEN_DECIMALS = 6
BANK_HOP_MS = 1400
CHAIN_HOP_MS = 2200
APPROVAL_STEP_MS = 600
SUPPLIER_AUTO_MS = 3000
ANALYST_AUTO_MS = 1500
CASE_TIMEOUT_S = 10.0
KILL_REFUSALS = 2
KILL_WINDOW_S = 600.0
CLUSTER_WINDOW_MINUTES = 60
WAVE_STEP_MS = 1300
T = TypeVar("T")


def typed_data_json(message: Message, domain: Any) -> dict[str, Any]:
    """EIP-712 typed data as plain JSON (the form wallets sign): bytes32 as 0x-hex, integers as decimal strings."""
    data = typed_data(message, domain)
    values: dict[str, Any] = {}
    for name, value in data["message"].items():
        if isinstance(value, (bytes, bytearray)):
            values[name] = to_hex(bytes(value))
        elif isinstance(value, int) and not isinstance(value, bool):
            values[name] = str(value)
        else:
            values[name] = value
    return {**data, "message": values}


def action_tier(risk: RiskResult) -> Tier:
    """The tier the response follows. HIGH risk that an out-of-band confirmation can lift is handled like
    MEDIUM (conditional settlement); the tier shown to people stays the model's."""
    return Tier.MEDIUM if risk.tier == Tier.HIGH and risk.oob_resolvable else risk.tier


@dataclass(frozen=True)
class ScenarioDef:
    order: str
    sim_swap_hours_ago: float | None = None
    """When set, the SIM behind the supplier's known number changed that many hours before the run."""
    rail_down: str | None = None
    """When set, that route's rail goes down before the payment and comes back after it (Scene 5)."""


SCENARIOS: dict[str, ScenarioDef] = {
    "legit": ScenarioDef("legit"),
    "diverted": ScenarioDef("diverted"),
    "diverted_simswap": ScenarioDef("diverted", sim_swap_hours_ago=5.0),
    "outage": ScenarioDef("legit", rail_down="R3"),
}
ATTACKS = ("release_revoked", "swap_beneficiary", "replay")
CASE_ACTIONS = ("CONFIRM_REVOCATION", "RELEASE", "FREEZE")
HOLD_MODES = {"ONCHAIN_ESCROW": "escrow", "FIAT_HOLD": "bank"}


class ScenarioBusy(Exception):
    pass


class UnknownScenario(Exception):
    pass


class UnknownPayment(Exception):
    pass


class NotWaiting(Exception):
    pass


class UnknownAttack(Exception):
    pass


class AttackNotApplicable(Exception):
    pass


class UnknownAction(Exception):
    pass


class UnknownRoute(Exception):
    pass


class UnknownBreaker(Exception):
    pass


class ActionNotAllowed(Exception):
    """A case action that makes no sense in the payment's current state. ``str(error)`` says why."""


class ChainUnavailable(Exception):
    """The chain did not answer (network, RPC, client bug): not a revert. ``step`` names the call."""

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


@dataclass
class PaymentRun:
    order: PaymentOrder
    scenario: str
    chain_pid: bytes
    pacer: Pacer
    auto: bool
    auto_answer: str
    status: str = "deciding"
    risk: RiskResult | None = None
    decision: RouteDecision | None = None
    intent: PaymentIntent | None = None
    intent_hash: str | None = None
    intent_signature: bytes | None = None
    salt: bytes | None = None
    hops: list[dict[str, str]] = field(default_factory=list)
    approval: ApprovalSession | None = None
    approval_done: asyncio.Event | None = None
    answer: asyncio.Future[str] | None = None
    analyst: asyncio.Future[str] | None = None
    analyst_by: str = texts.ANALYST
    hold: str | None = None
    hold_hop: int | None = None
    hold_expires_at: str | None = None
    frozen: bool = False
    case: CaseFile | None = None
    case_task: asyncio.Task[None] | None = None
    signed: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0

    @property
    def tier(self) -> Tier | None:
        return self.risk.tier if self.risk else None


class Orchestrator:
    def __init__(
        self,
        *,
        bus: EventBus,
        risk: RiskPort,
        chain: ChainPort,
        signer: Signer,
        norms: NormsEngine,
        settings: Settings,
        pacer_factory: Callable[[float], Pacer] = RealPacer,
        degraded: list[str] | None = None,
        beneficiary: str | None = None,
        payer_address: str | None = None,
        token: str | None = None,
        case: CaseService | None = None,
        journal: Journal | None = None,
    ) -> None:
        self.bus = bus
        self.risk = risk
        self.chain = chain
        self.signer = signer
        self.norms = norms
        self.settings = settings
        self.pacer_factory = pacer_factory
        self.degraded = list(degraded or [])
        self.beneficiary = beneficiary or dev_address("gh_vasp")
        self.payer_address = payer_address or dev_address("eu_casp")
        self.token = token or DEFAULT_TOKEN
        self.case = case or CaseService()
        self.journal = journal or Journal()
        self.boot_id = uuid.uuid4().hex[:12]
        self.chain_simulated = chain.mode != "fuji"
        self.telecom = SimSwapMock(clock=self.now)
        self.rails = Rails(norms.pack, chain, clock=lambda: self.now().timestamp())
        self.breakers = Breakers()
        self.cluster_port, self.cluster_stub = load_cluster_port()
        self.incidents: list[dict[str, Any]] = []
        self._window: list[WindowPayment] = []
        self._announced_breakers: set[str] = set()
        self._rng = random.Random(settings.seed)
        self._runs: dict[str, PaymentRun] = {}
        self._run_counts: dict[str, int] = {}
        self._task: asyncio.Task[None] | None = None
        self._current_pacer: Pacer | None = None

    # --- mode and clock ----------------------------------------------------------------------

    def now(self) -> datetime:
        return self._current_pacer.now() if self._current_pacer else datetime.now(timezone.utc)

    def mode(self) -> dict[str, Any]:
        return {
            "risk": "model" if isinstance(self.risk, CombinedRisk) else "rules",
            "chain": self.chain.mode,
            "llm": self.case.mode,
            "rails": "simulated",
            "degraded": list(self.degraded),
            "bootId": self.boot_id,
            "humanSteps": self.settings.human_steps,
        }

    def mode_event(self) -> dict[str, Any]:
        return {
            "v": 1,
            "seq": 0,
            "id": "evt-000000",
            "ts": iso_ms(datetime.now(timezone.utc)),
            "type": "system.mode",
            "paymentId": None,
            "simulated": False,
            "data": self.mode(),
        }

    def _degrade(self, dependency: str) -> None:
        """A dependency failed while running: say so on the stream, so the banner turns amber."""
        if dependency not in self.degraded:
            self.degraded.append(dependency)
            self.bus.publish("system.mode", self.mode())

    # --- public operations -------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, name: str, *, speed: float = 1.0, auto: bool = False, auto_answer: str = "deny") -> str:
        """Start a scenario in the background and return its payment id."""
        if name not in SCENARIOS:
            raise UnknownScenario(name)
        if self.running:
            raise ScenarioBusy()
        run = self._new_run(name, speed, auto, auto_answer)
        self._task = asyncio.create_task(self._execute(run))
        return run.order.id

    async def run_to_end(self, name: str, *, speed: float = 1.0, auto: bool = True, auto_answer: str = "deny") -> PaymentRun:
        """Run a scenario in the foreground (tests and the fixture recorder)."""
        if name not in SCENARIOS:
            raise UnknownScenario(name)
        if self.running:
            raise ScenarioBusy()
        run = self._new_run(name, speed, auto, auto_answer)
        await self._execute(run)
        if run.case_task is not None:
            await run.case_task
        return run

    def approve(self, payment_id: str, approver_id: str) -> dict[str, Any]:
        """One payer approval. Raises ``ApprovalError`` when this approver cannot approve now."""
        run = self._get(payment_id)
        if run.approval is None or run.approval_done is None or run.approval_done.is_set():
            raise NotWaiting(payment_id)
        run.approval.approve(approver_id, run.pacer.now())
        self._approval_progress(run)
        return {"ok": True, "pending": [approver.id for approver in run.approval.pending]}

    def supplier_response(self, payment_id: str, answer: str) -> None:
        run = self._get(payment_id)
        if run.answer is None or run.answer.done():
            raise NotWaiting(payment_id)
        run.answer.set_result(answer)

    async def case_action(self, payment_id: str, action: str, by: str | None = None) -> dict[str, Any]:
        """An analyst decision on a held payment: confirm the revocation, release, or freeze."""
        if action not in CASE_ACTIONS:
            raise UnknownAction(action)
        run = self._get(payment_id)
        by = by or texts.ANALYST
        if action == "CONFIRM_REVOCATION":
            if run.analyst is None or run.analyst.done():
                raise ActionNotAllowed("this payment is not waiting for an analyst decision")
            run.analyst_by = by
            run.analyst.set_result(action)
            return {"ok": True}
        if run.hold is None:
            raise ActionNotAllowed("this payment is not held")
        if run.frozen:
            raise ActionNotAllowed("this payment is frozen: only a refund to the payer is possible")
        if action == "FREEZE":
            fields: dict[str, Any] = {}
            simulated = True
            if run.hold == "escrow":
                freeze = getattr(self.chain, "freeze", None)
                if freeze is None:
                    raise ActionNotAllowed("this chain client cannot freeze a hold")
                tx = await self._chain("freeze", freeze, run.chain_pid)
                fields, simulated = self._tx_fields(tx), tx.simulated
            run.frozen = True
            self._emit(
                run, "case.action", {"action": action, "by": by, "detail": texts.FROZEN_DETAIL, **fields}, simulated=simulated
            )
            return {"ok": True}
        if run.status != "confirmed":
            raise ActionNotAllowed("release is only possible once the supplier has confirmed")
        self._emit(run, "case.action", {"action": action, "by": by}, simulated=True)
        return {"ok": True}

    async def attack(self, name: str, payment_id: str) -> dict[str, Any]:
        if name not in ATTACKS:
            raise UnknownAttack(name)
        run = self._get(payment_id)
        if name == "release_revoked":
            return await self._attack_release_revoked(run)
        if run.intent is None or run.intent_signature is None or run.decision is None:
            raise AttackNotApplicable("this payment has no committed intent yet")
        if name == "swap_beneficiary":
            return await self._attack_swap_beneficiary(run)
        return await self._attack_replay(run)

    async def reset(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for run in self._runs.values():
            if run.case_task is not None and not run.case_task.done():
                run.case_task.cancel()
        self._task = None
        self._runs.clear()
        self._current_pacer = None
        self.telecom.clear()
        self.rails.reset()
        self.breakers.reset()
        self._window.clear()
        self._announced_breakers.clear()
        self.bus.clear()
        self.bus.publish("session.reset", {})

    async def payment_info(self, payment_id: str) -> dict[str, Any]:
        run = self._get(payment_id)
        chain_status = Status(int(await asyncio.to_thread(self.chain.status, run.chain_pid)))
        return {
            "paymentId": payment_id,
            "status": run.status,
            "tier": run.tier.name if run.tier is not None else None,
            "routeId": run.decision.route.id if run.decision and run.decision.route else None,
            "chainStatus": chain_status.name,
            "lastSeq": run.last_seq,
            "scenario": run.scenario,
            "pendingApprovers": [a.id for a in run.approval.pending] if run.approval else [],
            "hold": run.hold,
            "holdExpiresAt": run.hold_expires_at,
            "frozen": run.frozen,
            "caseReady": run.case is not None,
        }

    async def proof(self, payment_id: str) -> dict[str, Any]:
        """Everything an auditor needs to recompute the payment: typed data, signatures, transactions, log."""
        run = self._get(payment_id)
        chain_status = Status(int(await asyncio.to_thread(self.chain.status, run.chain_pid)))
        approval = None
        if run.approval is not None:
            approval = {
                "method": run.approval.method,
                "conditional": run.approval.conditional,
                "records": [record.to_event() for record in run.approval.records],
                "approvalHash": run.intent.approval_hash if run.intent else None,
            }
        return {
            "paymentId": payment_id,
            "chainPaymentId": to_hex(run.chain_pid),
            "chainStatus": chain_status.name,
            "simulated": self.chain_simulated,
            "domain": self.chain.domain().to_json_dict(),
            "signed": list(run.signed),
            "offchain": {"salt": to_hex(run.salt), "fields": self._offchain_fields(run.order)} if run.salt else None,
            "approval": approval,
            "transactions": list(run.transactions),
            "log": self.journal.for_payment(payment_id),
            "logHead": self.journal.head,
        }

    # --- network defence and incidents (v2) --------------------------------------------------

    def _publish(self, type_: str, data: dict[str, Any], *, payment_id: str | None = None, simulated: bool = True) -> None:
        """An event that belongs to the session rather than to one payment's run."""
        self.bus.publish(type_, data, payment_id=payment_id, simulated=simulated, ts=self.now())

    def rail_down(self, route_id: str, reason: str | None = None) -> dict[str, Any]:
        """Simulated outage: the rail cannot be used, so payments are rerouted. It never changes a tier."""
        adapter = self.rails.get(route_id)
        if adapter is None:
            raise UnknownRoute(route_id)
        adapter.down_reason = reason or texts.RAIL_DOWN_REASON
        self._publish("rail.down", {"routeId": adapter.id, "name": adapter.name, "reason": adapter.down_reason})
        return {"ok": True, "routeId": adapter.id, "available": adapter.available}

    def rail_up(self, route_id: str) -> dict[str, Any]:
        """The rail is back. This also restores an adapter cut by the kill switch (its keys were rotated)."""
        adapter = self.rails.get(route_id)
        if adapter is None:
            raise UnknownRoute(route_id)
        adapter.restore()
        self._publish("rail.up", {"routeId": adapter.id, "name": adapter.name})
        return {"ok": True, "routeId": adapter.id, "available": adapter.available}

    def start_wave(self, *, speed: float = 1.0, auto: bool = False) -> dict[str, Any]:
        """Scene 3: three payments from other payers reach accounts of one mule cluster."""
        if self.running:
            raise ScenarioBusy()
        self._task = asyncio.create_task(self._wave(self.pacer_factory(speed), auto))
        return {"ok": True, "payments": [payment["paymentId"] for payment in wave_payments()]}

    async def run_wave(self, *, speed: float = 1.0, auto: bool = True) -> None:
        """The mule wave in the foreground (tests and the fixture recorder)."""
        if self.running:
            raise ScenarioBusy()
        await self._wave(self.pacer_factory(speed), auto)

    def confirm_breaker(self, breaker_id: str, by: str | None = None) -> dict[str, Any]:
        """The analyst switches a proposed circuit breaker on, for 24 hours."""
        try:
            breaker = self.breakers.confirm(breaker_id, by or texts.ANALYST, self.now())
        except KeyError:
            raise UnknownBreaker(breaker_id) from None
        except BreakerError as err:
            raise ActionNotAllowed(str(err)) from None
        self._publish("breaker.on", breaker.on_event())
        return {"ok": True, "breakerId": breaker.id, "expiresAt": breaker.on_event()["expiresAt"]}

    def lift_breaker(self, breaker_id: str, by: str | None = None) -> dict[str, Any]:
        """Only a person lifts a breaker before its 24 hours are over."""
        try:
            breaker = self.breakers.lift(breaker_id)
        except KeyError:
            raise UnknownBreaker(breaker_id) from None
        except BreakerError as err:
            raise ActionNotAllowed(str(err)) from None
        self._publish("breaker.off", {"breakerId": breaker.id, "reason": "LIFTED", "by": by or texts.ANALYST})
        return {"ok": True, "breakerId": breaker.id}

    def guardian_incident(self, report: dict[str, Any]) -> dict[str, Any]:
        """An on-chain incident reported by the guardian (Lane C): show it and draft the DORA incident report."""
        payment_id = report.get("paymentId")
        run = self._runs.get(payment_id) if isinstance(payment_id, str) else None
        incident_id = str(report.get("incidentId") or f"INC-{self.now():%Y%m%d}-{len(self.incidents) + 1:03d}")
        action = str(report.get("action") or "NONE")
        dora = {
            "clientsAffected": int(report.get("clientsAffected", 1 if run else 0)),
            "amountEur": float(report.get("amountEur", run.order.amount.as_float if run else 0.0)),
            "durationMinutes": float(report.get("durationMinutes", 0.0)),
            "geographicSpread": list(report.get("geographicSpread") or (["FR", "GH"] if run else [])),
            "criticality": str(report.get("criticality") or texts.DORA_CRITICALITY),
            "thirdParties": list(report.get("thirdParties") or ["Avalanche RPC providers"]),
            "major": bool(report.get("major", False)),
            "draft": True,
        }
        rule = str(report.get("rule") or "UNKNOWN")
        data = {
            "incidentId": incident_id,
            "rule": rule,
            "txHash": report.get("txHash"),
            "explorerUrl": report.get("explorerUrl"),
            "action": action,
            "headline": texts.GUARDIAN_HEADLINE.format(rule=rule),
            "dora": dora,
        }
        if run is not None and run.hold is not None and "FREEZE" in action.upper():
            run.frozen = True  # the guardian froze the hold on-chain: the engine must not try to release it
        self._publish(
            "guardian.incident",
            data,
            payment_id=run.order.id if run else None,
            simulated=bool(report.get("simulated", self.chain_simulated)),
        )
        draft = {**data, "paymentId": run.order.id if run else None, "receivedAt": iso_ms(self.now()), "status": "DRAFT, not filed"}
        self.incidents.append(draft)
        if self.settings.journal_path:
            folder = Path(self.settings.journal_path).parent / "incidents"
            folder.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in incident_id)
            (folder / f"{safe}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "incidentId": incident_id}

    async def _wave(self, pacer: Pacer, auto: bool) -> None:
        self._current_pacer = pacer
        try:
            self._publish("scenario.started", {"scenario": "mule_wave", "speed": pacer.speed, "auto": auto}, simulated=False)
            institution = cluster_sample()["institutions"][0]
            for payment in wave_payments():
                await pacer.wait(WAVE_STEP_MS)
                # Seen on the network, not routed by this engine: traffic, not a payment.created of ours.
                self._publish(
                    "traffic.sample",
                    {
                        "arcs": [{"from": PAYER.bank_institution_id, "to": institution, "kind": "bank"}],
                        "wave": True,
                        "uetr": payment["uetr"],
                        "payer": {"id": payment["payer"]["id"], "name": payment["payer"]["name"]},
                        "beneficiary": {
                            "payeeName": payment["payeeName"],
                            "accountHolder": payment["accountHolder"],
                            "accountMasked": payment["accountMasked"],
                            "institutionId": institution,
                        },
                        "amount": {"value": payment["amount"], "currency": "EUR"},
                        "text": texts.WAVE_PAYMENT.format(
                            payer=payment["payer"]["name"], amount=texts.eur(float(payment["amount"])), holder=payment["accountHolder"]
                        ),
                    },
                    payment_id=payment["paymentId"],
                )
                self._observe(
                    payment["paymentId"],
                    payment["accountId"],
                    institution,
                    float(payment["amount"]),
                    payer_id=payment["payer"]["id"],
                )
                await self._detect_clusters(pacer, auto or self.settings.human_steps != "manual")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mule wave failed")

    def _observe(
        self,
        payment_id: str,
        account_id: str,
        institution_id: str,
        amount_eur: float,
        *,
        payer_id: str | None = None,
    ) -> None:
        """Remember a payment for the cluster detector (last hour; a re-run of the same payment counts once)."""
        now = self.now()
        cutoff = now - timedelta(minutes=CLUSTER_WINDOW_MINUTES)
        self._window = [
            payment
            for payment in self._window
            if payment.payment_id != payment_id and datetime.fromisoformat(payment.at.replace("Z", "+00:00")) >= cutoff
        ]
        account = ACCOUNTS.get(account_id)
        account_age_days = None
        if account is not None:
            try:
                first_seen = datetime.fromisoformat(account.first_seen.replace("Z", "+00:00"))
                if first_seen.tzinfo is None:
                    first_seen = first_seen.replace(tzinfo=timezone.utc)
                account_age_days = max((now - first_seen).total_seconds() / 86400, 0.0)
            except (TypeError, ValueError):
                account_age_days = None
        self._window.append(
            WindowPayment(
                payment_id=payment_id,
                account_id=account_id,
                institution_id=institution_id,
                amount_eur=amount_eur,
                at=iso_ms(now),
                payer_id=payer_id,
                account_age_days=account_age_days,
                successful_payments=account.successful_payments if account is not None else None,
            )
        )

    async def _detect_clusters(self, pacer: Pacer, auto_confirm: bool) -> None:
        """Ask the cluster detector; a new cluster proposes a circuit breaker that the analyst confirms."""
        try:
            clusters = await asyncio.to_thread(self.cluster_port.detect, list(self._window))
        except Exception as err:
            log.warning("cluster detector failed (%s); no breaker proposed", err)
            return
        for cluster in clusters:
            breaker = self.breakers.propose(cluster, CORRIDOR)
            if breaker.status != "proposed" or breaker.id in self._announced_breakers:
                continue
            self._announced_breakers.add(breaker.id)
            await pacer.wait(700)
            self._publish(
                "cluster.detected",
                {
                    "clusterId": cluster.cluster_id,
                    "accounts": len(cluster.accounts),
                    "agents": len(cluster.agents),
                    "region": cluster.region,
                    "regionName": cluster.region_name or cluster.region,
                    "institutions": list(cluster.institutions),
                    "centroid": cluster.centroid.to_json_dict(),
                    "points": [point.to_json_dict() for point in cluster.points],
                    "linkedPayments": list(cluster.linked_payments),
                    "detector": getattr(self.cluster_port, "name", "unknown"),
                    "proposedBreaker": breaker.proposal(),
                },
            )
            if auto_confirm:
                await pacer.wait(ANALYST_AUTO_MS)
                if breaker.status == "proposed":
                    self.confirm_breaker(breaker.id, texts.REVOKED_BY)

    def _overlays(self, order: PaymentOrder, risk: RiskResult) -> RiskResult:
        """Circuit breaker and degraded mode. They can only make the decision stricter."""
        for expired in self.breakers.expire(self.now()):
            self._publish("breaker.off", {"breakerId": expired.id, "reason": "EXPIRED"})
        account = ACCOUNTS.get(order.creditor_account_id)
        payee = PAYEES.get(order.payee_id)
        institution = account.institution_id if account else order.creditor.institution_id
        breaker = self.breakers.active_for(institution, order.corridor)
        if breaker is not None:
            risk = apply_breaker(risk, breaker)
        return apply_degraded(risk, self.degraded, bool(account and payee and payee.owns(account.id)))

    def _check_kill_switch(self, adapter: RailAdapter) -> None:
        """Two legs changed or replayed on one adapter within ten minutes cut that adapter (roadmap A2.3)."""
        if adapter.killed_reason is not None:
            return
        refusals = adapter.integrity_refusals(KILL_WINDOW_S)
        if refusals < KILL_REFUSALS:
            return
        adapter.killed_reason = texts.KILL_SWITCH_REASON.format(refusals=refusals, minutes=KILL_WINDOW_S / 60)
        affected = [
            run
            for run in self._runs.values()
            if run.decision is not None
            and run.decision.route is not None
            and run.decision.route.id == adapter.id
            and run.hold is not None
            and run.analyst is not None
            and not run.analyst.done()
        ]
        self._publish(
            "killswitch.on",
            {
                "adapter": adapter.id,
                "name": adapter.name,
                "reason": adapter.killed_reason,
                "refusals": refusals,
                "windowSeconds": KILL_WINDOW_S,
                "revoked": [run.order.id for run in affected],
            },
        )
        for run in affected:
            # The run's own script revokes and refunds: it is waiting on this decision.
            run.analyst_by = texts.KILL_SWITCH_BY
            run.analyst.set_result("KILL_SWITCH")

    # --- internals ---------------------------------------------------------------------------

    def _get(self, payment_id: str) -> PaymentRun:
        run = self._runs.get(payment_id)
        if run is None:
            raise UnknownPayment(payment_id)
        return run

    def _new_run(self, name: str, speed: float, auto: bool, auto_answer: str) -> PaymentRun:
        scenario = SCENARIOS.get(name)
        if scenario is None:
            raise UnknownScenario(name)
        order = ORDERS[scenario.order]
        count = self._run_counts.get(order.id, 0) + 1
        self._run_counts[order.id] = count
        label = order.id if count == 1 else f"{order.id}#{count}"
        run = PaymentRun(
            order=order,
            scenario=name,
            chain_pid=keccak_text(label),
            pacer=self.pacer_factory(speed),
            auto=auto,
            auto_answer=auto_answer,
        )
        self._runs[order.id] = run
        return run

    def _auto_humans(self, run: PaymentRun) -> bool:
        """Whether the script plays the payer approvals and the analyst itself."""
        return run.auto or self.settings.human_steps != "manual"

    def _emit(self, run: PaymentRun, type_: str, data: dict[str, Any], *, simulated: bool = False) -> None:
        event = self.bus.publish(type_, data, payment_id=run.order.id, simulated=simulated, ts=run.pacer.now())
        run.last_seq = event["seq"]
        if data.get("txHash"):
            run.transactions.append(
                {
                    "event": type_,
                    "eventId": event["id"],
                    "txHash": data["txHash"],
                    "explorerUrl": data.get("explorerUrl"),
                    "simulated": simulated,
                }
            )

    def _alert(self, run: PaymentRun, audience: str, to: str, channel: str, text: str, **extra: Any) -> None:
        """Tell a person or an institution. Payers and suppliers are reached in the app or by SMS, never by e-mail."""
        assert channel in texts.ALERT_CHANNELS, channel
        self._emit(
            run, "alert.raised", {"audience": audience, "to": to, "channel": channel, "text": text, **extra}, simulated=True
        )

    async def _chain(self, step: str, fn: Callable[..., T], *args: Any) -> T:
        try:
            return await asyncio.to_thread(fn, *args)
        except (ChainReverted, LegRejected):
            raise
        except Exception as err:
            raise ChainUnavailable(step) from err

    def _tx_fields(self, tx: TxRef) -> dict[str, Any]:
        return {"txHash": tx.tx_hash, "explorerUrl": tx.explorer_url}

    def _reverted(self, run: PaymentRun, err: ChainReverted, function: str | None = None) -> None:
        self._emit(
            run,
            "tx.reverted",
            {
                "function": function or err.function or "unknown",
                "reason": err.reason,
                "txHash": err.tx.tx_hash if err.tx else None,
                "explorerUrl": err.tx.explorer_url if err.tx else None,
            },
            simulated=self.chain_simulated,
        )

    def _sign(self, run: PaymentRun, role: str, message: Message) -> bytes:
        """Sign with a role key and keep what an auditor needs to check the signature."""
        domain = self.chain.domain()
        signature = self.signer.sign(role, message, domain)
        run.signed.append(
            {
                "type": primary_type(message),
                "role": role,
                "signer": self.signer.address(role),
                "typedData": typed_data_json(message, domain),
                "digest": to_hex(digest(message, domain)),
                "signature": to_hex(signature),
            }
        )
        return signature

    async def _execute(self, run: PaymentRun) -> None:
        self._current_pacer = run.pacer
        try:
            await self._script(run)
        except asyncio.CancelledError:
            raise
        except ChainReverted as err:
            log.warning("chain refused %s: %s", err.function, err.reason)
            self._reverted(run, err)
            run.status = "stopped"
            self._emit(
                run,
                "payment.stopped",
                {
                    "headline": texts.CHAIN_REFUSED_HEADLINE,
                    "detail": texts.CHAIN_REFUSED_DETAIL.format(function=err.function, reason=err.reason),
                },
                simulated=self.chain_simulated,
            )
        except ChainUnavailable as err:
            # Fail safe: nothing is released by default. Money already in escrow stays there.
            log.exception("chain unavailable during %s", err.step)
            self._degrade("chain")
            detail = texts.CHAIN_DOWN_DETAIL.format(step=err.step)
            self._alert(run, "analyst", texts.ANALYST, "IN_APP", detail, headline=texts.CHAIN_DOWN_HEADLINE)
            if run.hold is not None:
                run.status = "held"
            else:
                run.status = "stopped"
                self._emit(run, "payment.stopped", {"headline": texts.CHAIN_DOWN_HEADLINE, "detail": detail})
        except Exception:
            log.exception("scenario %s failed", run.scenario)
            run.status = "stopped"

    def _payment_created(self, order: PaymentOrder) -> dict[str, Any]:
        account = ACCOUNTS[order.creditor_account_id]
        payee = PAYEES.get(order.payee_id)
        data: dict[str, Any] = {
            "uetr": order.uetr,
            "payer": {"id": PAYER.id, "name": PAYER.name, "institutionId": PAYER.institution_id},
            "beneficiary": {
                "payeeName": payee.legal_name if payee else order.creditor.name,
                "accountHolder": account.holder_name,
                "accountMasked": account.account_masked,
                "institutionId": account.institution_id,
                "knownPayee": payee is not None,
                "knownAccount": bool(payee and payee.owns(account.id)),
            },
            "amount": {"value": order.amount.value, "currency": order.amount.currency},
            "purpose": order.purpose,
            "invoiceRef": order.documents.invoice_ref,
            "provenance": order.provenance.get("creditorAccount", "unknown"),
        }
        if order.documents.sender_domain:
            data["senderDomain"] = order.documents.sender_domain
        return data

    @staticmethod
    def _offchain_fields(order: PaymentOrder) -> dict[str, Any]:
        """The private fields behind ``intent.offchainHash`` (the rail adapters rebuild them from each leg)."""
        account = ACCOUNTS[order.creditor_account_id]
        return {
            "creditorName": account.holder_name,
            "account": account.account_masked,
            "bank": account.institution_id,
            "invoiceRef": order.documents.invoice_ref,
            "uetr": order.uetr,
        }

    def _build_intent(
        self, run: PaymentRun, norms: NormsResult, risk: RiskResult, decision: RouteDecision, approval_hash: str
    ) -> PaymentIntent:
        order = run.order
        run.salt = self._rng.randbytes(32)
        decision_hash = hash_record(
            {
                "paymentId": order.id,
                "packVersion": norms.pack_version,
                "routeId": decision.route.id if decision.route else None,
                "routeScores": decision.scores,
                "tier": risk.tier.name,
                "score": risk.score,
                "rulesFired": risk.rules_fired,
                "oobResolvable": risk.oob_resolvable,
                "model": risk.model,
            }
        )
        return PaymentIntent(
            payment_id=to_hex(run.chain_pid),
            corridor_id=corridor_id_of(order.corridor),
            beneficiary=self.beneficiary,
            token=self.token,
            amount=int(Decimal(order.amount.value) * 10**TOKEN_DECIMALS),
            offchain_hash=offchain_hash(run.salt, self._offchain_fields(order)),
            decision_hash=decision_hash,
            approval_hash=approval_hash,
            tier=int(action_tier(risk)),
            valid_until=int(run.pacer.now().timestamp()) + 600,
            nonce=self.signer.next_nonce("router_signer"),
        )

    def _leg_message(self, run: PaymentRun, index: int, hop: dict[str, str]) -> LegMessage:
        assert run.intent is not None and run.salt is not None and run.decision is not None
        fields = self._offchain_fields(run.order)
        return LegMessage(
            order_id=run.order.id,
            uetr=run.order.uetr,
            hop=index,
            rail=run.decision.route.id,
            sender=hop["from"],
            receiver=hop["to"],
            kind=hop["kind"],
            amount=run.order.amount,
            creditor_name=fields["creditorName"],
            creditor_account=fields["account"],
            creditor_bank=fields["bank"],
            invoice_ref=fields["invoiceRef"],
            salt=to_hex(run.salt),
            intent=run.intent,
        )

    # --- approval ----------------------------------------------------------------------------

    def _approval_note(self, run: PaymentRun) -> dict[str, Any]:
        assert run.approval is not None
        note = texts.APPROVAL_NOTE_CONDITIONAL if run.approval.conditional else texts.APPROVAL_NOTE_DIRECT
        data = run.approval.required_event(note)
        if run.approval.conditional:
            data["warning"] = texts.APPROVAL_WARNING_UNTRUSTED
        return data

    def _approval_progress(self, run: PaymentRun) -> None:
        assert run.approval is not None and run.approval_done is not None
        if run.approval.complete:
            run.approval_done.set()
        else:
            self._emit(run, "approval.required", self._approval_note(run), simulated=True)

    async def _approve(self, run: PaymentRun, decision: RouteDecision, conditional: bool) -> str:
        """Payer approval with dual control. Returns the approval hash that goes into the intent."""
        order, pacer = run.order, run.pacer
        account = ACCOUNTS[order.creditor_account_id]
        payee = PAYEES.get(order.payee_id)
        approvers, method = required_approvers(
            PAYER,
            order.amount.as_float,
            known_account=bool(payee and payee.owns(account.id)),
            dual_control_eur=self.settings.dual_control_eur,
            new_payee_eur=self.settings.dual_control_new_payee_eur,
        )
        run.approval = ApprovalSession(required=approvers, method=method, conditional=conditional)
        run.approval_done = asyncio.Event()
        run.status = "awaiting_approval"
        self._emit(run, "approval.required", self._approval_note(run), simulated=True)

        if self._auto_humans(run):
            for approver in approvers:
                await pacer.wait(APPROVAL_STEP_MS)
                if any(pending.id == approver.id for pending in run.approval.pending):
                    run.approval.approve(approver.id, pacer.now())
                    self._approval_progress(run)
        await run.approval_done.wait()

        approval_hash = run.approval.approval_hash(
            payment_id=order.id, route_id=decision.route.id, amount=order.amount.value
        )
        run.status = "deciding"
        self._emit(
            run,
            "approval.granted",
            {
                "by": [record.to_event() for record in run.approval.records],
                "method": method,
                "conditional": conditional,
                "approvalHash": approval_hash,
            },
            simulated=True,
        )
        return approval_hash

    # --- the script --------------------------------------------------------------------------

    async def _script(self, run: PaymentRun) -> None:
        pacer, order = run.pacer, run.order
        scenario = SCENARIOS[run.scenario]
        self.telecom.clear()
        if scenario.sim_swap_hours_ago is not None:
            contact = PAYEES[order.payee_id].known_contacts[0]
            self.telecom.declare_swap(contact.msisdn_masked, hours_ago=scenario.sim_swap_hours_ago)

        self._emit(run, "scenario.started", {"scenario": run.scenario, "speed": pacer.speed, "auto": run.auto})
        if scenario.rail_down is not None:
            await pacer.wait(600)
            self.rail_down(scenario.rail_down)
        await pacer.wait(400)
        self._emit(run, "payment.created", self._payment_created(order))
        creditor_account = ACCOUNTS[order.creditor_account_id]
        self._observe(
            order.id,
            creditor_account.id,
            creditor_account.institution_id,
            order.amount.as_float,
            payer_id=order.debtor.id,
        )
        await self._detect_clusters(pacer, self._auto_humans(run))

        await pacer.wait(900)
        norms = self.norms.evaluate(order)
        self._emit(run, "norms.checked", norms.to_event_data())

        await pacer.wait(900)
        risk = self._overlays(order, self.risk.score(order, build_risk_context(order, norms.signal_codes)))
        run.risk = risk
        self._emit(
            run,
            "risk.scored",
            {
                "score": risk.score,
                "tier": risk.tier.name,
                "rulesFired": risk.rules_fired,
                "reasons": [r.to_json_dict() for r in risk.reasons],
                "model": risk.model,
                "oobResolvable": risk.oob_resolvable,
            },
        )

        await pacer.wait(900)
        decision = choose_route(
            norms,
            risk.tier,
            order.amount.as_float,
            self.norms.pack.route_model,
            oob_resolvable=risk.oob_resolvable,
            unavailable=self.rails.unavailable(),
        )
        run.decision = decision
        if decision.route_eval is None:
            run.status = "stopped"
            self._emit(run, "payment.stopped", {"headline": texts.NO_ROUTE_HEADLINE, "detail": decision.reason})
            await self._open_case(run, "blocked")
            return
        run.hops = decision.route_eval.hops
        self._emit(run, "route.selected", decision.to_event_data())

        await pacer.wait(1000)
        conditional = action_tier(risk) == Tier.MEDIUM
        approval_hash = await self._approve(run, decision, conditional)

        await pacer.wait(900)
        intent = self._build_intent(run, norms, risk, decision, approval_hash)
        signature = self._sign(run, "router_signer", intent)
        tx = await self._chain("commit", self.chain.commit, intent, signature)
        run.intent, run.intent_signature = intent, signature
        run.intent_hash = to_hex(digest(intent, self.chain.domain()))
        self._emit(
            run,
            "intent.committed",
            {"intentHash": run.intent_hash, "tier": Tier(intent.tier).name, **self._tx_fields(tx)},
            simulated=tx.simulated,
        )
        run.status = "in_transit"

        adapter = self.rails.adapter(decision.route.id)
        hold_mode = HOLD_MODES.get(decision.settlement or "") if conditional else None
        hold_hop = adapter.hold_hop() if hold_mode else None
        executed = False
        for index, hop in enumerate(run.hops):
            duration = CHAIN_HOP_MS if hop["kind"] == "chain" else BANK_HOP_MS
            await pacer.wait(300)
            leg = self._leg_message(run, index, hop)
            if not await self._send_leg(run, adapter, leg, duration):
                return
            if hold_mode == "escrow" and index == hold_hop:
                if not await self._hold_and_verify(run, intent, index, "escrow"):
                    return
                executed = True
                await pacer.wait(1100)
            else:
                await pacer.wait(duration)
            adapter.settle(leg.idempotency_key)
            self._emit(run, "leg.settled", {"hop": index, "at": hop["to"]}, simulated=True)
            if hold_mode == "bank" and index == hold_hop:
                if not await self._hold_and_verify(run, intent, index, "bank"):
                    return

        if not executed:
            await pacer.wait(400)
            tx = await self._chain(
                "markExecuted", self.chain.mark_executed, run.chain_pid, keccak_text(f"{order.id}:{decision.route.id}")
            )
            self._emit(run, "intent.executed", self._tx_fields(tx), simulated=tx.simulated)

        await pacer.wait(300)
        run.status = "credited"
        self._emit(
            run,
            "payment.credited",
            {
                "at": run.hops[-1]["to"],
                "feesEur": decision.fees_eur,
                "routeCostEur": decision.s_selected,
                "swiftRouteCostEur": decision.s_swift,
                "elapsedLabel": f"{decision.route.eta_label}{texts.ELAPSED_SUFFIX}",
            },
            simulated=True,
        )
        if scenario.rail_down is not None:
            await pacer.wait(1500)
            self.rail_up(scenario.rail_down)

    # --- rails -------------------------------------------------------------------------------

    def _leg_rejected(self, run: PaymentRun, err: LegRejected) -> None:
        leg = err.leg
        self._emit(
            run,
            "leg.rejected",
            {
                "hop": leg.hop,
                "rail": leg.rail,
                "reason": err.reason,
                "from": leg.sender,
                "to": leg.receiver,
                "text": texts.LEG_REJECTED.get(err.reason, err.detail),
            },
            simulated=True,
        )
        self._check_kill_switch(self.rails.adapter(leg.rail))

    async def _send_leg(self, run: PaymentRun, adapter: RailAdapter, leg: LegMessage, duration: float) -> bool:
        """Hand one leg to its rail adapter. Returns False (and stops the payment) when the adapter refuses it."""
        try:
            await self._chain(f"leg {leg.hop}", adapter.initiate, leg)
        except LegRejected as err:
            self._leg_rejected(run, err)
            run.status = "held" if run.hold is not None else "stopped"
            self._emit(
                run,
                "payment.stopped",
                {
                    "headline": texts.LEG_REJECTED_HEADLINE,
                    "detail": texts.LEG_REJECTED_DETAIL.format(rail=adapter.name, hop=leg.hop, reason=err.reason),
                },
                simulated=True,
            )
            return False
        self._emit(
            run,
            "leg.sent",
            {
                "hop": leg.hop,
                "from": leg.sender,
                "to": leg.receiver,
                "kind": leg.kind,
                "rail": leg.rail,
                "durationMs": round(duration / run.pacer.speed),
                "uetr": leg.uetr,
                "intentHash": run.intent_hash,
                "idempotencyKey": leg.idempotency_key,
            },
            simulated=True,
        )
        return True

    # --- hold, out-of-band check, outcome ----------------------------------------------------

    async def _open_case(self, run: PaymentRun, situation: str) -> None:
        """Ask for the analyst's case file. Without a case writer it is built from the rules, at once.

        ``situation`` is where the payment stands: ``held`` (the supplier is asked), ``analyst`` (the
        known contact cannot be trusted) or ``blocked`` (no route at this risk level).
        """
        assert run.risk is not None
        events = [event for event in self.bus.events if event["paymentId"] == run.order.id]
        if self.case.writer is None:
            await run.pacer.wait(700)
            self._case_ready(run, self.case.write(run.order, run.risk, events, situation))
        else:
            run.case_task = asyncio.create_task(self._write_case(run, events, situation))

    async def _write_case(self, run: PaymentRun, events: list[dict[str, Any]], situation: str) -> None:
        assert run.risk is not None
        try:
            case = await asyncio.wait_for(
                asyncio.to_thread(self.case.write, run.order, run.risk, events, situation), timeout=CASE_TIMEOUT_S
            )
        except Exception as err:
            log.warning("case file not ready in time (%s); using the one built from the rules", err)
            self._degrade("llm")
            case = rules_case_file(run.order, run.risk, events, situation)
        self._case_ready(run, case)

    def _case_ready(self, run: PaymentRun, case: CaseFile) -> None:
        run.case = case
        self._emit(run, "case.ready", case.model_dump(by_alias=True, mode="json"))

    async def _await_analyst(self, run: PaymentRun) -> str:
        assert run.analyst is not None
        run.status = "awaiting_analyst"
        if self._auto_humans(run) and not run.analyst.done():
            await run.pacer.wait(ANALYST_AUTO_MS)
            if not run.analyst.done():
                run.analyst_by = texts.REVOKED_BY
                run.analyst.set_result("CONFIRM_REVOCATION")
        return await run.analyst

    async def _await_supplier_or_analyst(self, run: PaymentRun) -> tuple[str, str]:
        """The supplier's answer, unless the analyst revokes first."""
        assert run.analyst is not None
        run.answer = asyncio.get_running_loop().create_future()
        run.status = "awaiting_supplier"
        if run.auto:
            await run.pacer.wait(SUPPLIER_AUTO_MS)
            if not run.answer.done() and not run.analyst.done():
                run.answer.set_result(run.auto_answer)
        await asyncio.wait({run.answer, run.analyst}, return_when=asyncio.FIRST_COMPLETED)
        if run.analyst.done():
            if not run.answer.done():
                run.answer.cancel()
            return "analyst", run.analyst.result()
        return "supplier", run.answer.result()

    async def _hold_and_verify(self, run: PaymentRun, intent: PaymentIntent, hop_index: int, mode: str) -> bool:
        """Hold (escrow or bank), out-of-band check and outcome. Returns True when the money may go on."""
        pacer, order, risk = run.pacer, run.order, run.risk
        assert risk is not None and run.decision is not None
        domain = self.chain.domain()
        bank_name = "Banque Hexagone"
        amount = texts.eur(order.amount.as_float)

        expires = pacer.now() + timedelta(seconds=self.settings.escrow_hold_seconds)
        if mode == "escrow":
            await pacer.wait(1100)
            tx = await self._chain("deposit", self.chain.deposit, intent, self.payer_address)
            expires = pacer.now() + timedelta(seconds=self.settings.escrow_hold_seconds)
            self._emit(
                run,
                "escrow.deposited",
                {"amount": order.amount.value, "token": "tEURC", "expiresAt": iso_ms(expires), **self._tx_fields(tx)},
                simulated=tx.simulated,
            )
        run.hold, run.hold_hop, run.hold_expires_at = mode, hop_index, iso_ms(expires)
        run.analyst = asyncio.get_running_loop().create_future()

        payee = PAYEES[order.payee_id]
        contact = payee.known_contacts[0]
        sim_swap_recent = self.telecom.check(contact.msisdn_masked, self.settings.sim_swap_max_age_hours)
        reasons = list(risk.reasons)
        next_step = texts.NEXT_STEP
        if sim_swap_recent:
            changed = self.telecom.retrieve_date(contact.msisdn_masked)
            hours = (pacer.now() - changed).total_seconds() / 3600 if changed else 0.0
            next_step = texts.NEXT_STEP_ANALYST.format(hours=hours)
            reasons.append(RiskReason(ref="O", text=next_step, rule_id="R-OOB-01"))
        if risk.tier == Tier.HIGH and risk.oob_resolvable:
            next_step = f"{next_step}\n{texts.HIGH_IDENTITY_ONLY_HOLD}"

        await pacer.wait(200)
        run.status = "held"
        self._emit(
            run,
            "payment.held",
            {
                "hop": hop_index,
                "at": mode,
                "tier": risk.tier.name,
                "headline": texts.HELD_HEADLINE,
                "reasons": [r.to_json_dict() for r in reasons],
                "protection": (
                    texts.PROTECTION
                    if mode == "escrow"
                    else texts.PROTECTION_BANK.format(amount=amount, bank=bank_name, payer=PAYER.name)
                ),
                "nextStep": next_step,
                "expiresAt": iso_ms(expires),
            },
            simulated=self.chain_simulated if mode == "escrow" else True,
        )
        self._alert(run, "payer", PAYER.approvers[0].name, "IN_APP", texts.ALERT_HELD)
        await self._open_case(run, "analyst" if sim_swap_recent else "held")

        await pacer.wait(800)
        self._emit(
            run,
            "verification.requested",
            {
                "contactName": contact.name,
                "contactMasked": contact.msisdn_masked,
                "contactSince": contact.since,
                "channel": "ANALYST" if sim_swap_recent else "SMS",
                "simSwapChecked": True,
                "simSwapRecent": sim_swap_recent,
            },
            simulated=True,
        )
        if sim_swap_recent:
            # Rule R-OOB-01: the known number cannot be trusted, so nobody is texted and the analyst decides.
            who, answer = "analyst", await self._await_analyst(run)
        else:
            who, answer = await self._await_supplier_or_analyst(run)

        if who == "analyst":
            await self._stop_held(run, intent, mode, answer, RevocationReason.ANALYST_DECISION)
            return False

        await pacer.wait(800)
        result = VerificationResult.CONFIRMED if answer == "confirm" else VerificationResult.DENIED
        attestation = VerificationAttestation(
            payment_id=intent.payment_id,
            intent_hash=to_hex(digest(intent, domain)),
            method=int(VerificationMethod.OOB_KNOWN_CONTACT),
            result=int(result),
            sim_swap_checked=True,
            evidence_hash=hash_record(
                {"paymentId": order.id, "contact": contact.msisdn_masked, "answer": answer, "simSwapRecent": False}
            ),
            verified_at=int(pacer.now().timestamp()),
            nonce=self.signer.next_nonce("verifier_signer"),
        )
        tx = await self._chain(
            "recordVerification", self.chain.record_verification, attestation, self._sign(run, "verifier_signer", attestation)
        )
        self._emit(
            run,
            "verification.recorded",
            {
                "result": result.name,
                "answerText": texts.ANSWER_CONFIRM if result == VerificationResult.CONFIRMED else texts.ANSWER_DENY,
                **self._tx_fields(tx),
            },
            simulated=True,
        )

        if result == VerificationResult.DENIED:
            await self._stop_held(run, intent, mode, await self._await_analyst(run), RevocationReason.SUPPLIER_DENIED)
            return False

        run.status = "confirmed"
        await pacer.wait(1000)
        if mode == "escrow":
            try:
                tx = await self._chain("release", self.chain.release, run.chain_pid, "relayer")
            except ChainReverted as err:
                # Frozen by the analyst, paused corridor or expired hold: the money stays in escrow.
                self._reverted(run, err, "release")
                await self._stop_held(run, intent, mode, await self._await_analyst(run), RevocationReason.ANALYST_DECISION)
                return False
            run.hold = None
            run.status = "in_transit"
            self._emit(
                run,
                "escrow.released",
                {"to": run.hops[hop_index]["to"], "amount": order.amount.value, **self._tx_fields(tx)},
                simulated=tx.simulated,
            )
            await pacer.wait(300)
            self._emit(run, "intent.executed", self._tx_fields(tx), simulated=tx.simulated)
            return True
        if run.frozen:
            await self._stop_held(run, intent, mode, await self._await_analyst(run), RevocationReason.ANALYST_DECISION)
            return False
        run.hold = None
        run.status = "in_transit"
        return True

    async def _stop_held(
        self, run: PaymentRun, intent: PaymentIntent, mode: str, action: str, reason: RevocationReason
    ) -> None:
        """Stop a held payment after the analyst's decision, or after the kill switch cut its route."""
        bank_name = "Banque Hexagone"
        if action == "KILL_SWITCH":
            reason = RevocationReason.KILL_SWITCH
            detail = texts.STOPPED_DETAIL_KILL if mode == "escrow" else texts.STOPPED_DETAIL_KILL_BANK.format(bank=bank_name)
            alert = texts.ALERT_STOPPED_KILL
        elif reason == RevocationReason.SUPPLIER_DENIED:
            detail = texts.STOPPED_DETAIL if mode == "escrow" else texts.STOPPED_DETAIL_BANK.format(bank=bank_name)
            alert = texts.ALERT_STOPPED
        else:
            detail = texts.STOPPED_DETAIL_ANALYST if mode == "escrow" else texts.STOPPED_DETAIL_ANALYST_BANK.format(bank=bank_name)
            alert = texts.ALERT_STOPPED_ANALYST
        await self._revoke_and_refund(run, intent, reason, mode, detail, alert)

    async def _revoke_and_refund(
        self, run: PaymentRun, intent: PaymentIntent, reason: RevocationReason, mode: str, detail: str, payer_alert: str
    ) -> None:
        """Revoke in the registry, give the money back, tell who must know (analyst decision or kill switch)."""
        pacer, order, risk = run.pacer, run.order, run.risk
        assert risk is not None
        account = ACCOUNTS[order.creditor_account_id]
        if reason != RevocationReason.KILL_SWITCH:
            self._emit(run, "case.action", {"action": "CONFIRM_REVOCATION", "by": run.analyst_by}, simulated=True)

        await pacer.wait(300)
        revocation = Revocation(
            payment_id=intent.payment_id,
            reason_code=int(reason),
            case_hash=hash_record({"paymentId": order.id, "reason": reason.name, "rules": risk.rules_fired}),
            nonce=self.signer.next_nonce("analyst_signer"),
        )
        tx = await self._chain("revoke", self.chain.revoke, revocation, self._sign(run, "analyst_signer", revocation))
        run.status = "held"
        self._emit(
            run,
            "intent.revoked",
            {"reasonCode": reason.name, "by": run.analyst_by, **self._tx_fields(tx)},
            simulated=tx.simulated,
        )
        if mode == "escrow":
            await pacer.wait(1000)
            tx = await self._chain("refund", self.chain.refund, run.chain_pid)
            self._emit(
                run,
                "escrow.refunded",
                {"to": PAYER.institution_id, "amount": order.amount.value, **self._tx_fields(tx)},
                simulated=tx.simulated,
            )
        run.hold = None

        await pacer.wait(1200)
        self._alert(
            run,
            "beneficiary_bank",
            account.institution_id,
            "NETWORK",
            texts.ALERT_FREEZE_REQUEST.format(uetr=order.uetr, account=account.account_masked, holder=account.holder_name),
            uetr=order.uetr,
        )
        await pacer.wait(2000)
        self._alert(run, "payer", PAYER.approvers[0].name, "SMS", payer_alert)
        run.status = "stopped"
        self._emit(run, "payment.stopped", {"headline": texts.STOPPED_HEADLINE, "detail": detail}, simulated=True)

    # --- attacks -----------------------------------------------------------------------------

    def _attack_started(self, run: PaymentRun, name: str) -> None:
        self._current_pacer = run.pacer
        self._emit(
            run,
            "attack.attempted",
            {"attack": name, "description": texts.ATTACK_DESCRIPTIONS[name], "by": "attacker"},
            simulated=self.chain_simulated,
        )

    async def _attack_release_revoked(self, run: PaymentRun) -> dict[str, Any]:
        status = Status(int(await asyncio.to_thread(self.chain.status, run.chain_pid)))
        if status != Status.REVOKED:
            raise AttackNotApplicable(f"payment is {status.name}, not REVOKED")
        self._attack_started(run, "release_revoked")
        try:
            await self._chain("release", self.chain.release, run.chain_pid, "attacker")
        except ChainReverted as err:
            await run.pacer.wait(900)
            self._reverted(run, err, "release")
            return {"ok": True, "reverted": True, "reason": err.reason}
        log.error("release() on a revoked payment did NOT revert: the chain port is broken")
        return {"ok": True, "reverted": False, "reason": None}

    def _payout_hop(self, run: PaymentRun) -> int:
        """The first leg that moves money towards the beneficiary: where a substitution would pay off."""
        assert run.decision is not None
        hold = self.rails.adapter(run.decision.route.id).hold_hop()
        if hold is not None and hold + 1 < len(run.hops):
            return hold + 1
        return len(run.hops) - 1

    async def _attack_swap_beneficiary(self, run: PaymentRun) -> dict[str, Any]:
        """The beneficiary of a leg is changed in transit, then a modified intent is offered to the escrow."""
        assert run.intent is not None and run.decision is not None
        self._attack_started(run, "swap_beneficiary")
        index = self._payout_hop(run)
        tampered = dataclasses.replace(
            self._leg_message(run, index, run.hops[index]),
            creditor_name=texts.ATTACKER_ACCOUNT["name"],
            creditor_account=texts.ATTACKER_ACCOUNT["account"],
            creditor_bank=texts.ATTACKER_ACCOUNT["bank"],
        )
        leg_reason: str | None = None
        try:
            await self._chain(f"leg {index}", self.rails.adapter(run.decision.route.id).initiate, tampered)
        except LegRejected as err:
            leg_reason = err.reason
            await run.pacer.wait(600)
            self._leg_rejected(run, err)
        else:
            log.error("a leg with a substituted beneficiary was NOT refused: the rail adapter is broken")

        modified = run.intent.model_copy(update={"beneficiary": dev_address("attacker")})
        try:
            await self._chain("deposit", self.chain.deposit, modified, self.payer_address)
        except ChainReverted as err:
            await run.pacer.wait(900)
            self._reverted(run, err, "deposit")
            return {"ok": True, "reverted": True, "reason": err.reason, "legRejected": leg_reason}
        log.error("deposit() with a modified intent did NOT revert: the chain port is broken")
        return {"ok": True, "reverted": False, "reason": None, "legRejected": leg_reason}

    async def _attack_replay(self, run: PaymentRun) -> dict[str, Any]:
        """The same signed intent is committed a second time."""
        assert run.intent is not None and run.intent_signature is not None
        self._attack_started(run, "replay")
        try:
            await self._chain("commit", self.chain.commit, run.intent, run.intent_signature)
        except ChainReverted as err:
            await run.pacer.wait(900)
            self._reverted(run, err, "commit")
            return {"ok": True, "reverted": True, "reason": err.reason}
        log.error("commit() of a replayed intent did NOT revert: the chain port is broken")
        return {"ok": True, "reverted": False, "reason": None}


def build_orchestrator(
    settings: Settings | None = None,
    *,
    env: Mapping[str, str] | None = None,
    pacer_factory: Callable[[float], Pacer] = RealPacer,
    bus: EventBus | None = None,
) -> Orchestrator:
    env = os.environ if env is None else env
    settings = settings or Settings.from_env(env)
    signer = Signer(env)
    holder: dict[str, Orchestrator] = {}
    risk, chain, degraded = load_ports(settings, signer=signer, clock=lambda: holder["o"].now().timestamp())
    writer, llm_degraded = load_case_writer(settings, env)
    if llm_degraded:
        degraded.append("llm")
    journal = Journal(settings.journal_path)
    bus = bus or EventBus()
    bus.add_listener(journal.record_event)
    orchestrator = Orchestrator(
        bus=bus,
        risk=risk,
        chain=chain,
        signer=signer,
        norms=NormsEngine(),
        settings=settings,
        pacer_factory=pacer_factory,
        degraded=degraded,
        beneficiary=env.get("GH_VASP_ADDRESS") or None,
        payer_address=env.get("EU_CASP_ADDRESS") or None,
        token=settings.token_address,
        case=CaseService(settings.llm_mode, writer),
        journal=journal,
    )
    holder["o"] = orchestrator
    return orchestrator
