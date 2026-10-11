"""Payment state machine and scenario scripts (v0 spec §5.10).

Every wait goes through the run's pacer, every chain call through ``asyncio.to_thread``, and every
step is published on the bus as an event. The web app only draws these events.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, TypeVar

from eth_utils import to_checksum_address

from sylo_spec.canonical import corridor_id_of, hash_record, keccak_text, offchain_hash, to_hex
from sylo_spec.devkeys import dev_address
from sylo_spec.eip712 import digest
from sylo_spec.models import (
    CaseFile,
    PaymentIntent,
    PaymentOrder,
    Revocation,
    RevocationReason,
    RiskResult,
    Status,
    Tier,
    TxRef,
    VerificationAttestation,
    VerificationMethod,
    VerificationResult,
)
from sylo_spec.ports import CasePort, ChainPort, ChainReverted, RiskPort
from sylo_spec.scenarios import ACCOUNTS, ORDERS, PAYEES, PAYER, build_risk_context

from . import texts
from .bus import EventBus
from .config import Settings
from .norms import NormsEngine, NormsResult
from .pacer import Pacer, RealPacer, iso_ms
from .ports_loader import load_ports
from .risk_rules import CombinedRisk
from .router import RouteDecision, choose_route
from .signer import Signer

log = logging.getLogger("sylo.orchestrator")

DEFAULT_TOKEN = to_checksum_address("0x" + "0" * 37 + "e0c")
TOKEN_DECIMALS = 6
BANK_HOP_MS = 1400
CHAIN_HOP_MS = 2200
T = TypeVar("T")


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
    hops: list[dict[str, str]] = field(default_factory=list)
    answer: asyncio.Future[str] | None = None
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
        case: CasePort | None,
        signer: Signer,
        norms: NormsEngine,
        settings: Settings,
        pacer_factory: Callable[[float], Pacer] = RealPacer,
        degraded: list[str] | None = None,
        beneficiary: str | None = None,
        payer_address: str | None = None,
        token: str | None = None,
    ) -> None:
        self.bus = bus
        self.risk = risk
        self.chain = chain
        self.case = case
        self.signer = signer
        self.norms = norms
        self.settings = settings
        self.pacer_factory = pacer_factory
        self.degraded = list(degraded or [])
        self.beneficiary = beneficiary or dev_address("gh_vasp")
        self.payer_address = payer_address or dev_address("eu_casp")
        self.token = token or DEFAULT_TOKEN
        self.boot_id = uuid.uuid4().hex[:12]
        self.chain_simulated = chain.mode != "fuji"
        self._rng = random.Random(settings.seed)
        self._runs: dict[str, PaymentRun] = {}
        self._run_counts: dict[str, int] = {}
        self._task: asyncio.Task[None] | None = None
        self._case_tasks: set[asyncio.Task[None]] = set()
        self._current_pacer: Pacer | None = None

    # --- mode and clock ----------------------------------------------------------------------

    def now(self) -> datetime:
        return self._current_pacer.now() if self._current_pacer else datetime.now(timezone.utc)

    def mode(self) -> dict[str, Any]:
        return {
            "risk": "model" if isinstance(self.risk, CombinedRisk) else "rules",
            "chain": self.chain.mode,
            "llm": self.settings.llm_mode if self.case is not None else "off",
            "rails": "simulated",
            "degraded": list(self.degraded),
            "bootId": self.boot_id,
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

    # --- public operations -------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, name: str, *, speed: float = 1.0, auto: bool = False, auto_answer: str = "deny") -> str:
        """Start a scenario in the background and return its payment id."""
        if name not in ORDERS:
            raise UnknownScenario(name)
        if self.running:
            raise ScenarioBusy()
        run = self._new_run(name, speed, auto, auto_answer)
        self._task = asyncio.create_task(self._execute(run))
        return run.order.id

    async def run_to_end(self, name: str, *, speed: float = 1.0, auto: bool = True, auto_answer: str = "deny") -> PaymentRun:
        """Run a scenario in the foreground (tests and the fixture recorder)."""
        if name not in ORDERS:
            raise UnknownScenario(name)
        if self.running:
            raise ScenarioBusy()
        run = self._new_run(name, speed, auto, auto_answer)
        await self._execute(run)
        return run

    def supplier_response(self, payment_id: str, answer: str) -> None:
        run = self._runs.get(payment_id)
        if run is None:
            raise UnknownPayment(payment_id)
        if run.answer is None or run.answer.done():
            raise NotWaiting(payment_id)
        run.answer.set_result(answer)

    async def attack(self, name: str, payment_id: str) -> dict[str, Any]:
        if name != "release_revoked":
            raise UnknownAttack(name)
        run = self._runs.get(payment_id)
        if run is None:
            raise UnknownPayment(payment_id)
        status = Status(int(await asyncio.to_thread(self.chain.status, run.chain_pid)))
        if status != Status.REVOKED:
            raise AttackNotApplicable(f"payment is {status.name}, not REVOKED")
        self._current_pacer = run.pacer
        self._emit(
            run,
            "attack.attempted",
            {"attack": name, "description": texts.ATTACK_RELEASE_REVOKED, "by": "attacker"},
            simulated=self.chain_simulated,
        )
        try:
            await asyncio.to_thread(self.chain.release, run.chain_pid, "attacker")
        except ChainReverted as err:
            await run.pacer.wait(900)
            self._emit(
                run,
                "tx.reverted",
                {
                    "function": "release",
                    "reason": err.reason,
                    "txHash": err.tx.tx_hash if err.tx else None,
                    "explorerUrl": err.tx.explorer_url if err.tx else None,
                },
                simulated=self.chain_simulated,
            )
            return {"ok": True, "reverted": True, "reason": err.reason}
        log.error("release() on a revoked payment did NOT revert: the chain port is broken")
        return {"ok": True, "reverted": False, "reason": None}

    async def reset(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        for task in list(self._case_tasks):
            task.cancel()
        if self._case_tasks:
            await asyncio.gather(*self._case_tasks, return_exceptions=True)
        self._case_tasks.clear()
        self._runs.clear()
        self._current_pacer = None
        self.bus.clear()
        self.bus.publish("session.reset", {})

    async def payment_info(self, payment_id: str) -> dict[str, Any]:
        run = self._runs.get(payment_id)
        if run is None:
            raise UnknownPayment(payment_id)
        chain_status = Status(int(await asyncio.to_thread(self.chain.status, run.chain_pid)))
        return {
            "paymentId": payment_id,
            "status": run.status,
            "tier": run.tier.name if run.tier is not None else None,
            "routeId": run.decision.route.id if run.decision and run.decision.route else None,
            "chainStatus": chain_status.name,
            "lastSeq": run.last_seq,
        }

    # --- internals ---------------------------------------------------------------------------

    def _new_run(self, name: str, speed: float, auto: bool, auto_answer: str) -> PaymentRun:
        order = ORDERS.get(name)
        if order is None:
            raise UnknownScenario(name)
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

    def _emit(self, run: PaymentRun, type_: str, data: dict[str, Any], *, simulated: bool = False) -> None:
        event = self.bus.publish(type_, data, payment_id=run.order.id, simulated=simulated, ts=run.pacer.now())
        run.last_seq = event["seq"]

    def _schedule_case_ready(self, run: PaymentRun) -> None:
        if self.case is None:
            return
        events = [event for event in self.bus.events if event.get("paymentId") == run.order.id]
        task = asyncio.create_task(self._write_case_ready(run, events))
        self._case_tasks.add(task)
        task.add_done_callback(self._case_tasks.discard)

    async def _write_case_ready(self, run: PaymentRun, events: list[dict[str, Any]]) -> None:
        if self.case is None:
            return
        try:
            if getattr(self.case, "mode", None) == "off":
                result = self.case.write(run.order.id, events)
            else:
                result = await asyncio.to_thread(self.case.write, run.order.id, events)
            case = result if isinstance(result, CaseFile) else CaseFile.model_validate(result)
            self._emit(
                run,
                "case.ready",
                case.model_dump(by_alias=True, mode="json"),
                simulated=self.chain_simulated,
            )
        except Exception as err:
            log.warning("CasePort failed (%s); continuing payment flow", type(err).__name__)

    async def _chain(self, fn: Callable[..., T], *args: Any) -> T:
        return await asyncio.to_thread(fn, *args)

    def _tx_fields(self, tx: TxRef) -> dict[str, Any]:
        return {"txHash": tx.tx_hash, "explorerUrl": tx.explorer_url}

    async def _execute(self, run: PaymentRun) -> None:
        self._current_pacer = run.pacer
        try:
            await self._script(run)
        except asyncio.CancelledError:
            raise
        except ChainReverted as err:
            log.warning("chain refused %s: %s", err.function, err.reason)
            self._emit(
                run,
                "tx.reverted",
                {
                    "function": err.function or "unknown",
                    "reason": err.reason,
                    "txHash": err.tx.tx_hash if err.tx else None,
                    "explorerUrl": err.tx.explorer_url if err.tx else None,
                },
                simulated=self.chain_simulated,
            )
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

    def _build_intent(
        self, run: PaymentRun, norms: NormsResult, risk: RiskResult, decision: RouteDecision, approval_hash: str
    ) -> PaymentIntent:
        order = run.order
        action_tier = (
            Tier.MEDIUM if risk.tier == Tier.HIGH and risk.oob_resolvable else risk.tier
        )
        account = ACCOUNTS[order.creditor_account_id]
        offchain = offchain_hash(
            self._rng.randbytes(32),
            {
                "creditorName": account.holder_name,
                "account": account.account_masked,
                "bank": account.institution_id,
                "invoiceRef": order.documents.invoice_ref,
                "uetr": order.uetr,
            },
        )
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
            offchain_hash=offchain,
            decision_hash=decision_hash,
            approval_hash=approval_hash,
            tier=int(action_tier),
            valid_until=int(run.pacer.now().timestamp()) + 600,
            nonce=self.signer.next_nonce("router_signer"),
        )

    async def _await_answer(self, run: PaymentRun) -> str:
        run.answer = asyncio.get_running_loop().create_future()
        if run.auto:
            await run.pacer.wait(3000)
            if not run.answer.done():
                run.answer.set_result(run.auto_answer)
        return await run.answer

    async def _script(self, run: PaymentRun) -> None:
        pacer, order = run.pacer, run.order
        domain = self.chain.domain()

        self._emit(run, "scenario.started", {"scenario": run.scenario, "speed": pacer.speed, "auto": run.auto})
        await pacer.wait(400)
        self._emit(run, "payment.created", self._payment_created(order))

        await pacer.wait(900)
        norms = self.norms.evaluate(order)
        self._emit(run, "norms.checked", norms.to_event_data())

        await pacer.wait(900)
        risk = self.risk.score(order, build_risk_context(order, norms.signal_codes))
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
        action_tier = (
            Tier.MEDIUM if risk.tier == Tier.HIGH and risk.oob_resolvable else risk.tier
        )
        decision = choose_route(
            norms,
            risk.tier,
            order.amount.as_float,
            self.norms.pack.route_model,
            oob_resolvable=risk.oob_resolvable,
        )
        run.decision = decision
        if decision.route_eval is None:
            run.status = "stopped"
            self._emit(
                run,
                "payment.stopped",
                {"headline": texts.NO_ROUTE_HEADLINE, "detail": decision.reason},
                simulated=False,
            )
            return
        run.hops = decision.route_eval.hops
        self._emit(run, "route.selected", decision.to_event_data())

        await pacer.wait(1000)
        conditional = action_tier == Tier.MEDIUM
        approvers = [{"name": a.name, "role": texts.APPROVER_ROLES.get(a.id, a.role)} for a in PAYER.approvers]
        approval_hash = hash_record(
            {
                "paymentId": order.id,
                "approvers": [a.id for a in PAYER.approvers],
                "method": "DUAL_CONTROL",
                "routeId": decision.route.id,
                "amount": order.amount.value,
                "conditional": conditional,
            }
        )
        self._emit(
            run,
            "approval.granted",
            {"by": approvers, "method": "DUAL_CONTROL", "conditional": conditional, "approvalHash": approval_hash},
            simulated=True,
        )

        await pacer.wait(900)
        intent = self._build_intent(run, norms, risk, decision, approval_hash)
        tx = await self._chain(self.chain.commit, intent, self.signer.sign("router_signer", intent, domain))
        run.intent = intent
        self._emit(
            run,
            "intent.committed",
            {"intentHash": to_hex(digest(intent, domain)), "tier": Tier(intent.tier).name, **self._tx_fields(tx)},
            simulated=tx.simulated,
        )
        run.status = "in_transit"

        executed = False
        escrowed = action_tier == Tier.MEDIUM and decision.settlement == "ONCHAIN_ESCROW"
        for index, hop in enumerate(run.hops):
            duration = CHAIN_HOP_MS if hop["kind"] == "chain" else BANK_HOP_MS
            await pacer.wait(300)
            self._emit(
                run,
                "leg.sent",
                {
                    "hop": index,
                    "from": hop["from"],
                    "to": hop["to"],
                    "kind": hop["kind"],
                    "rail": decision.route.id,
                    "durationMs": round(duration / pacer.speed),
                },
                simulated=True,
            )
            if hop["kind"] == "chain" and escrowed:
                if not await self._hold_and_verify(run, intent, index):
                    return
                executed = True
                await pacer.wait(1100)
            else:
                await pacer.wait(duration)
            self._emit(run, "leg.settled", {"hop": index, "at": hop["to"]}, simulated=True)

        if not executed:
            await pacer.wait(400)
            tx = await self._chain(self.chain.mark_executed, run.chain_pid, keccak_text(f"{order.id}:{decision.route.id}"))
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

    async def _hold_and_verify(self, run: PaymentRun, intent: PaymentIntent, hop_index: int) -> bool:
        """Escrow, out-of-band check and outcome. Returns True when the money was released."""
        pacer, order, risk = run.pacer, run.order, run.risk
        assert risk is not None
        domain = self.chain.domain()

        await pacer.wait(1100)
        tx = await self._chain(self.chain.deposit, intent, self.payer_address)
        expires_at = iso_ms(pacer.now() + timedelta(seconds=self.settings.escrow_hold_seconds))
        self._emit(
            run,
            "escrow.deposited",
            {"amount": order.amount.value, "token": "tEURC", "expiresAt": expires_at, **self._tx_fields(tx)},
            simulated=tx.simulated,
        )

        await pacer.wait(200)
        run.status = "held"
        self._emit(
            run,
            "payment.held",
            {
                "hop": hop_index,
                "at": "escrow",
                "tier": risk.tier.name,
                "headline": texts.HELD_HEADLINE,
                "reasons": [r.to_json_dict() for r in risk.reasons],
                "protection": texts.PROTECTION,
                "nextStep": (
                    f"{texts.NEXT_STEP}\n{texts.HIGH_IDENTITY_ONLY_HOLD}"
                    if risk.tier == Tier.HIGH and risk.oob_resolvable
                    else texts.NEXT_STEP
                ),
                "expiresAt": expires_at,
            },
            simulated=self.chain_simulated,
        )
        self._schedule_case_ready(run)

        await pacer.wait(1500)
        payee = PAYEES[order.payee_id]
        contact = payee.known_contacts[0]
        self._emit(
            run,
            "verification.requested",
            {
                "contactName": contact.name,
                "contactMasked": contact.msisdn_masked,
                "contactSince": contact.since,
                "channel": "SMS",
                "simSwapChecked": True,
                "simSwapRecent": False,
            },
            simulated=True,
        )
        run.status = "awaiting_supplier"
        answer = await self._await_answer(run)

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
            self.chain.record_verification, attestation, self.signer.sign("verifier_signer", attestation, domain)
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
        self._schedule_case_ready(run)

        if result == VerificationResult.DENIED:
            await pacer.wait(1500)
            revocation = Revocation(
                payment_id=intent.payment_id,
                reason_code=int(RevocationReason.SUPPLIER_DENIED),
                case_hash=hash_record({"paymentId": order.id, "reason": "SUPPLIER_DENIED", "rules": risk.rules_fired}),
                nonce=self.signer.next_nonce("analyst_signer"),
            )
            tx = await self._chain(self.chain.revoke, revocation, self.signer.sign("analyst_signer", revocation, domain))
            run.status = "held"
            self._emit(
                run,
                "intent.revoked",
                {"reasonCode": "SUPPLIER_DENIED", "by": texts.REVOKED_BY, **self._tx_fields(tx)},
                simulated=tx.simulated,
            )
            await pacer.wait(1000)
            tx = await self._chain(self.chain.refund, run.chain_pid)
            self._emit(
                run,
                "escrow.refunded",
                {"to": PAYER.institution_id, "amount": order.amount.value, **self._tx_fields(tx)},
                simulated=tx.simulated,
            )
            await pacer.wait(3200)
            run.status = "stopped"
            self._emit(
                run,
                "payment.stopped",
                {"headline": texts.STOPPED_HEADLINE, "detail": texts.STOPPED_DETAIL},
                simulated=True,
            )
            return False

        await pacer.wait(1000)
        tx = await self._chain(self.chain.release, run.chain_pid, "relayer")
        run.status = "in_transit"
        chain_hop = run.hops[hop_index]
        self._emit(
            run,
            "escrow.released",
            {"to": chain_hop["to"], "amount": order.amount.value, **self._tx_fields(tx)},
            simulated=tx.simulated,
        )
        await pacer.wait(300)
        self._emit(run, "intent.executed", self._tx_fields(tx), simulated=tx.simulated)
        return True


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
    risk, chain, case, degraded = load_ports(
        settings,
        signer=signer,
        clock=lambda: holder["o"].now().timestamp(),
        env=env,
    )
    orchestrator = Orchestrator(
        bus=bus or EventBus(),
        risk=risk,
        chain=chain,
        case=case,
        signer=signer,
        norms=NormsEngine(),
        settings=settings,
        pacer_factory=pacer_factory,
        degraded=degraded,
        beneficiary=env.get("GH_VASP_ADDRESS") or None,
        payer_address=env.get("EU_CASP_ADDRESS") or None,
        token=settings.token_address,
    )
    holder["o"] = orchestrator
    return orchestrator
