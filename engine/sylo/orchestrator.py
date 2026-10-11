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
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

from eth_utils import to_checksum_address
from sylo_spec.canonical import (
    corridor_id_of,
    hash_record,
    keccak_text,
    offchain_hash,
    to_hex,
)
from sylo_spec.devkeys import dev_address
from sylo_spec.eip712 import Message, digest, primary_type, typed_data
from sylo_spec.models import (
    Account,
    CaseFile,
    Payer,
    PayerSession,
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
from sylo_spec.scenarios import (
    ACCOUNTS,
    CORRIDOR,
    DIVERTED_ORDER,
    LEGIT_ORDER,
    MULE_ACCOUNT,
    ORDERS,
    PAYEES,
    PAYER,
    build_risk_context,
)

from . import texts
from .approvals import ApprovalSession, required_approvers
from .breakers import BreakerError, Breakers, apply_breaker, apply_degraded
from .bus import EventBus
from .case import CaseService, redact_case_document, rules_case_file
from .clusters import cluster_sample, load_cluster_port, wave_payments
from .confidential import HIDDEN, TOKEN, VISIBLE, ConfidentialLeg, load_confidential_leg
from .config import (
    ORANGE_PLAYGROUND_MIN_MAX_AGE_HOURS,
    Settings,
    orange_playground_number,
)
from .intake import extract, match_order
from .journal import Journal
from .norms import NormsEngine, NormsResult, load_pack
from .pacer import Pacer, RealPacer, iso_ms
from .payees import PaymentIn, build_order, forget_session_accounts
from .ports_loader import load_case_writer, load_ports
from .rails import LegMessage, LegRejected, RailAdapter, Rails
from .risk_rules import CombinedRisk
from .router import PAYER_LIMIT, RerouteLimits, RouteDecision, choose_route
from .signer import Signer
from .telecom import OrangeSimSwap, SimSwapMock

log = logging.getLogger("sylo.orchestrator")

DEFAULT_TOKEN = to_checksum_address("0x" + "0" * 37 + "e0c")
TOKEN_DECIMALS = 6
BANK_HOP_MS = 1400
CHAIN_HOP_MS = 2200
APPROVAL_STEP_MS = 600
SUPPLIER_AUTO_MS = 3000
ANALYST_AUTO_MS = 1500
GUARDIAN_REACTION_MS = 700
TIME_LOCK_AUTO_MS = 2000
QUOTE_VALIDITY_S = 600
GUARDIAN_KNOWN_RUNS = 50
"""Lane C's guardian recognises the engine's payments by recomputing their on-chain ids, for the first 50
runs of an order on a registry (``MAX_RUNS_PER_ORDER`` in ``chain/sylo_chain/guardian.py``)."""
ID_SEARCH_LIMIT = 1_000_000
CONTACT_MIN_DAYS = 30
SIM_EVENTS = ("rail_down", "rail_up", "mule_wave", "sim_swap", "clock", "compromised_connector", "stolen_verifier_key")
THIEF_RELEASE_MS = 900
CASE_TIMEOUT_S = 10.0
CONFIDENTIAL_TIMEOUT_S = 150.0
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
    supplier_silent: bool = False
    """The supplier never answers: with ``auto`` the demo clock jumps to the hold's expiry."""


SCENARIOS: dict[str, ScenarioDef] = {
    "legit": ScenarioDef("legit"),
    "diverted": ScenarioDef("diverted"),
    "diverted_simswap": ScenarioDef("diverted", sim_swap_hours_ago=5.0),
    "outage": ScenarioDef("legit", rail_down="R3"),
    "diverted_expiry": ScenarioDef("diverted", supplier_silent=True),
    "diverted_timelock": ScenarioDef("diverted", rail_down="R3"),
}
CUSTOM = "custom"  # scenario name a typed payment is published under
"""A payment typed by a user (``POST /v1/quotes`` with ``payment``): no injected incident."""
ATTACKS = ("release_revoked", "swap_beneficiary", "replay", "stolen_verifier_key")
CASE_ACTIONS = ("CONFIRM_REVOCATION", "RELEASE", "FREEZE")
HOLD_MODES = {"ONCHAIN_ESCROW": "escrow", "FIAT_HOLD": "bank"}


CORRIDOR_DEMOS: dict[str, str] = {"lagos-accra": "NG-GH"}
"""Quotable demo orders of other corridors: name -> pack id. Payer and order are read from the pack file."""


@lru_cache(maxsize=None)
def corridor_demo(name: str) -> tuple[NormsEngine, Payer, PaymentOrder]:
    """A second corridor needs no code: its routes, rules, payer and demo order come from its pack file."""
    pack = load_pack(CORRIDOR_DEMOS[name])
    if not pack.demo:
        raise ValueError(f"pack {pack.id} has no demo order")
    return NormsEngine(pack), Payer.model_validate(pack.demo["payer"]), PaymentOrder.model_validate(pack.demo["order"])


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


class UnknownQuote(Exception):
    pass


class UnknownPayee(Exception):
    pass


class CustomOrderLimit(Exception):
    pass


@dataclass
class Quote:
    id: str
    order_name: str
    order: PaymentOrder
    valid_until: datetime
    executable: bool
    invoice_text: str | None = None


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
    chain_index: int = 1
    """Which run of the order this is on the registry: the id is ``keccak(order id)``, then ``id#2``, ``id#3``..."""
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
    escalation: asyncio.Future[str] | None = None
    """Resolved by a guardian incident that froze the hold: the supplier is no longer waited for."""
    incident_id: str | None = None
    expiry: asyncio.Future[str] | None = None
    """Resolved when the hold expires (demo clock or real time) before anybody decided."""
    hold_until: datetime | None = None
    time_lock: asyncio.Future[str] | None = None
    locked_until: datetime | None = None
    hold: str | None = None
    hold_hop: int | None = None
    hold_expires_at: str | None = None
    frozen: bool = False
    case: CaseFile | None = None
    case_task: asyncio.Task[None] | None = None
    signed: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    invoice_text: str | None = None

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
        confidential: ConfidentialLeg | None = None,
        telecom: SimSwapMock | OrangeSimSwap | None = None,
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
        self.confidential = confidential
        self.boot_id = uuid.uuid4().hex[:12]
        self.chain_simulated = chain.mode != "fuji"
        self.telecom = telecom or SimSwapMock(clock=self.now)
        self.rails = Rails(norms.pack, chain, clock=lambda: self.now().timestamp())
        self.breakers = Breakers()
        self.cluster_port, self.cluster_stub = load_cluster_port(settings.cluster_mode)
        if settings.cluster_mode == "auto" and self.cluster_stub and "clusters" not in self.degraded:
            self.degraded.append("clusters")
        self._startup_degraded = list(self.degraded)
        self.incidents: list[dict[str, Any]] = []
        self._paused_corridors: dict[str, str] = {}
        self._clock_offset = timedelta(0)
        self._quotes: dict[str, Quote] = {}
        self._submitted: dict[str, dict[str, Any]] = {}
        self._custom_orders: dict[str, PaymentOrder] = {}
        self._custom_scenarios: dict[str, ScenarioDef] = {}
        self._custom_accounts: dict[str, Account] = {}
        self._custom_order_count = 0
        self._next_custom_order = 1001
        self._payee_checks: dict[str, dict[str, Any]] = {}
        self._injected_sim_swap: float | None = None
        self._window: list[WindowPayment] = []
        self._announced_breakers: set[str] = set()
        self._rng = random.Random(settings.seed)
        self._runs: dict[str, PaymentRun] = {}
        self._run_counts: dict[str, int] = {}
        self._task: asyncio.Task[None] | None = None
        self._current_pacer: Pacer | None = None

    # --- mode and clock ----------------------------------------------------------------------

    def now(self) -> datetime:
        return self._current_pacer.now() if self._current_pacer else datetime.now(timezone.utc) + self._clock_offset

    def _pacer(self, speed: float) -> Pacer:
        pacer = self.pacer_factory(speed)
        if isinstance(pacer, RealPacer) and self._clock_offset:
            pacer.advance(self._clock_offset)  # a wall-clock pacer joins the session's demo clock
        return pacer

    def advance_clock(self, hours: float) -> dict[str, Any]:
        """Demo clock (PRD P1-9): jump the session's time forward, so that a hold's expiry or a time-lock
        is shown in seconds. Whatever was waiting for that moment goes on."""
        delta = timedelta(hours=hours)
        self._clock_offset += delta
        pacers = {id(run.pacer): run.pacer for run in self._runs.values()}
        if self._current_pacer is not None:
            pacers[id(self._current_pacer)] = self._current_pacer
        for pacer in pacers.values():
            pacer.advance(delta)
        now = self.now()
        shown = round(hours, 2)
        self._publish("clock.advanced", {"hours": shown, "now": iso_ms(now), "text": texts.CLOCK_ADVANCED.format(hours=shown)})
        for expired in self.breakers.expire(now):
            self._publish("breaker.off", {"breakerId": expired.id, "reason": "EXPIRED"})
        for run in self._runs.values():
            if run.hold is None:
                continue
            if run.expiry is not None and not run.expiry.done() and run.hold_until is not None and now >= run.hold_until:
                run.expiry.set_result("EXPIRED")
            if run.time_lock is not None and not run.time_lock.done() and run.locked_until is not None and now >= run.locked_until:
                run.time_lock.set_result("ELAPSED")
        return {"ok": True, "now": iso_ms(now)}

    def mode(self) -> dict[str, Any]:
        return {
            "risk": "model" if isinstance(self.risk, CombinedRisk) else "rules",
            "chain": self.chain.mode,
            "llm": self.case.mode,
            "rails": "simulated",
            "degraded": list(self.degraded),
            "bootId": self.boot_id,
            "humanSteps": self.settings.human_steps,
            "clusters": "sample" if self.cluster_stub else "detector",
            "confidential": self.confidential.mode if self.confidential is not None else "off",
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

    def start(
        self,
        name: str,
        *,
        speed: float = 1.0,
        auto: bool = False,
        auto_answer: str = "deny",
        invoice_text: str | None = None,
    ) -> str:
        """Start a scenario in the background and return its payment id."""
        if self._scenario(name) is None:
            raise UnknownScenario(name)
        if self.running:
            raise ScenarioBusy()
        run = self._new_run(name, speed, auto, auto_answer, invoice_text)
        self._task = asyncio.create_task(self._execute(run))
        return run.order.id

    async def run_to_end(
        self,
        name: str,
        *,
        speed: float = 1.0,
        auto: bool = True,
        auto_answer: str = "deny",
        invoice_text: str | None = None,
    ) -> PaymentRun:
        """Run a scenario in the foreground (tests and the fixture recorder)."""
        if self._scenario(name) is None:
            raise UnknownScenario(name)
        if self.running:
            raise ScenarioBusy()
        run = self._new_run(name, speed, auto, auto_answer, invoice_text)
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
        if name == "stolen_verifier_key":
            return await self._attack_stolen_verifier_key(run)
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
        self._clock_offset = timedelta(0)
        self._quotes.clear()
        forget_session_accounts()
        self._submitted.clear()
        for account_id, account in self._custom_accounts.items():
            if ACCOUNTS.get(account_id) is account:
                ACCOUNTS.pop(account_id, None)
        self._custom_accounts.clear()
        self._custom_orders.clear()
        self._custom_scenarios.clear()
        self._payee_checks.clear()
        self._injected_sim_swap = None
        self.telecom.clear()
        for route_id in list(self._paused_corridors):
            self._reopen_corridor(route_id)
        self.rails.reset()
        self.breakers.reset()
        self._window.clear()
        self._announced_breakers.clear()
        self.incidents.clear()
        # A dependency that failed while running gets another chance; one missing since start-up stays degraded.
        runtime_degraded = self.degraded != self._startup_degraded
        self.degraded = list(self._startup_degraded)
        if isinstance(self.risk, CombinedRisk):
            self.risk.failed = False
        self.bus.clear()
        self.bus.publish("session.reset", {})
        if runtime_degraded:
            self.bus.publish("system.mode", self.mode())

    def _legs(self, payment_id: str) -> list[dict[str, Any]]:
        """Status leg by leg, from the events of the payment (pacs.002-style)."""
        legs: dict[int, dict[str, Any]] = {}
        refused: list[dict[str, Any]] = []
        for event in self.bus.events:
            if event["paymentId"] != payment_id:
                continue
            data = event["data"]
            if event["type"] == "leg.sent":
                legs[data["hop"]] = {
                    "hop": data["hop"],
                    "from": data["from"],
                    "to": data["to"],
                    "rail": data["rail"],
                    "status": "pending",
                    "idempotencyKey": data["idempotencyKey"],
                    "sentAt": event["ts"],
                }
            elif event["type"] == "leg.settled" and data["hop"] in legs:
                legs[data["hop"]].update(status="settled", settledAt=event["ts"])
            elif event["type"] == "leg.rejected":
                refused.append(
                    {"hop": data["hop"], "from": data["from"], "to": data["to"], "rail": data["rail"], "status": "rejected", "reason": data["reason"], "at": event["ts"]}
                )
        return [legs[hop] for hop in sorted(legs)] + refused

    async def payment_info(self, payment_id: str) -> dict[str, Any]:
        run = self._get(payment_id)
        payment_id = run.order.id
        chain_status = Status(int(await asyncio.to_thread(self.chain.status, run.chain_pid)))
        return {
            "paymentId": payment_id,
            "uetr": run.order.uetr,
            "chainPaymentId": to_hex(run.chain_pid),
            "chainRunIndex": run.chain_index,
            "legs": self._legs(payment_id),
            "status": run.status,
            "tier": run.tier.name if run.tier is not None else None,
            "routeId": run.decision.route.id if run.decision and run.decision.route else None,
            "chainStatus": chain_status.name,
            "lastSeq": run.last_seq,
            "scenario": run.scenario,
            "pendingApprovers": [a.id for a in run.approval.pending] if run.approval else [],
            "hold": run.hold,
            "holdExpiresAt": run.hold_expires_at,
            "lockedUntil": iso_ms(run.locked_until) if run.locked_until else None,
            "frozen": run.frozen,
            "incidentId": run.incident_id,
            "caseReady": run.case is not None,
        }

    async def proof(self, payment_id: str) -> dict[str, Any]:
        """Everything an auditor needs to recompute the payment: typed data, signatures, transactions, log."""
        run = self._get(payment_id)
        payment_id = run.order.id
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
            "chainPaymentLabel": self._chain_label(payment_id, run.chain_index),
            "chainRunIndex": run.chain_index,
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

    # --- integration API: quote, payment, cases, payee verification (PRD §16.2) ---------------

    def _decision(self, order: PaymentOrder, *, engine: NormsEngine | None = None, payer: Payer = PAYER) -> dict[str, Any]:
        """Norms, risk and route for an order, without committing anything (the PRD's ``Decision``).

        ``engine`` and ``payer`` are those of another corridor's pack; by default the corridor the engine runs."""
        own = engine is None
        engine = engine or self.norms
        pack = engine.pack
        norms = engine.evaluate(order)
        context = (
            build_risk_context(order, norms.signal_codes, sanctions_hit=norms.sanctions_hit)
            if own
            else build_risk_context(
                order,
                norms.signal_codes,
                session=PayerSession(country=order.channel.session_country),
                sanctions_hit=norms.sanctions_hit,
            )
        )
        risk = self._overlays(order, self.risk.score(order, context))
        amount = order.amount.as_float
        decision = choose_route(
            norms,
            risk.tier,
            amount,
            pack.route_model,
            oob_resolvable=risk.oob_resolvable,
            unavailable=self.rails.unavailable() if own else {},
            limits=RerouteLimits(self.settings.reroute_max_fees_eur, self.settings.reroute_max_days),
            symbol=pack.symbol,
        )
        account = ACCOUNTS.get(order.creditor_account_id)
        payee = PAYEES.get(order.payee_id)
        approvers, method = required_approvers(
            payer,
            amount,
            known_account=bool(account and payee and payee.owns(account.id)),
            dual_control_eur=self.settings.dual_control_eur,
            new_payee_eur=self.settings.dual_control_new_payee_eur,
        )
        conditional = decision.route is not None and action_tier(risk) == Tier.MEDIUM
        legal_refs = {rule.id: rule.legal_ref for rule in pack.rules}
        rails = (
            self.rails.quotes(amount)
            if own
            else [
                {
                    "routeId": route.id,
                    "rail": route.name,
                    "settlement": route.settlement,
                    "feesEur": round(route.fees(amount), 2),
                    "etaLabel": route.eta_label,
                    "available": True,
                    "simulated": True,
                }
                for route in pack.routes
            ]
        )
        return {
            "paymentId": order.id,
            "uetr": order.uetr,
            "corridor": order.corridor,
            "currency": pack.currency,
            "authorities": pack.authorities(),
            "packVersion": norms.pack_version,
            "routes": [route.to_event() for route in norms.routes],
            "normChecks": [
                {"routeId": route.route.id, "ruleId": check["ruleId"], "result": check["result"], "legalRef": legal_refs.get(check["ruleId"])}
                for route in norms.routes
                for check in route.checks
            ],
            "signals": norms.signals,
            "taxNotices": norms.tax_notices,
            "controls": norms.controls,
            "risk": {
                "score": risk.score,
                "tier": risk.tier.name,
                "rulesFired": risk.rules_fired,
                "topReasons": [reason.to_json_dict() for reason in risk.reasons],
                "modelVersion": risk.model,
                "oobResolvable": risk.oob_resolvable,
            },
            "route": {
                "chosen": decision.route.id if decision.route else None,
                "candidates": decision.scores,
                "settlement": decision.settlement or "NONE",
                "reason": decision.reason,
                "feesEur": decision.fees_eur,
                "etaLabel": decision.route.eta_label if decision.route else None,
                "priceOfSafetyEur": decision.price_of_safety,
                "blockedBy": decision.blocked_by,
            },
            "approval": {
                "required": [{"id": approver.id, "name": approver.name, "role": approver.role} for approver in approvers],
                "method": method,
                "conditional": conditional,
            },
            "verifications": ["SIM_SWAP_CHECK", "OOB_KNOWN_CONTACT"] if conditional else [],
            "rails": rails,
        }

    def quote_payment(self, payment: PaymentIn) -> dict[str, Any]:
        """Norms, risk, best route and price for a payment typed by a user. Executable for 600 s."""
        if self._custom_order_count >= 200:
            raise CustomOrderLimit()
        order = self._verified_order(build_order(payment, f"PAY-2026-{self._next_custom_order:04d}"))
        self._custom_orders[order.id] = order
        self._custom_scenarios[order.id] = ScenarioDef(order=order.id)
        self._custom_order_count += 1
        self._next_custom_order += 1
        return self._store_quote(order.id, order, executable=True, invoice_text=payment.invoiceText)

    def _store_quote(
        self, order_name: str, order: PaymentOrder, *, executable: bool, invoice_text: str | None = None, **decide: Any
    ) -> dict[str, Any]:
        quote = Quote(
            id=f"Q-{len(self._quotes) + 1:04d}",
            order_name=order_name,
            order=order,
            valid_until=self.now() + timedelta(seconds=QUOTE_VALIDITY_S),
            executable=executable,
            invoice_text=invoice_text,
        )
        self._quotes[quote.id] = quote
        decision = self._decision(order, **decide)
        decision["route"]["quoteValidUntil"] = iso_ms(quote.valid_until)
        return {"quoteId": quote.id, "validUntil": iso_ms(quote.valid_until), "executable": quote.executable, **decision}

    def quote(self, order_name: str, amount: str | None = None) -> dict[str, Any]:
        """Norms, risk, best route and reason for one of the demo orders, valid 600 s. Nothing is committed.

        ``amount`` prices the same order for another amount; such a quote cannot be executed, because the
        PoC only runs the two recorded orders."""
        engine: NormsEngine | None = None
        payer = PAYER
        if order_name in CORRIDOR_DEMOS:
            engine, payer, order = corridor_demo(order_name)  # another corridor: priced, never executed here
        elif (recorded_order := self._order(order_name)) is not None:
            order = self._verified_order(recorded_order)
        else:
            raise UnknownScenario(order_name)
        if amount is not None:
            order = order.model_copy(update={"amount": order.amount.model_copy(update={"value": amount})})
        return self._store_quote(order_name, order, executable=amount is None and engine is None, engine=engine, payer=payer)

    def quote_custom(self, custom: Mapping[str, Any]) -> dict[str, Any]:
        if self._custom_order_count >= 200:
            raise CustomOrderLimit()

        order_id = f"PAY-2026-{self._next_custom_order:04d}"
        account_kind = custom["account"]
        invoice_ref = custom["invoiceRef"]
        amount = str(custom["amount"])
        invoice_text = custom.get("invoiceText")
        sender_domain = custom.get("senderDomain")

        account_id = LEGIT_ORDER.creditor_account_id
        account = ACCOUNTS[account_id]
        creditor = LEGIT_ORDER.creditor
        provenance = dict(LEGIT_ORDER.provenance)
        if account_kind == "new":
            account_id = f"acc-custom-{self._next_custom_order:04d}"
            account_number_index = self._next_custom_order
            while account_id in ACCOUNTS:
                account_number_index += 1
                account_id = f"acc-custom-{account_number_index:04d}"
            account_number = "".join(str(custom["accountNumber"]).split())
            account = MULE_ACCOUNT.model_copy(
                update={
                    "id": account_id,
                    "holder_name": custom["holderName"],
                    "account_masked": f"GH•• •••• {account_number[-4:]}",
                    "first_seen": self.now().date().isoformat(),
                    "successful_payments": 0,
                }
            )
            sender_domain = sender_domain or "savannashea-exports.co"
            creditor = creditor.model_copy(update={"institution_id": account.institution_id})
            provenance = dict(DIVERTED_ORDER.provenance)
            # Runtime custom payees extend the shared account registry; the spec file stays unchanged.
            ACCOUNTS[account_id] = account
            self._custom_accounts[account_id] = account
        else:
            sender_domain = sender_domain or LEGIT_ORDER.documents.sender_domain

        order = LEGIT_ORDER.model_copy(
            update={
                "id": order_id,
                "uetr": str(uuid.uuid4()),
                "creditor": creditor,
                "creditor_account_id": account_id,
                "amount": LEGIT_ORDER.amount.model_copy(update={"value": amount}),
                "documents": LEGIT_ORDER.documents.model_copy(
                    update={"invoice_ref": invoice_ref, "sender_domain": sender_domain}
                ),
                "provenance": provenance,
            }
        )
        self._custom_orders[order_id] = order
        self._custom_scenarios[order_id] = ScenarioDef(order=order_id)
        self._custom_order_count += 1
        self._next_custom_order += 1

        quote = Quote(
            id=f"Q-{len(self._quotes) + 1:04d}",
            order_name=order_id,
            order=order,
            valid_until=self.now() + timedelta(seconds=QUOTE_VALIDITY_S),
            executable=True,
            invoice_text=invoice_text,
        )
        self._quotes[quote.id] = quote
        decision = self._decision(order)
        decision["route"]["quoteValidUntil"] = iso_ms(quote.valid_until)
        return {"quoteId": quote.id, "validUntil": iso_ms(quote.valid_until), "executable": True, **decision}

    def quote_invoice_text(self, quote_id: str | None) -> str | None:
        quote = self._quotes.get(quote_id or "")
        return quote.invoice_text if quote is not None else None

    def is_submission_replay(self, idempotency_key: str | None) -> bool:
        return bool(idempotency_key and idempotency_key in self._submitted)

    def public_payments(self) -> list[dict[str, str]]:
        return [
            {"paymentId": run.order.id, "chainPaymentId": to_hex(run.chain_pid)}
            for run in self._runs.values()
        ]

    def submit(
        self,
        *,
        quote_id: str | None = None,
        order_name: str | None = None,
        speed: float = 1.0,
        auto: bool = False,
        auto_answer: str = "deny",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Submit one of the demo orders, or execute a quote. Returns the decision and what it still needs
        from people; the payment then runs like a scenario. The same ``Idempotency-Key`` never starts two."""
        if idempotency_key and idempotency_key in self._submitted:
            return {**self._submitted[idempotency_key], "replayed": True}
        if quote_id is not None:
            quote = self._quotes.get(quote_id)
            if quote is None:
                raise UnknownQuote(quote_id)
            if not quote.executable:
                raise ActionNotAllowed("this quote is for pricing only: the PoC executes the two recorded FR → GH orders")
            if self.now() > quote.valid_until:
                raise ActionNotAllowed(f"quote {quote_id} expired at {iso_ms(quote.valid_until)}: ask for a new one")
            order_name = quote.order_name
        order = self._order(order_name)
        if order is None:
            raise UnknownScenario(str(order_name))
        decision = self._decision(self._verified_order(order))
        payment_id = self.start(
            order_name,
            speed=speed,
            auto=auto,
            auto_answer=auto_answer,
            invoice_text=quote.invoice_text if quote_id is not None else None,
        )
        answer = {"paymentId": payment_id, "quoteId": quote_id, "status": "deciding", "replayed": False, "decision": decision}
        if idempotency_key:
            self._submitted[idempotency_key] = answer
        return answer

    def intake(self, text: str, sender_domain: str | None = None) -> dict[str, Any]:
        """Read an invoice or an e-mail into the fixed fields, find the recorded order it is about, and give
        the engine's decision for that order. The text itself never reaches a rule (documents are data)."""
        result = extract(text, sender_domain)
        order = match_order(result)
        return {
            "intake": result.to_json(),
            "matchedOrder": order.id if order is not None else None,
            "decision": self._decision(self._verified_order(order)) if order is not None else None,
        }

    def cases(self) -> list[dict[str, Any]]:
        """The analyst's queue: every payment that was held, blocked or touched by an incident."""
        queue: list[dict[str, Any]] = []
        for run in self._runs.values():
            if run.case is None and run.hold is None and run.incident_id is None:
                continue
            actions: list[str] = []
            if run.analyst is not None and not run.analyst.done():
                actions.append("CONFIRM_REVOCATION")
            if run.hold is not None and not run.frozen:
                actions.append("FREEZE")
                if run.status == "confirmed":
                    actions.append("RELEASE")
            queue.append(
                {
                    "paymentId": run.order.id,
                    "uetr": run.order.uetr,
                    "status": run.status,
                    "tier": run.tier.name if run.tier is not None else None,
                    "score": run.risk.score if run.risk else None,
                    "rulesFired": list(run.risk.rules_fired) if run.risk else [],
                    "hold": run.hold,
                    "holdExpiresAt": run.hold_expires_at if run.hold is not None else None,
                    "frozen": run.frozen,
                    "incidentId": run.incident_id,
                    "caseReady": run.case is not None,
                    "allowedActions": actions,
                }
            )
        return queue

    def _payee_account(self, payee_id: str, account_id: str):
        payee = PAYEES.get(payee_id)
        account = ACCOUNTS.get(account_id)
        if payee is None or account is None:
            raise UnknownPayee(payee_id if payee is None else account_id)
        return payee, account

    def start_payee_verification(self, payee_id: str, account_id: str) -> dict[str, Any]:
        """Ask the payee, on a contact already on file, whether an account is theirs: before any payment."""
        payee, account = self._payee_account(payee_id, account_id)
        contact = payee.known_contacts[0]
        days_known = (self.now().date() - date.fromisoformat(contact.since)).days
        sim_swap_recent = self.telecom.check(contact.msisdn_masked, self.settings.sim_swap_max_age_hours)
        why = (
            texts.CONTACT_TOO_RECENT.format(days=CONTACT_MIN_DAYS)
            if days_known < CONTACT_MIN_DAYS
            else texts.CONTACT_SIM_SWAP if sim_swap_recent else None
        )
        check = {
            "payeeId": payee.id,
            "accountId": account.id,
            "accountMasked": account.account_masked,
            "accountHolder": account.holder_name,
            "step": "REQUESTED",
            "channel": "SMS" if why is None else "ANALYST",
            "contactName": contact.name,
            "contactMasked": contact.msisdn_masked,
            "contactSince": contact.since,
            "simSwapChecked": True,
            "simSwapRecent": sim_swap_recent,
            "result": None,
            "text": (
                texts.PAYEE_VERIFICATION_REQUESTED.format(
                    account=account.account_masked, holder=account.holder_name, contact=contact.name, since=contact.since
                )
                if why is None
                else texts.PAYEE_VERIFICATION_ANALYST.format(payee=texts.payee_short(payee), why=why, account=account.account_masked)
            ),
        }
        self._payee_checks[account.id] = check
        self._publish("payee.verification", dict(check))
        return {"ok": True, **check}

    def record_payee_verification(self, payee_id: str, account_id: str, result: str) -> dict[str, Any]:
        """The known contact's answer. A denied account is blocked before approval; a confirmed one is no
        longer 'details from an untrusted source' (the other risk reasons still apply)."""
        payee, account = self._payee_account(payee_id, account_id)
        check = self._payee_checks.get(account.id)
        if check is None or check["step"] != "REQUESTED":
            raise ActionNotAllowed("no verification is waiting for an answer on this account: start one first")
        if check["channel"] != "SMS":
            raise ActionNotAllowed("the known contact cannot be trusted for this check: an analyst decides")
        check = {
            **check,
            "step": "RECORDED",
            "result": result,
            "at": iso_ms(self.now()),
            "text": texts.PAYEE_VERIFICATION_RECORDED[result].format(
                contact=check["contactName"], account=account.account_masked, holder=account.holder_name, payee=texts.payee_short(payee)
            ),
        }
        self._payee_checks[account.id] = check
        self._publish("payee.verification", dict(check))
        return {"ok": True, **check}

    def _verified_order(self, order: PaymentOrder) -> PaymentOrder:
        """The order as the engine sees it after a recorded payee verification of its account."""
        check = self._payee_checks.get(order.creditor_account_id)
        if check is None or check.get("result") != "CONFIRMED":
            return order
        return order.model_copy(update={"provenance": {**order.provenance, "creditorAccount": "verified_registry"}})

    async def sim_event(self, kind: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Attack console: one entry point for the simulated events (fraud wave, outage, compromised connector)."""
        if kind == "rail_down":
            return self.rail_down(str(params.get("routeId")), params.get("reason"))
        if kind == "rail_up":
            return self.rail_up(str(params.get("routeId")))
        if kind == "mule_wave":
            return self.start_wave(speed=float(params.get("speed") or 1.0), auto=bool(params.get("auto", False)))
        if kind == "clock":
            return self.advance_clock(float(params.get("advanceHours") or 24.0))
        if kind == "sim_swap":
            self._injected_sim_swap = float(params.get("hoursAgo") or 5.0)
            return {"ok": True, "hoursAgo": self._injected_sim_swap, "appliesTo": "the next out-of-band check"}
        payment_id = str(params.get("paymentId") or "")
        if kind == "stolen_verifier_key":
            return await self.attack("stolen_verifier_key", payment_id)
        if kind == "compromised_connector":
            # A connector that keeps changing legs: the adapter refuses each one, then the kill switch cuts it.
            attempts = [await self.attack("swap_beneficiary", payment_id) for _ in range(KILL_REFUSALS)]
            run = self._get(payment_id)
            adapter = self.rails.adapter(run.decision.route.id) if run.decision and run.decision.route else None
            return {"ok": True, "attempts": attempts, "killSwitch": bool(adapter and adapter.killed_reason is not None)}
        raise UnknownAction(kind)

    def rail_webhook(self, route_id: str, notification: Mapping[str, Any]) -> dict[str, Any]:
        adapter = self.rails.get(route_id)
        if adapter is None:
            raise UnknownRoute(route_id)
        return {"routeId": adapter.id, **adapter.on_webhook(notification)}

    def rail_reconcile(self, route_id: str) -> dict[str, Any]:
        adapter = self.rails.get(route_id)
        if adapter is None:
            raise UnknownRoute(route_id)
        return adapter.reconcile()

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
        self._reopen_corridor(adapter.id)
        self._publish("rail.up", {"routeId": adapter.id, "name": adapter.name})
        return {"ok": True, "routeId": adapter.id, "available": adapter.available}

    def start_wave(self, *, speed: float = 1.0, auto: bool = False) -> dict[str, Any]:
        """Scene 3: three payments from other payers reach accounts of one mule cluster."""
        if self.running:
            raise ScenarioBusy()
        self._task = asyncio.create_task(self._wave(self._pacer(speed), auto))
        return {"ok": True, "payments": [payment["paymentId"] for payment in wave_payments()]}

    async def run_wave(self, *, speed: float = 1.0, auto: bool = True) -> None:
        """The mule wave in the foreground (tests and the fixture recorder)."""
        if self.running:
            raise ScenarioBusy()
        await self._wave(self._pacer(speed), auto)

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

    def guardian_incident(self, report: dict[str, Any], *, escalate: bool = True) -> dict[str, Any]:
        """An on-chain incident reported by the guardian (Lane C): show it and draft the DORA incident report.

        A freeze hands the held payment to the analyst (``escalate``): the supplier's answer can no longer
        release it, so the only way out is a revocation and a refund to the payer.
        """
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
        froze = run is not None and run.hold is not None and "FREEZE" in action.upper()
        if run is not None and froze:
            run.frozen = True  # the guardian froze the hold on-chain: the engine must not try to release it
            run.incident_id = incident_id
        self._publish(
            "guardian.incident",
            data,
            payment_id=run.order.id if run else None,
            simulated=bool(report.get("simulated", self.chain_simulated)),
        )
        if "PAUSE" in action.upper():
            self._corridor_paused(run, incident_id)
        if run is not None and froze:
            self._alert(
                run,
                "analyst",
                texts.ANALYST,
                "IN_APP",
                texts.ALERT_GUARDIAN_FROZEN.format(rule=rule),
                headline=texts.GUARDIAN_HEADLINE.format(rule=rule),
                incidentId=incident_id,
            )
            if escalate:
                self._escalate(run)
        draft = {**data, "paymentId": run.order.id if run else None, "receivedAt": iso_ms(self.now()), "status": "DRAFT, not filed"}
        self.incidents.append(draft)
        if self.settings.journal_path:
            folder = Path(self.settings.journal_path).parent / "incidents"
            folder.mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in incident_id)
            (folder / f"{safe}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "incidentId": incident_id}

    @staticmethod
    def _escalate(run: PaymentRun) -> None:
        """Stop waiting for the supplier on a hold the guardian froze: a person decides."""
        if run.escalation is not None and not run.escalation.done():
            run.escalation.set_result(run.incident_id or "guardian")

    def _escrow_routes(self, run: PaymentRun | None) -> list[str]:
        """The routes that settle through the on-chain escrow: the ones a paused corridor closes."""
        if run is not None and run.decision is not None and run.decision.route is not None and run.hold == "escrow":
            return [run.decision.route.id]
        return [adapter.id for adapter in self.rails if adapter.route.settlement == "ONCHAIN_ESCROW"]

    def _corridor_paused(self, run: PaymentRun | None, incident_id: str) -> None:
        """The guardian paused the corridor: no escrow release can pass, so its route is closed until a
        person reopens it (``rail_up``, after the keys are rotated and the corridor is unpaused)."""
        for route_id in self._escrow_routes(run):
            adapter = self.rails.adapter(route_id)
            if not adapter.available:
                continue
            adapter.down_reason = texts.GUARDIAN_PAUSE_REASON.format(incident=incident_id)
            self._paused_corridors[route_id] = corridor_id_of(CORRIDOR)
            self._publish("rail.down", {"routeId": adapter.id, "name": adapter.name, "reason": adapter.down_reason})

    def _reopen_corridor(self, route_id: str) -> None:
        """Only the simulated chain is reopened here: on Fuji the admin key unpauses (Lane C's guardian command)."""
        corridor = self._paused_corridors.pop(route_id, None)
        unpause = getattr(self.chain, "unpause_corridor", None)
        if corridor is not None and self.chain_simulated and unpause is not None:
            unpause(corridor)

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
                    WindowPayment(
                        payment_id=payment["paymentId"],
                        account_id=payment["accountId"],
                        institution_id=institution,
                        amount_eur=float(payment["amount"]),
                        at=iso_ms(self.now()),
                        payer_id=payment["payer"]["id"],
                        payee_id=payment.get("payeeName"),
                        account_age_days=payment.get("accountAgeDays"),
                        successful_payments=payment.get("successfulPayments"),
                    )
                )
                await self._detect_clusters(pacer, auto or self.settings.human_steps != "manual")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mule wave failed")

    def _observe(self, seen: WindowPayment) -> None:
        """Remember a payment for the cluster detector (last hour; a re-run of the same payment counts once)."""
        cutoff = self.now() - timedelta(minutes=CLUSTER_WINDOW_MINUTES)
        self._window = [
            payment
            for payment in self._window
            if payment.payment_id != seen.payment_id and datetime.fromisoformat(payment.at.replace("Z", "+00:00")) >= cutoff
        ]
        self._window.append(seen)

    def _observe_order(self, order: PaymentOrder) -> None:
        account = ACCOUNTS[order.creditor_account_id]
        first_seen = datetime.fromisoformat(account.first_seen).replace(tzinfo=timezone.utc)
        self._observe(
            WindowPayment(
                payment_id=order.id,
                account_id=account.id,
                institution_id=account.institution_id,
                amount_eur=order.amount.as_float,
                at=iso_ms(self.now()),
                payer_id=PAYER.id,
                payee_id=order.payee_id,
                account_age_days=max((self.now() - first_seen).total_seconds() / 86_400, 0.0),
                successful_payments=account.successful_payments,
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
        if getattr(self.risk, "failed", False):
            self._degrade("risk")
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
        """A payment by its id, by its UETR, or by its on-chain id (0x-hex, as the registry's events give it)."""
        wanted = payment_id.lower()
        run = self._runs.get(payment_id) or next(
            (r for r in self._runs.values() if r.order.uetr == payment_id or to_hex(r.chain_pid).lower() == wanted), None
        )
        if run is None:
            raise UnknownPayment(payment_id)
        return run

    def _new_run(
        self,
        name: str,
        speed: float,
        auto: bool,
        auto_answer: str,
        invoice_text: str | None = None,
    ) -> PaymentRun:
        scenario = self._scenario(name)
        if scenario is None:
            raise UnknownScenario(name)
        order = self._order(scenario.order)
        if order is None:
            raise UnknownScenario(scenario.order)
        index = self._run_counts.get(order.id, 0) + 1  # checked against the registry when the run starts
        self._run_counts[order.id] = index
        run = PaymentRun(
            order=order,
            scenario=name,
            chain_pid=keccak_text(self._chain_label(order.id, index)),
            pacer=self._pacer(speed),
            chain_index=index,
            auto=auto,
            auto_answer=auto_answer,
            invoice_text=invoice_text,
        )
        self._runs[order.id] = run
        return run

    def _order(self, name: str | None) -> PaymentOrder | None:
        if name is None:
            return None
        return self._custom_orders.get(name) or ORDERS.get(name)

    def _scenario(self, name: str | None) -> ScenarioDef | None:
        if name is None:
            return None
        return self._custom_scenarios.get(name) or SCENARIOS.get(name)

    @staticmethod
    def _chain_label(order_id: str, index: int) -> str:
        """The label hashed into the on-chain payment id: the order id for its first run, then ``id#2``,
        ``id#3``... Lane C's guardian recomputes exactly these ids to find what the engine signed, so the
        scheme must not change (no salt, no other separator) without changing the guardian with it."""
        return order_id if index == 1 else f"{order_id}#{index}"

    async def _claim_chain_id(self, run: PaymentRun) -> None:
        """Give the run an on-chain id that the registry has never seen.

        The run counter lives in memory, so after a restart it starts again at 1 while a registry that
        outlives the engine (Fuji, a local node) still holds the ids of earlier sessions; committing one of
        them again reverts ``InvalidTransition``. The run therefore keeps its id only if the registry does
        not know it, and otherwise takes a free one further on: doubling steps until a free index is
        found, then a binary search back towards the lowest free one. If the registry cannot be read
        now, the id is kept as it is and the commit will say what is wrong.
        """
        order_id = run.order.id

        async def used(index: int) -> bool:
            pid = keccak_text(self._chain_label(order_id, index))
            return Status(int(await asyncio.to_thread(self.chain.status, pid))) != Status.NONE

        try:
            if not await used(run.chain_index):
                return
            low, step = run.chain_index, 1  # low is always a used index, high a free one
            high = low + step
            while await used(high):
                low, step = high, step * 2
                high = low + step
                if high > ID_SEARCH_LIMIT:
                    raise RuntimeError(f"no free on-chain id below {ID_SEARCH_LIMIT}")
            while high - low > 1:
                middle = (low + high) // 2
                if await used(middle):
                    low = middle
                else:
                    high = middle
        except asyncio.CancelledError:
            raise
        except Exception as err:
            log.warning("could not look for a free on-chain id for %s (%s); keeping run %d", order_id, err, run.chain_index)
            return
        log.info("%s: runs up to %d are already in the registry, this one is run %d", order_id, high - 1, high)
        run.chain_index = high
        run.chain_pid = keccak_text(self._chain_label(order_id, high))
        self._run_counts[order_id] = max(self._run_counts.get(order_id, 0), high)
        if high > GUARDIAN_KNOWN_RUNS:
            log.warning(
                "%s is at run %d on this registry: the guardian only recognises the first %d and will treat "
                "a genuine confirmation as forged",
                order_id, high, GUARDIAN_KNOWN_RUNS,
            )

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
            await self._claim_chain_id(run)
            await self._script(run)
        except asyncio.CancelledError:
            raise
        except ChainReverted as err:
            log.warning("chain refused %s: %s", err.function, err.reason)
            self._reverted(run, err)
            detail = texts.CHAIN_REFUSED_DETAIL.format(function=err.function, reason=err.reason)
            if run.hold is not None:
                # Fail safe: the money stays in the hold. Saying "stopped" would be wrong while it is still there.
                run.status = "held"
                self._alert(
                    run, "analyst", texts.ANALYST, "IN_APP", texts.CHAIN_REFUSED_HELD.format(detail=detail),
                    headline=texts.CHAIN_REFUSED_HEADLINE,
                )
            else:
                run.status = "stopped"
                self._emit(
                    run,
                    "payment.stopped",
                    {"headline": texts.CHAIN_REFUSED_HEADLINE, "detail": detail},
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
            # Fail safe: say so on the stream, keep any hold, and never leave the screen on "in transit".
            log.exception("scenario %s failed", run.scenario)
            self._degrade("engine")
            if run.hold is not None:
                run.status = "held"
                self._alert(
                    run, "analyst", texts.ANALYST, "IN_APP", texts.ENGINE_ERROR_HELD, headline=texts.ENGINE_ERROR_HEADLINE
                )
            else:
                detail = texts.ENGINE_ERROR_DETAIL.format(status=run.status)
                run.status = "stopped"
                self._alert(run, "analyst", texts.ANALYST, "IN_APP", detail, headline=texts.ENGINE_ERROR_HEADLINE)
                self._emit(run, "payment.stopped", {"headline": texts.ENGINE_ERROR_HEADLINE, "detail": detail})

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
        scenario = self._scenario(run.scenario)
        assert scenario is not None
        self.telecom.clear()
        swap_hours = scenario.sim_swap_hours_ago if scenario.sim_swap_hours_ago is not None else self._injected_sim_swap
        self._injected_sim_swap = None
        if swap_hours is not None:
            contact = PAYEES[order.payee_id].known_contacts[0]
            self.telecom.declare_swap(contact.msisdn_masked, hours_ago=swap_hours)
        order = run.order = self._verified_order(order)

        scenario_name = CUSTOM if run.scenario in self._custom_scenarios else run.scenario
        self._emit(run, "scenario.started", {"scenario": scenario_name, "speed": pacer.speed, "auto": run.auto})
        if scenario.rail_down is not None:
            await pacer.wait(600)
            self.rail_down(scenario.rail_down)
        await pacer.wait(400)
        self._emit(run, "payment.created", self._payment_created(order))
        check = self._payee_checks.get(order.creditor_account_id)
        if check is not None and check.get("result") == "DENIED":
            # Protect before approval: the supplier already said this account is not theirs.
            account = ACCOUNTS[order.creditor_account_id]
            run.status = "stopped"
            self._emit(
                run,
                "payment.stopped",
                {
                    "headline": texts.DENIED_ACCOUNT_HEADLINE,
                    "detail": texts.DENIED_ACCOUNT_DETAIL.format(
                        payee=texts.payee_short(PAYEES[order.payee_id]), at=check["at"], account=account.account_masked, holder=account.holder_name
                    ),
                    "blockedBy": "PAYEE_VERIFICATION_DENIED",
                },
                simulated=True,
            )
            self._alert(run, "payer", PAYER.approvers[0].name, "IN_APP", texts.ALERT_DENIED_ACCOUNT)
            return
        self._observe_order(order)
        await self._detect_clusters(pacer, self._auto_humans(run))

        await pacer.wait(900)
        norms = self.norms.evaluate(order)
        self._emit(run, "norms.checked", norms.to_event_data())

        await pacer.wait(900)
        context = build_risk_context(order, norms.signal_codes, sanctions_hit=norms.sanctions_hit)
        risk = self._overlays(order, self.risk.score(order, context))
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
            limits=RerouteLimits(self.settings.reroute_max_fees_eur, self.settings.reroute_max_days),
        )
        run.decision = decision
        if decision.route_eval is None and decision.blocked_by == PAYER_LIMIT:
            # An operational wait, not a fraud case: nothing is sent and the payer is told in the app.
            run.status = "stopped"
            self._emit(
                run,
                "payment.stopped",
                {"headline": texts.NO_ROUTE_LIMITS_HEADLINE, "detail": decision.reason, "blockedBy": PAYER_LIMIT, "scores": decision.scores},
            )
            self._alert(run, "payer", PAYER.approvers[0].name, "IN_APP", texts.ALERT_WAITING_ROUTE)
            return
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
            if hop["kind"] == "chain" and hold_mode is None and self.confidential is not None:
                # No hold is needed, so the chain leg can be confidential (a held payment keeps the public escrow).
                if not await self._confidential_leg(run, index, hop):
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
        swift_score = next((score for score in decision.scores if score["routeId"] == "R1"), None)
        self._emit(
            run,
            "payment.credited",
            {
                "at": run.hops[-1]["to"],
                "feesEur": decision.fees_eur,
                "routeCostEur": decision.s_selected,
                "swiftRouteCostEur": decision.s_swift,
                "cashCostEur": decision.cost["cashCostEur"],
                "swiftCashCostEur": swift_score["cashCostEur"] if swift_score else None,
                "fxMarginEur": decision.cost["fxMarginEur"],
                "recipientGetsGhs": decision.recipient_gets_ghs,
                "etaMinutes": decision.eta_minutes,
                "swiftEtaLabel": swift_score["etaLabel"] if swift_score else None,
                "swiftEtaMinutes": swift_score["etaMinutes"] if swift_score else None,
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

    async def _confidential_leg(self, run: PaymentRun, index: int, hop: dict[str, str]) -> bool:
        """The chain leg as an eERC confidential transfer, after the adapter accepted the leg. Returns False
        (payment stopped) only when the auditor's amount does not match. If the confidential leg cannot
        be made, the leg stays public and the banner says so."""
        assert self.confidential is not None
        amount = run.order.amount.as_float
        try:
            receipt = await asyncio.wait_for(
                asyncio.to_thread(self.confidential.transfer, run.order.id, amount), timeout=CONFIDENTIAL_TIMEOUT_S
            )
        except Exception as err:
            why = str(err) if str(err) else type(err).__name__
            log.warning("confidential leg unavailable (%s); the leg stays public", why)
            self._degrade("confidential")
            self._alert(run, "analyst", texts.ANALYST, "IN_APP", texts.CONFIDENTIAL_FALLBACK.format(why=why))
            return True
        matches = receipt.auditor_amount_eur is not None and abs(receipt.auditor_amount_eur - amount) < 0.005
        self._emit(
            run,
            "confidential.transfer",
            {
                "hop": index,
                "from": hop["from"],
                "to": hop["to"],
                "token": TOKEN,
                "amountHidden": True,
                "txHash": receipt.tx_hash,
                "explorerUrl": receipt.explorer_url,
                "depositTxHash": receipt.deposit_tx_hash,
                "withdrawTxHash": receipt.withdraw_tx_hash,
                "auditorDecryptedAmountEur": receipt.auditor_amount_eur,
                "auditorMatches": matches,
                "metadataEncrypted": receipt.metadata_payment_id is not None,
                "hidden": list(HIDDEN),
                "visible": list(VISIBLE),
                "text": texts.CONFIDENTIAL_TRANSFER.format(amount=texts.eur(amount)) if matches else None,
            },
            simulated=receipt.simulated,
        )
        if matches:
            return True
        seen = "unknown" if receipt.auditor_amount_eur is None else texts.eur(receipt.auditor_amount_eur)
        detail = texts.CONFIDENTIAL_MISMATCH.format(seen=seen, expected=texts.eur(amount))
        self._alert(run, "analyst", texts.ANALYST, "IN_APP", detail, headline=texts.CONFIDENTIAL_MISMATCH_HEADLINE)
        run.status = "stopped"
        self._emit(run, "payment.stopped", {"headline": texts.CONFIDENTIAL_MISMATCH_HEADLINE, "detail": detail}, simulated=True)
        return False

    # --- hold, out-of-band check, outcome ----------------------------------------------------

    async def _open_case(self, run: PaymentRun, situation: str) -> None:
        """Ask for the analyst's case file. Without a case writer it is built from the rules, at once.

        ``situation`` is where the payment stands: ``held`` (the supplier is asked), ``analyst`` (the
        known contact cannot be trusted) or ``blocked`` (no route at this risk level).
        """
        assert run.risk is not None
        events = [event for event in self.bus.events if event["paymentId"] == run.order.id]
        live_invoice_ready = run.invoice_text is not None and self.case.live_writer_ready
        if run.invoice_text is not None and not live_invoice_ready:
            self._degrade("llm")
        if self.case.writer is None and not live_invoice_ready:
            await run.pacer.wait(700)
            self._case_ready(
                run, self.case.write(run.order, run.risk, events, situation, document=run.invoice_text)
            )
        else:
            run.case_task = asyncio.create_task(self._write_case(run, events, situation))

    async def _write_case(self, run: PaymentRun, events: list[dict[str, Any]], situation: str) -> None:
        assert run.risk is not None
        try:
            case = await asyncio.wait_for(
                asyncio.to_thread(
                    self.case.write,
                    run.order,
                    run.risk,
                    events,
                    situation,
                    document=run.invoice_text,
                ),
                timeout=CASE_TIMEOUT_S,
            )
        except Exception as err:
            log.warning("case file not ready in time (%s); using the one built from the rules", type(err).__name__)
            self._degrade("llm")
            case = rules_case_file(run.order, run.risk, events, situation)
        if self.case.requested == "live" and case.llm != "live":
            # Mistral did not answer and the writer fell back to cached text or the rules: say so on the banner.
            # (In cached mode the template for a scene without cached text is expected, not a failure.)
            self._degrade("llm")
        self._case_ready(run, case)

    def _case_ready(self, run: PaymentRun, case: CaseFile) -> None:
        if run.invoice_text is not None:
            case = redact_case_document(case, run.invoice_text)
        run.case = case
        self._emit(run, "case.ready", case.model_dump(by_alias=True, mode="json"))

    async def _until_decided(self, run: PaymentRun, *futures: asyncio.Future[str]) -> None:
        """Wait for one of the futures, but not beyond the hold's expiry (demo clock or real time)."""
        waiting = set(futures) | ({run.expiry} if run.expiry is not None else set())
        timeout = max((run.hold_until - run.pacer.now()).total_seconds(), 0.0) if run.hold_until is not None else None
        done, _ = await asyncio.wait(waiting, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done and run.expiry is not None and not run.expiry.done():
            run.expiry.set_result("EXPIRED")

    @staticmethod
    def _expired(run: PaymentRun) -> bool:
        return run.expiry is not None and run.expiry.done()

    @staticmethod
    async def _case_written(run: PaymentRun) -> None:
        """Simulated people act once the case file is out (the writer runs in a thread, bounded by CASE_TIMEOUT_S)."""
        if run.case_task is not None:
            await asyncio.wait({run.case_task})

    async def _await_analyst(self, run: PaymentRun) -> str:
        """The analyst's decision, or ``EXPIRED`` when the hold ran out first."""
        assert run.analyst is not None
        run.status = "awaiting_analyst"
        if self._auto_humans(run) and not run.analyst.done():
            await run.pacer.wait(ANALYST_AUTO_MS)
            await self._case_written(run)
            if not run.analyst.done():
                run.analyst_by = texts.REVOKED_BY
                run.analyst.set_result("CONFIRM_REVOCATION")
        await self._until_decided(run, run.analyst)
        return run.analyst.result() if run.analyst.done() else "EXPIRED"

    async def _await_supplier_or_analyst(self, run: PaymentRun) -> tuple[str, str]:
        """The supplier's answer, unless the analyst revokes first or the guardian freezes the hold."""
        assert run.analyst is not None and run.escalation is not None
        run.answer = asyncio.get_running_loop().create_future()
        run.status = "awaiting_supplier"
        if run.auto:
            await run.pacer.wait(SUPPLIER_AUTO_MS)
            await self._case_written(run)
            if not (run.answer.done() or run.analyst.done() or run.escalation.done()):
                scenario = self._scenario(run.scenario)
                if scenario is not None and scenario.supplier_silent:
                    # Nobody answers: the demo clock jumps to the hold's expiry instead of waiting a day.
                    self.advance_clock(self.settings.escrow_hold_seconds / 3600)
                else:
                    run.answer.set_result(run.auto_answer)
        await self._until_decided(run, run.answer, run.analyst, run.escalation)
        decided = run.analyst.done() or run.escalation.done() or self._expired(run)
        if decided and not run.answer.done():
            run.answer.cancel()
        if run.analyst.done():
            return "analyst", run.analyst.result()
        if run.escalation.done():
            return "guardian", run.escalation.result()
        if self._expired(run):
            return "expired", "EXPIRED"  # a late answer cannot release a hold that ran out
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
        run.hold, run.hold_hop, run.hold_expires_at, run.hold_until = mode, hop_index, iso_ms(expires), expires
        run.analyst = asyncio.get_running_loop().create_future()
        run.escalation = asyncio.get_running_loop().create_future()
        run.expiry = asyncio.get_running_loop().create_future()

        payee = PAYEES.get(order.payee_id)
        contact = payee.known_contacts[0] if payee is not None and payee.known_contacts else None
        custom = run.scenario in self._custom_scenarios
        reasons = list(risk.reasons)
        sim_swap_recent = False
        if contact is None:
            # Nobody known can confirm the account out of band: never trust a number given with the payment.
            next_step = texts.NEXT_STEP_NO_CONTACT
            reasons.append(RiskReason(ref="O", text=next_step, rule_id="R-OOB-02"))
        else:
            telecom_msisdn = (
                orange_playground_number(contact.msisdn_masked, run.scenario)
                if isinstance(self.telecom, OrangeSimSwap)
                else contact.msisdn_masked
            )
            max_age_hours = self.settings.sim_swap_max_age_hours
            if isinstance(self.telecom, OrangeSimSwap):
                max_age_hours = max(max_age_hours, ORANGE_PLAYGROUND_MIN_MAX_AGE_HOURS)
            sim_swap_recent = self.telecom.check(telecom_msisdn, max_age_hours)
            if getattr(self.telecom, "degraded", False):
                self._degrade("telecom")
            next_step = (
                texts.NEXT_STEP_CONTACT.format(payee=texts.payee_short(payee), contact=contact.name) if custom else texts.NEXT_STEP
            )
        if sim_swap_recent:
            changed = self.telecom.retrieve_date(telecom_msisdn)
            if getattr(self.telecom, "degraded", False):
                self._degrade("telecom")
            if changed is None and getattr(self.telecom, "degraded", False):
                next_step = texts.NEXT_STEP_ANALYST_UNAVAILABLE
            else:
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
                    (texts.PROTECTION_AMOUNT.format(amount=amount) if custom else texts.PROTECTION)
                    if mode == "escrow"
                    else texts.PROTECTION_BANK.format(amount=amount, bank=bank_name, payer=PAYER.name)
                ),
                "nextStep": next_step,
                "expiresAt": iso_ms(expires),
            },
            simulated=self.chain_simulated if mode == "escrow" else True,
        )
        self._alert(run, "payer", PAYER.approvers[0].name, "IN_APP", texts.ALERT_HELD)
        analyst_only = sim_swap_recent or contact is None
        await self._open_case(run, "analyst" if analyst_only else "held")

        await pacer.wait(800)
        self._emit(
            run,
            "verification.requested",
            {
                "contactName": contact.name if contact else texts.NO_CONTACT,
                "contactMasked": contact.msisdn_masked if contact else "—",
                "contactSince": contact.since if contact else "—",
                "channel": "ANALYST" if analyst_only else "SMS",
                "simSwapChecked": True,
                "simSwapRecent": sim_swap_recent,
                "simSwapSource": self.telecom.source,
            },
            simulated=True,
        )
        if analyst_only:
            # Rule R-OOB-01 (number not trusted) or R-OOB-02 (no contact on file): the known number cannot be trusted, so nobody is texted and the analyst decides.
            who, answer = "analyst", await self._await_analyst(run)
        else:
            who, answer = await self._await_supplier_or_analyst(run)

        if who == "analyst":
            await self._stop_held(run, intent, mode, answer, RevocationReason.ANALYST_DECISION)
            return False
        if who == "guardian":
            # The hold is frozen on-chain: the supplier's answer no longer matters, the analyst decides.
            await self._stop_held(run, intent, mode, await self._await_analyst(run), RevocationReason.ANALYST_DECISION)
            return False
        if who == "expired":
            await self._stop_held(run, intent, mode, "EXPIRED", RevocationReason.EXPIRED)
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
        try:
            tx = await self._chain(
                "recordVerification", self.chain.record_verification, attestation, self._sign(run, "verifier_signer", attestation)
            )
        except ChainReverted as err:
            # The registry already holds an answer the engine never signed (a stolen verifier key), or the
            # payment moved on outside the engine. Nothing is released: the analyst revokes and refunds.
            self._reverted(run, err, "recordVerification")
            self._alert(
                run, "analyst", texts.ANALYST, "IN_APP", texts.ALERT_REGISTRY_REFUSED.format(reason=err.reason),
                headline=texts.CHAIN_REFUSED_HEADLINE,
            )
            await self._stop_held(run, intent, mode, await self._await_analyst(run), RevocationReason.ANALYST_DECISION)
            return False
        self._emit(
            run,
            "verification.recorded",
            {
                "result": result.name,
                "answerText": texts.ANSWER_CONFIRM if result == VerificationResult.CONFIRMED else texts.ANSWER_DENY,
                **self._tx_fields(tx),
            },
            simulated=tx.simulated,
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
        started = expires - timedelta(seconds=self.settings.escrow_hold_seconds)
        if not await self._time_lock(run, intent, mode, started):
            return False
        run.hold = None
        run.status = "in_transit"
        return True

    def _time_lock_hours(self, order: PaymentOrder) -> float:
        """First payment to a new account, by amount band (PRD §12.3). Zero when no lock applies."""
        account = ACCOUNTS[order.creditor_account_id]
        payee = PAYEES.get(order.payee_id)
        if (payee is not None and payee.owns(account.id)) or account.successful_payments > 0:
            return 0.0
        amount = order.amount.as_float
        if amount > self.settings.time_lock_long_from_eur:
            return self.settings.time_lock_long_hours
        return self.settings.time_lock_hours if amount >= self.settings.time_lock_from_eur else 0.0

    async def _time_lock(self, run: PaymentRun, intent: PaymentIntent, mode: str, started: datetime) -> bool:
        """Bank hold only (where an escrow exists it stands in for the lock): even confirmed, a first
        payment to a new account does not leave the bank before the lock ends. Returns False when the
        analyst stops the payment in the meantime."""
        assert run.analyst is not None
        hours = self._time_lock_hours(run.order)
        until = started + timedelta(hours=hours)
        if hours <= 0 or run.pacer.now() >= until:
            return True
        run.locked_until, run.time_lock = until, asyncio.get_running_loop().create_future()
        run.status = "time_locked"
        self._emit(
            run,
            "timelock.on",
            {
                "hours": hours,
                "until": iso_ms(until),
                "text": texts.TIME_LOCK_ON.format(amount=texts.eur(run.order.amount.as_float), bank="Banque Hexagone", hours=hours),
            },
            simulated=True,
        )
        if run.auto:
            await run.pacer.wait(TIME_LOCK_AUTO_MS)
            if not run.time_lock.done() and not run.analyst.done():
                self.advance_clock((until - run.pacer.now()).total_seconds() / 3600)
        timeout = max((until - run.pacer.now()).total_seconds(), 0.0)
        await asyncio.wait({run.time_lock, run.analyst}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if run.analyst.done():
            await self._stop_held(run, intent, mode, run.analyst.result(), RevocationReason.ANALYST_DECISION)
            return False
        self._emit(run, "timelock.off", {"reason": "ELAPSED"}, simulated=True)
        return True

    async def _stop_held(
        self, run: PaymentRun, intent: PaymentIntent, mode: str, action: str, reason: RevocationReason
    ) -> None:
        """Stop a held payment after the analyst's decision, or after the kill switch cut its route."""
        bank_name = "Banque Hexagone"
        cause: str | None
        if action == "EXPIRED":
            reason = RevocationReason.EXPIRED
            run.analyst_by = texts.EXPIRY_BY
            detail = texts.STOPPED_DETAIL_EXPIRED if mode == "escrow" else texts.STOPPED_DETAIL_EXPIRED_BANK.format(bank=bank_name)
            alert, cause = texts.ALERT_STOPPED_EXPIRED, None  # silence is not proof: no freeze request to the other bank
        elif action == "KILL_SWITCH":
            reason = RevocationReason.KILL_SWITCH
            detail = texts.STOPPED_DETAIL_KILL if mode == "escrow" else texts.STOPPED_DETAIL_KILL_BANK.format(bank=bank_name)
            alert, cause = texts.ALERT_STOPPED_KILL, texts.FREEZE_CAUSE_KILL
        elif reason == RevocationReason.SUPPLIER_DENIED:
            detail = texts.STOPPED_DETAIL if mode == "escrow" else texts.STOPPED_DETAIL_BANK.format(bank=bank_name)
            alert, cause = texts.ALERT_STOPPED, texts.FREEZE_CAUSE_DENIED
        elif run.incident_id is not None and mode == "escrow":
            detail, alert, cause = texts.STOPPED_DETAIL_GUARDIAN, texts.ALERT_STOPPED_ANALYST, texts.FREEZE_CAUSE_GUARDIAN
        else:
            detail = texts.STOPPED_DETAIL_ANALYST if mode == "escrow" else texts.STOPPED_DETAIL_ANALYST_BANK.format(bank=bank_name)
            alert, cause = texts.ALERT_STOPPED_ANALYST, texts.FREEZE_CAUSE_ANALYST
        await self._revoke_and_refund(run, intent, reason, mode, detail, alert, cause)

    async def _revoke_and_refund(
        self,
        run: PaymentRun,
        intent: PaymentIntent,
        reason: RevocationReason,
        mode: str,
        detail: str,
        payer_alert: str,
        freeze_cause: str | None,
    ) -> None:
        """Revoke in the registry, give the money back, tell who must know (analyst decision or kill switch)."""
        pacer, order, risk = run.pacer, run.order, run.risk
        assert risk is not None
        account = ACCOUNTS[order.creditor_account_id]
        if reason not in (RevocationReason.KILL_SWITCH, RevocationReason.EXPIRED):
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

        if freeze_cause is not None:
            await pacer.wait(1200)
            self._alert(
                run,
                "beneficiary_bank",
                account.institution_id,
                "NETWORK",
                texts.ALERT_FREEZE_REQUEST.format(
                    uetr=order.uetr, account=account.account_masked, holder=account.holder_name, cause=freeze_cause
                ),
                uetr=order.uetr,
            )
        await pacer.wait(2000)
        self._alert(run, "payer", PAYER.approvers[0].name, "SMS", payer_alert)
        run.status = "stopped"
        headline = (
            texts.STOPPED_HEADLINE_AMOUNT.format(amount=texts.eur(float(run.order.amount.value)))
            if run.scenario in self._custom_scenarios
            else texts.STOPPED_HEADLINE
        )
        self._emit(run, "payment.stopped", {"headline": headline, "detail": detail}, simulated=True)

    # --- attacks -----------------------------------------------------------------------------

    def _attack_started(self, run: PaymentRun, name: str) -> None:
        if self._current_pacer is None:
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

    async def _attack_stolen_verifier_key(self, run: PaymentRun) -> dict[str, Any]:
        """Scene 4: a thief holding the verifier key confirms a held payment, then tries to release it.

        On a simulated chain the engine also plays the guardian (freeze, pause, report). On Fuji the real
        guardian must be watching, so the scene is run with Lane C's script instead.
        """
        if not self.chain_simulated:
            raise AttackNotApplicable(
                "on a real chain run `uv run python -m sylo_chain.stolen_verifier_key <paymentId>` with the guardian watching"
            )
        waiting = run.answer is not None and not run.answer.done()
        if run.intent is None or run.hold != "escrow" or run.frozen or not waiting:
            raise AttackNotApplicable("this payment is not held in escrow waiting for the supplier's answer")
        intent, pacer = run.intent, run.pacer
        self._attack_started(run, "stolen_verifier_key")
        domain = self.chain.domain()
        forged = VerificationAttestation(
            payment_id=intent.payment_id,
            intent_hash=to_hex(digest(intent, domain)),
            method=int(VerificationMethod.OOB_KNOWN_CONTACT),
            result=int(VerificationResult.CONFIRMED),
            sim_swap_checked=True,
            evidence_hash=hash_record({"paymentId": run.order.id, "forged": True}),
            verified_at=int(pacer.now().timestamp()),
            nonce=self.signer.next_nonce("verifier_signer"),
        )
        # Signed with the real key but never recorded by the engine: that gap is what the guardian looks for.
        tx = await self._chain(
            "recordVerification", self.chain.record_verification, forged, self.signer.sign("verifier_signer", forged, domain)
        )

        await pacer.wait(GUARDIAN_REACTION_MS)
        await self._chain("freeze", self.chain.freeze, run.chain_pid)
        await self._chain("pauseCorridor", self.chain.pause_corridor, intent.corridor_id)
        incident = self.guardian_incident(
            {
                "rule": "CONFIRMED_WITHOUT_OOB_RECORD",
                "action": "FREEZE_AND_PAUSE",
                "txHash": tx.tx_hash,
                "explorerUrl": tx.explorer_url,
                "paymentId": run.order.id,
                "simulated": True,
            },
            escalate=False,  # the run's script goes on once the thief's release has been seen to fail
        )

        await pacer.wait(THIEF_RELEASE_MS)
        result = {"ok": True, "reverted": False, "reason": None, "incidentId": incident["incidentId"]}
        try:
            await self._chain("release", self.chain.release, run.chain_pid, "attacker")
        except ChainReverted as err:
            self._reverted(run, err, "release")
            result.update(reverted=True, reason=err.reason)
        else:
            log.error("release() on a frozen hold did NOT revert: the chain port is broken")
        self._escalate(run)
        return result

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
    keys_missing = False
    if settings.chain_mode == "fuji":
        # The public dev keys are fine on a simulated chain, never on a real one: without the real keys, use the mock chain.
        try:
            signer = Signer(env, allow_dev_keys=False)
        except RuntimeError as err:
            log.warning("CHAIN_MODE=fuji but %s; using the mock chain", err)
            settings = dataclasses.replace(settings, chain_mode="mock")
            signer = Signer(env)
            keys_missing = True
    else:
        signer = Signer(env)
    holder: dict[str, Orchestrator] = {}
    risk, chain, degraded = load_ports(settings, signer=signer, clock=lambda: holder["o"].now().timestamp())
    if keys_missing:
        degraded.append("chain")
    if chain.mode != "mock":
        # The registry outlives this process and keeps every nonce: start from this session's own base
        # (microseconds since the epoch), so no message repeats a nonce of an earlier session.
        signer.start_nonces_at(time.time_ns() // 1_000)
    writer, llm_degraded, live_writer, live_writer_ready = load_case_writer(settings, env)
    if llm_degraded:
        degraded.append("llm")
    confidential, confidential_degraded = load_confidential_leg(
        settings.confidential_mode, settings.eerc_url, settings.explorer_base_url
    )
    if confidential_degraded:
        degraded.append("confidential")
    telecom = (
        OrangeSimSwap(
            client_id=env.get("ORANGE_CLIENT_ID", ""),
            client_secret=env.get("ORANGE_CLIENT_SECRET", ""),
        )
        if settings.telecom_mode == "orange-playground"
        else None
    )
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
        case=CaseService(
            settings.llm_mode,
            writer,
            live_writer=live_writer,
            live_writer_ready=live_writer_ready,
        ),
        journal=journal,
        confidential=confidential,
        telecom=telecom,
    )
    holder["o"] = orchestrator
    return orchestrator
