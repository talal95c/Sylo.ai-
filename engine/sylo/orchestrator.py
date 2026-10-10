"""Orchestrator: the payment state machine and the scenario scripts.

One payment goes through NORMS → RISK → COST → COMMIT → ACTION. Every step is published
as an event; every wait goes through the pacer. The intent is committed before any leg is
sent, MEDIUM payments stop in escrow until the supplier answers on a known contact, and
nothing is ever released by default.

    Deciding → Committed → InTransit → (LOW) Credited
                                      → (MEDIUM) Held → AwaitingSupplier → Revoked → Refunded → Stopped
                                                                          → Released → InTransit → Credited
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional

from sylo_spec import scenarios
from sylo_spec.canonical import hex0x, payment_id_bytes, record_hash
from sylo_spec.models import Hop, PaymentIntent, PaymentOrder, RevocationReason, RiskResult, Status, Tier, TxRef, VerificationResult
from sylo_spec.ports import ChainReverted

from . import norms as norms_engine
from . import texts
from .bus import EventBus
from .config import Settings
from .pacer import iso_millis
from .ports_loader import Ports
from .router import RouteDecision, select_route
from .signer import Signer, approval_hash_hex

log = logging.getLogger("sylo.orchestrator")

DUAL_CONTROL_THRESHOLD_EUR = 20_000
ATTACKS = ("release_revoked",)

# Delays in milliseconds at speed 1 (build spec, section 5.10). The pacer divides them by the speed.
D_CREATED, D_NORMS, D_RISK, D_ROUTE, D_APPROVAL, D_COMMIT = 400, 900, 900, 900, 1000, 900
D_LEG_GAP, D_EXECUTED, D_CREDITED = 300, 400, 300
D_DEPOSIT, D_HELD, D_VERIFICATION_REQUEST, D_AUTO_ANSWER = 1100, 200, 1500, 3000
D_VERIFICATION_RECORDED, D_REVOKED, D_REFUNDED, D_STOPPED = 800, 1500, 1000, 3200
D_RELEASED, D_RELEASE_EXECUTED, D_CHAIN_HOP_REST = 1000, 300, 1100
D_REVERTED = 900


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


@dataclass
class PaymentRun:
    payment_id: str
    scenario: str
    order: PaymentOrder
    speed: float
    auto: bool
    auto_answer: str
    status: str = "deciding"
    tier: Optional[Tier] = None
    route_id: Optional[str] = None
    risk: Optional[RiskResult] = None
    decision: Optional[RouteDecision] = None
    intent: Optional[PaymentIntent] = None
    intent_digest: Optional[bytes] = None
    hops: list[Hop] = field(default_factory=list)
    hop_labels: list[str] = field(default_factory=list)
    answer: Optional[asyncio.Future] = None
    last_seq: int = 0


class Orchestrator:
    def __init__(self, settings: Settings, bus: EventBus, pacer, ports: Ports, signer: Signer):
        self.settings = settings
        self.bus = bus
        self.pacer = pacer
        self.ports = ports
        self.signer = signer
        self.pack = norms_engine.load_pack(scenarios.CORRIDOR)
        self.payments: dict[str, PaymentRun] = {}
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ small helpers

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def wait_idle(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    def _emit(self, run: Optional[PaymentRun], type_: str, data: dict[str, Any], simulated: bool = False) -> dict[str, Any]:
        event = self.bus.publish(type_, run.payment_id if run else None, data, simulated)
        if run is not None:
            run.last_seq = event["seq"]
        return event

    async def _wait(self, ms: float) -> None:
        await self.pacer.wait(ms)

    async def _chain(self, fn, *args, **kwargs) -> TxRef:
        """Chain calls are synchronous; run them off the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _now_ts(self) -> int:
        return int(self.pacer.now().timestamp())

    @staticmethod
    def _tx_fields(tx: TxRef) -> dict[str, Any]:
        return {"txHash": tx.tx_hash, "explorerUrl": tx.explorer_url}

    @staticmethod
    def _reasons(risk: RiskResult) -> list[dict[str, str]]:
        out = []
        for reason in risk.reasons:
            item = {"ref": reason.ref, "text": reason.text}
            if reason.rule_id:
                item["ruleId"] = reason.rule_id
            out.append(item)
        return out

    # ------------------------------------------------------------------ public API

    def start(self, name: str, speed: Optional[float] = None, auto: bool = False, auto_answer: str = "deny") -> str:
        if name not in scenarios.SCENARIOS:
            raise NotFound(f"unknown scenario: {name}")
        if self.running:
            raise Conflict("a scenario is running")
        if auto_answer not in ("deny", "confirm"):
            raise Conflict("autoAnswer must be 'deny' or 'confirm'")
        order = scenarios.order(name)
        speed = float(speed if speed else self.settings.demo_speed)
        run = PaymentRun(payment_id=order.payment_id, scenario=name, order=order, speed=speed, auto=auto, auto_answer=auto_answer)
        self.payments[run.payment_id] = run
        self.pacer.speed = max(speed, 0.01)
        forget = getattr(self.ports.chain, "forget", None)
        if callable(forget):  # mock only: the same demo payment id can be run again
            forget(payment_id_bytes(run.payment_id))
        self._task = asyncio.create_task(self._guarded(run))
        return run.payment_id

    def supplier_response(self, payment_id: str, answer: str) -> None:
        run = self.payments.get(payment_id)
        if run is None:
            raise NotFound(f"unknown payment: {payment_id}")
        if answer not in ("confirm", "deny"):
            raise Conflict("answer must be 'confirm' or 'deny'")
        if run.status != "awaiting_supplier" or run.answer is None or run.answer.done():
            raise Conflict("the payment is not waiting for a supplier answer")
        run.answer.set_result(answer)

    async def attack(self, name: str, payment_id: str) -> dict[str, Any]:
        if name not in ATTACKS:
            raise NotFound(f"unknown attack: {name}")
        run = self.payments.get(payment_id)
        if run is None:
            raise NotFound(f"unknown payment: {payment_id}")
        pid = payment_id_bytes(payment_id)
        if await asyncio.to_thread(self.ports.chain.status, pid) != Status.REVOKED:
            raise Conflict("release_revoked only makes sense on a revoked payment")
        simulated = self.ports.chain.mode == "mock"
        self._emit(run, "attack.attempted", {"attack": name, "description": texts.ATTACK_RELEASE_REVOKED, "by": "attacker"}, simulated)
        try:
            await self._chain(self.ports.chain.release, pid, caller="attacker")
        except ChainReverted as err:
            await self._wait(D_REVERTED)
            tx = err.tx
            self._emit(
                run,
                "tx.reverted",
                {
                    "function": "release",
                    "reason": err.reason,
                    "txHash": tx.tx_hash if tx else None,
                    "explorerUrl": tx.explorer_url if tx else None,
                    "text": texts.reverted(err.reason),
                },
                tx.simulated if tx else simulated,
            )
            return {"ok": True, "reverted": True, "reason": err.reason}
        log.error("release of a revoked payment did not revert: %s", payment_id)
        return {"ok": True, "reverted": False, "reason": None}

    async def reset(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        forget = getattr(self.ports.chain, "forget", None)
        if callable(forget):
            for payment_id in self.payments:
                forget(payment_id_bytes(payment_id))
        self.payments.clear()
        self.bus.reset()
        self._emit(None, "session.reset", {})

    def payment_view(self, payment_id: str) -> dict[str, Any]:
        run = self.payments.get(payment_id)
        if run is None:
            raise NotFound(f"unknown payment: {payment_id}")
        chain_status = self.ports.chain.status(payment_id_bytes(payment_id))
        return {
            "paymentId": run.payment_id,
            "status": run.status,
            "tier": run.tier.name if run.tier is not None else None,
            "routeId": run.route_id,
            "chainStatus": Status(chain_status).name,
            "lastSeq": run.last_seq,
        }

    # ------------------------------------------------------------------ pipeline

    async def _guarded(self, run: PaymentRun) -> None:
        try:
            await self._pipeline(run)
        except asyncio.CancelledError:
            raise
        except ChainReverted as err:
            # Fail safe: the payment stays where it is. Nothing is released by default.
            log.error("chain call reverted for %s in state %s: %s", run.payment_id, run.status, err.reason)
        except Exception:
            log.exception("scenario %s stopped in state %s", run.scenario, run.status)

    async def _pipeline(self, run: PaymentRun) -> None:
        order = run.order
        chain = self.ports.chain
        sim_chain = chain.mode == "mock"
        account = scenarios.account(order.creditor.account_id)
        payee = scenarios.PAYEES.get(order.creditor.payee_id)
        amount_eur = order.amount.as_float()
        payer_name = order.payer.short_name or order.payer.name
        supplier_name = (payee.short_name or payee.legal_name) if payee else order.creditor.payee_name

        self._emit(run, "scenario.started", {"scenario": run.scenario, "speed": run.speed, "auto": run.auto})

        # --- order received
        await self._wait(D_CREATED)
        created: dict[str, Any] = {
            "uetr": order.uetr,
            "payer": {"id": order.payer.id, "name": order.payer.name, "institutionId": order.payer.institution_id},
            "beneficiary": {
                "payeeName": order.creditor.payee_name,
                "accountHolder": order.creditor.account_holder,
                "accountMasked": order.creditor.account_masked,
                "institutionId": order.creditor.institution_id,
                "knownPayee": payee is not None,
                "knownAccount": payee is not None and payee.account(account.id) is not None,
            },
            "amount": {"value": order.amount.value, "currency": order.amount.currency},
            "purpose": order.purpose,
            "invoiceRef": order.invoice_ref,
            "provenance": order.provenance,
        }
        if order.sender_domain:
            created["senderDomain"] = order.sender_domain
        self._emit(run, "payment.created", created)

        # --- 1. NORMS: hard filter on routes, signals for the risk engine
        await self._wait(D_NORMS)
        norms = norms_engine.evaluate(order, account, payee, scenarios.SUPPLIER_INSTITUTION_ID, self.pack)
        self._emit(run, "norms.checked", norms.to_event())

        # --- 2. RISK: sets the tier, which restricts the routes
        await self._wait(D_RISK)
        ctx = scenarios.build_risk_context(order, norms.signal_codes, self.pacer.now())
        risk = self.ports.risk.score(order, ctx)
        run.risk, run.tier = risk, risk.tier
        self._emit(
            run,
            "risk.scored",
            {"score": risk.score, "tier": risk.tier.name, "rulesFired": risk.rules_fired, "reasons": self._reasons(risk), "model": risk.model},
        )

        # --- 3. COST: best remaining route (fraud risk is not an input of the score)
        await self._wait(D_ROUTE)
        decision = select_route(norms, risk.tier, amount_eur, self.pack)
        run.decision = decision
        if decision.selected is None:
            run.status = "blocked"  # HIGH or CRITICAL: no route, an analyst decides (v1)
            return
        route = decision.selected
        run.route_id = route.route.id
        run.hops, run.hop_labels = route.hops, route.hop_labels
        self._emit(run, "route.selected", decision.to_event(amount_eur))

        # --- approval (automatic in v0; payer panel in v1)
        await self._wait(D_APPROVAL)
        approvers = order.payer.approvers[:1]
        method = "SCA"
        if amount_eur >= DUAL_CONTROL_THRESHOLD_EUR and len(order.payer.approvers) > 1:
            approvers, method = order.payer.approvers[:2], "DUAL_CONTROL"
        conditional = risk.tier == Tier.MEDIUM
        approval = {
            "paymentId": order.payment_id,
            "by": [{"name": a.name, "role": a.role} for a in approvers],
            "method": method,
            "conditional": conditional,
            "approvedAt": iso_millis(self.pacer.now()),
        }
        self._emit(
            run,
            "approval.granted",
            {"by": approval["by"], "method": method, "conditional": conditional, "approvalHash": approval_hash_hex(approval)},
        )

        # --- 4. COMMIT: the signed intent is recorded before any money moves
        await self._wait(D_COMMIT)
        decision_record = {
            "paymentId": order.payment_id,
            "packVersion": norms.pack_version,
            "normChecks": [c for r in norms.routes for c in r.checks],
            "signals": norms.signal_codes,
            "risk": {"score": risk.score, "tier": risk.tier.name, "rulesFired": risk.rules_fired, "model": risk.model},
            "route": {"routeId": route.route.id, "scores": decision.scores},
        }
        domain = chain.domain()
        intent = self.signer.build_intent(order, risk.tier, decision_record, approval, self._now_ts())
        run.intent = intent
        tx = await self._chain(chain.commit, intent, self.signer.sign_intent(domain, intent))
        run.intent_digest = await asyncio.to_thread(chain.intent_hash, intent.payment_id)
        run.status = "committed"
        self._emit(run, "intent.committed", {"intentHash": hex0x(run.intent_digest), "tier": risk.tier.name, **self._tx_fields(tx)}, tx.simulated)

        # --- 5. ACTION
        if risk.tier == Tier.LOW:
            await self._legs(run, range(len(run.hops)))
            await self._wait(D_EXECUTED)
            tx = await self._chain(chain.mark_executed, intent.payment_id, record_hash({"paymentId": order.payment_id, "uetr": order.uetr}))
            self._emit(run, "intent.executed", self._tx_fields(tx), tx.simulated)
            await self._credit(run)
            return

        if route.route.settlement != "ONCHAIN_ESCROW":
            # Bank hold on R1 is part of v1 (rail adapters). Fail safe: the payment stays committed, nothing moves.
            log.warning("settlement %s is not implemented in v0; %s stays committed", route.route.settlement, run.payment_id)
            return

        chain_hop = next(i for i, hop in enumerate(run.hops) if hop.kind == "chain")
        await self._legs(run, range(chain_hop))

        # the chain hop starts, and the money stops in escrow halfway
        await self._wait(D_LEG_GAP)
        self._send_leg(run, chain_hop)
        await self._wait(D_DEPOSIT)
        tx = await self._chain(chain.deposit, intent, self.signer.addresses.payer_treasury)
        expires_at = iso_millis(self.pacer.now() + timedelta(seconds=self.settings.escrow_hold_seconds))
        run.status = "held"
        self._emit(
            run,
            "escrow.deposited",
            {"amount": order.amount.value, "token": route.route.extra.get("token", "tEURC"), "expiresAt": expires_at, **self._tx_fields(tx)},
            tx.simulated,
        )
        await self._wait(D_HELD)
        contact = payee.known_contacts[0] if payee and payee.known_contacts else None
        contact_name = contact.name if contact else supplier_name
        self._emit(
            run,
            "payment.held",
            {
                "hop": chain_hop,
                "at": "escrow",
                "tier": risk.tier.name,
                "headline": texts.HELD_HEADLINE,
                "reasons": self._reasons(risk),
                "protection": texts.protection(amount_eur, payer_name),
                "nextStep": texts.next_step(supplier_name, contact_name),
                "expiresAt": expires_at,
            },
        )

        # out-of-band verification on the contact already on file, after a SIM-swap check (telecom mock)
        await self._wait(D_VERIFICATION_REQUEST)
        run.answer = asyncio.get_running_loop().create_future()
        run.status = "awaiting_supplier"
        self._emit(
            run,
            "verification.requested",
            {
                "contactName": contact_name,
                "contactMasked": contact.msisdn_masked if contact else "",
                "contactSince": contact.registered_at.isoformat() if contact else "",
                "channel": "SMS",
                "simSwapChecked": True,
                "simSwapRecent": False,
            },
            True,
        )
        if run.auto:
            await self._wait(D_AUTO_ANSWER)
            answer = run.answer.result() if run.answer.done() else run.auto_answer
            if not run.answer.done():
                run.answer.set_result(answer)
        else:
            answer = await run.answer  # no timeout: the money stays in escrow until someone answers

        result = VerificationResult.CONFIRMED if answer == "confirm" else VerificationResult.DENIED
        await self._wait(D_VERIFICATION_RECORDED)
        evidence = {"paymentId": order.payment_id, "contact": contact_name, "answer": answer, "simSwapRecent": False}
        attestation = self.signer.build_attestation(intent, run.intent_digest, result, evidence, self._now_ts())
        tx = await self._chain(chain.record_verification, attestation, self.signer.sign_attestation(domain, attestation))
        answer_text = texts.answer_confirm(contact_name) if answer == "confirm" else texts.answer_deny(contact_name)
        self._emit(run, "verification.recorded", {"result": result.name, "answerText": answer_text, **self._tx_fields(tx)}, tx.simulated)

        if result == VerificationResult.DENIED:
            await self._wait(D_REVOKED)
            revocation = self.signer.build_revocation(intent, RevocationReason.SUPPLIER_DENIED, {"paymentId": order.payment_id, "reason": "SUPPLIER_DENIED"})
            tx = await self._chain(chain.revoke, revocation, self.signer.sign_revocation(domain, revocation))
            run.status = "revoked"
            self._emit(run, "intent.revoked", {"reasonCode": "SUPPLIER_DENIED", "by": texts.ANALYST_AUTO, **self._tx_fields(tx)}, tx.simulated)

            await self._wait(D_REFUNDED)
            tx = await self._chain(chain.refund, intent.payment_id)
            run.status = "refunded"
            self._emit(run, "escrow.refunded", {"to": order.payer.institution_id, "amount": order.amount.value, **self._tx_fields(tx)}, tx.simulated)

            await self._wait(D_STOPPED)
            run.status = "stopped"
            self._emit(run, "payment.stopped", {"headline": texts.stopped_headline(amount_eur, payer_name), "detail": texts.STOPPED_DETAIL})
            return

        # confirmed: the escrow releases to the beneficiary fixed in the intent, then the legs resume
        await self._wait(D_RELEASED)
        tx = await self._chain(chain.release, intent.payment_id)
        run.status = "released"
        self._emit(run, "escrow.released", {"to": run.hops[chain_hop].dst, "amount": order.amount.value, **self._tx_fields(tx)}, tx.simulated)
        await self._wait(D_RELEASE_EXECUTED)
        self._emit(run, "intent.executed", self._tx_fields(tx), tx.simulated)  # release() marks the registry EXECUTED in the same transaction
        await self._wait(D_CHAIN_HOP_REST)
        self._settle_leg(run, chain_hop)
        await self._legs(run, range(chain_hop + 1, len(run.hops)))
        await self._credit(run)

    # ------------------------------------------------------------------ legs (always simulated rails)

    def _send_leg(self, run: PaymentRun, index: int) -> float:
        hop = run.hops[index]
        duration = self.pack.leg_durations_ms.get(hop.kind, 1400.0)
        run.status = "in_transit"
        data = {"hop": index, "from": hop.src, "to": hop.dst, "kind": hop.kind, "rail": run.route_id, "durationMs": duration}
        if index < len(run.hop_labels) and run.hop_labels[index]:
            data["label"] = run.hop_labels[index]
        self._emit(run, "leg.sent", data, True)
        return duration

    def _settle_leg(self, run: PaymentRun, index: int) -> None:
        self._emit(run, "leg.settled", {"hop": index, "at": run.hops[index].dst}, True)

    async def _legs(self, run: PaymentRun, indexes) -> None:
        for index in indexes:
            await self._wait(D_LEG_GAP)
            duration = self._send_leg(run, index)
            await self._wait(duration)
            self._settle_leg(run, index)

    async def _credit(self, run: PaymentRun) -> None:
        await self._wait(D_CREDITED)
        decision = run.decision
        route = decision.selected.route
        run.status = "credited"
        self._emit(
            run,
            "payment.credited",
            {
                "at": run.hops[-1].dst,
                "feesEur": round(route.fees_eur(run.order.amount.as_float()), 2),
                "routeCostEur": decision.cost_eur,
                "swiftRouteCostEur": decision.swift_cost_eur,
                "elapsedLabel": texts.ELAPSED_SIMULATED.format(eta=route.eta_label),
            },
            True,
        )
