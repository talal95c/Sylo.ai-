from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from eth_utils import keccak, to_checksum_address
from pydantic import ValidationError

from api.adapters import RailAdapter
from api.agents.investigator import investigate
from api.chain.client import ChainClient, ChainRevert, FakeChain, create_chain_client
from api.chain.signer import (
    CHAIN_ID,
    DEFAULT_VERIFYING_CONTRACT,
    TIER_CODES,
    signer,
)
from api.events import EventBus, event_bus
from api.journal import HashChainJournal
from api.norms import evaluate, norm_r1_signal
from api.risk import score_with_status
from api.risk_fallback import evaluate_rules
from api.routing import load_rails, select_route
from shared.types import PaymentOrder, RiskContext

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "shared" / "fixtures"
FUJI_EURC = "0x5E44db7996c682E92a960b65AC713a54AD815c6B"
DEV_TOKEN = "0x0000000000000000000000000000000000000002"
DEFAULT_PAYER = "0x0000000000000000000000000000000000000003"


def _stable_hash(value: str) -> str:
    return "0x" + keccak(text=value).hex()


def _address_for(value: str) -> str:
    digest = keccak(text=value)[-20:]
    return to_checksum_address("0x" + digest.hex())


def _read_fixture(scene: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"scene{scene}.json").read_text(encoding="utf-8"))


class Orchestrator:
    def __init__(
        self,
        *,
        bus: EventBus = event_bus,
        chain: ChainClient | None = None,
        delay_ms: int | None = None,
    ) -> None:
        self.bus = bus
        self.delay_ms = (
            delay_ms
            if delay_ms is not None
            else self._configured_delay()
        )
        self.chain_mode = os.getenv("CHAIN_MODE", "fake").lower()
        self.chain: ChainClient | None = chain
        self.chain_error: str | None = None
        if self.chain is None:
            try:
                self.chain = create_chain_client(self.chain_mode)
            except Exception as error:
                self.chain_error = type(error).__name__
                LOGGER.warning("Chain dependency unavailable; payments remain held.")
        self.payments: dict[str, dict[str, Any]] = {}
        self.cases: dict[str, dict[str, Any]] = {}
        self.idempotency: dict[str, str] = {}
        self.nonce = 1
        self.kill_switched: set[str] = set()
        self.journals: dict[str, HashChainJournal] = {}
        self.journal: HashChainJournal | None = None
        self.payees: dict[str, dict[str, Any]] = {}
        for scene in ("1", "2"):
            fixture = _read_fixture(scene)
            self.payees[fixture["payeeRegistry"]["id"]] = fixture["payeeRegistry"]
        self.adapters = {
            route["id"]: RailAdapter(
                route["id"],
                self._adapter_publish,
                self._kill_switch,
            )
            for route in load_rails()[1]
        }

    @staticmethod
    def _configured_delay() -> int:
        try:
            return max(0, int(os.getenv("SCENE_DELAY_MS", "600")))
        except ValueError:
            return 600

    def reset(self, *, clear_events: bool = True) -> dict[str, Any]:
        if clear_events:
            self.bus.clear(reset_ids=True)
        if self.chain_mode == "fake":
            self.chain = FakeChain()
            self.chain_error = None
        elif self.chain_mode == "fuji":
            try:
                self.chain = create_chain_client("fuji")
                self.chain_error = None
            except Exception as error:
                self.chain = None
                self.chain_error = type(error).__name__
        self.payments.clear()
        self.cases.clear()
        self.idempotency.clear()
        self.nonce = 1
        self.kill_switched.clear()
        self.journals.clear()
        self.journal = None
        self.adapters = {
            route["id"]: RailAdapter(
                route["id"],
                self._adapter_publish,
                self._kill_switch,
            )
            for route in load_rails()[1]
        }
        return {"status": "ok"}

    async def _pause(self, scene: str | None) -> None:
        if scene is not None and self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)

    def _new_journal(
        self, payment_id: str, uetr: str, scene: str
    ) -> HashChainJournal:
        journal = HashChainJournal(
            bus=self.bus,
            payment_id=payment_id,
            uetr=uetr,
            scene=scene,
        )
        self.journals[payment_id] = journal
        self.journal = journal
        return journal

    def _publish(
        self,
        payment_id: str,
        kind: str,
        data: dict[str, Any],
        *,
        scene: str | None = None,
        uetr: str | None = None,
        explorer_url: str | None = None,
    ) -> dict[str, Any]:
        payment = self.payments.get(payment_id, {})
        selected_scene = scene if scene is not None else payment.get("scene", "api")
        selected_uetr = uetr or payment.get("uetr", payment_id)
        journal = self.journals.get(payment_id)
        if journal is not None and kind != "log.tampered":
            journal.append(kind, data)
        return self.bus.publish(
            kind,
            payment_id,
            selected_uetr,
            selected_scene,
            data,
            explorer_url,
        )

    def _adapter_publish(self, kind: str, data: dict[str, Any]) -> None:
        payment_id = str(data.pop("_paymentId", "pay_scene2"))
        payment = self.payments.get(payment_id, {})
        self._publish(payment_id, kind, data, uetr=payment.get("uetr"))

    def _kill_switch(self, reason: str) -> None:
        rail = next(
            (name for name, adapter in self.adapters.items() if adapter.killed),
            "R3",
        )
        self.kill_switched.add(rail)
        payment_id = self._active_payment_id or "pay_scene2"
        self._publish(
            payment_id,
            "killswitch.on",
            {
                "rail": rail,
                "reason": reason,
                "scope": "adapter",
                "simulated": True,
            },
            scene="2b",
        )

    @property
    def _active_payment_id(self) -> str | None:
        return getattr(self, "active_payment_id", None)

    def _make_context(
        self, order: PaymentOrder, source: dict[str, Any]
    ) -> RiskContext:
        if source.get("riskContext"):
            return RiskContext.model_validate(source["riskContext"])
        provenance = next(iter(order.provenance.values()), "verified_registry")
        registry = source.get("payeeRegistry") or {}
        account_ids = {account.get("id") for account in registry.get("accounts", [])}
        is_new = order.creditor.accountId not in account_ids
        return RiskContext(
            payee_is_new=is_new,
            account_first_seen_days=0 if is_new else 365,
            account_age_days=9 if is_new else 365,
            successful_payments_to_account=0 if is_new else 1,
            name_match=0.5 if is_new else 1.0,
            provenance=provenance,
            amount_eur=float(order.amount.value)
            if order.amount.currency == "EUR"
            else 0,
            norm_r1=False,
        )

    @staticmethod
    def _approval_requirements(order: PaymentOrder, context: RiskContext) -> list[str]:
        amount = float(order.amount.value)
        if amount >= 20_000 or (context.payee_is_new and amount >= 5_000):
            return ["claire", "marc"]
        return ["claire"]

    @staticmethod
    def _approval_blocked(context: RiskContext) -> bool:
        return context.provenance in {
            "invoice_pdf_email",
            "inbound_call",
            "user_input",
        } and (context.payee_is_new or context.account_first_seen_days == 0)

    def _decision_payload(self, payment: dict[str, Any]) -> dict[str, Any]:
        route_result = payment["route"]
        return {
            "paymentId": payment["paymentId"],
            "normChecks": payment["normChecks"],
            "taxNotices": payment["taxNotices"],
            "risk": payment["risk"],
            "route": {
                key: route_result[key]
                for key in (
                    "chosen",
                    "candidates",
                    "settlement",
                    "quoteValidUntil",
                )
            },
            "approval": payment.get("approval"),
            "intent": payment.get("intentSummary"),
        }

    async def submit_order(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        scene: str | None = None,
        allow_blocked_hold: bool = False,
    ) -> dict[str, Any]:
        source = payload if isinstance(payload, dict) else {}
        order_data = source.get("order", source)
        order = PaymentOrder.model_validate(order_data)
        key = idempotency_key or order.id
        if key in self.idempotency:
            payment_id = self.idempotency[key]
            return self.payment_response(payment_id)

        registry = source.get("payeeRegistry")
        if registry is None:
            registry = next(
                (
                    fixture["payeeRegistry"]
                    for fixture in (
                        _read_fixture("1"),
                        _read_fixture("2"),
                    )
                    if fixture["payeeRegistry"]["id"]
                    in self.payees
                ),
                {},
            )
        self.payees[registry.get("id", "default")] = registry
        scoring, rails = load_rails()
        norm_checks, tax_notices = evaluate(order, rails, registry)
        context = self._make_context(order, source)
        context = context.model_copy(
            update={"norm_r1": norm_r1_signal(order, registry)}
        )
        payment_id = order.id
        payment_scene = scene or "api"
        payment: dict[str, Any] = {
            "paymentId": payment_id,
            "uetr": order.uetr,
            "scene": payment_scene,
            "order": order,
            "payeeRegistry": registry,
            "riskContext": context,
            "normChecks": norm_checks,
            "taxNotices": tax_notices,
            "approvals": [],
            "approvalRequiredBy": self._approval_requirements(order, context),
            "approvalBlock": self._approval_blocked(context),
            "approval": None,
            "legs": [],
            "status": "PENDING_APPROVAL",
            "journal": None,
            "source": source,
        }
        self.payments[payment_id] = payment
        self.active_payment_id = payment_id
        payment["journal"] = self._new_journal(
            payment_id, order.uetr, payment_scene
        )
        self.idempotency[key] = payment_id

        self._publish(
            payment_id,
            "norms.checked",
            {
                "decision": {
                    "normChecks": norm_checks,
                    "taxNotices": tax_notices,
                }
            },
            scene=payment_scene,
        )
        await self._pause(scene)

        fallback = evaluate_rules(order, context)
        if fallback["approvalBlocked"]:
            payment["approvalBlock"] = True
            if scene is not None:
                required_approval = self._approval_data(payment)
                self._publish(
                    payment_id,
                    "approval.required",
                    {
                        "decision": {
                            "approval": required_approval,
                            "blocked": "verification_required",
                        }
                    },
                    scene=payment_scene,
                )
                await self._pause(scene)

        risk_result, risk_degraded = score_with_status(order, context)
        if self.chain_error or self.chain is None:
            risk_tier_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
            if risk_tier_order.get(risk_result["tier"], 0) < risk_tier_order["MEDIUM"]:
                risk_result["tier"] = "MEDIUM"
        payment["risk"] = risk_result
        payment["riskDegraded"] = risk_degraded
        if risk_degraded:
            self._publish(
                payment_id,
                "mode.degraded",
                {
                    "dependency": "risk_model",
                    "status": "unavailable",
                    "policy": "rules_and_humans_only",
                    "releaseDisabled": True,
                },
                scene=payment_scene,
            )
            await self._pause(scene)
        self._publish(
            payment_id,
            "risk.scored",
            {"decision": {"risk": risk_result}},
            scene=payment_scene,
        )
        await self._pause(scene)

        route_result = select_route(
            order,
            risk_result,
            norm_checks,
            kill_switched=self.kill_switched,
        )
        payment["route"] = route_result
        self._publish(
            payment_id,
            "route.selected",
            {
                "decision": {
                    "route": {
                        key: route_result[key]
                        for key in (
                            "chosen",
                            "candidates",
                            "settlement",
                            "quoteValidUntil",
                        )
                    }
                },
                "reason": route_result["reason"],
                "priceOfSafety": route_result["priceOfSafety"],
            },
            scene=payment_scene,
        )
        await self._pause(scene)

        if not payment["approvalBlock"]:
            self._publish(
                payment_id,
                "approval.required",
                {"decision": {"approval": self._approval_data(payment)}},
                scene=payment_scene,
            )
            await self._pause(scene)

        if self.chain_error:
            self._publish(
                payment_id,
                "mode.degraded",
                {
                    "dependency": "rpc",
                    "status": "unavailable",
                    "policy": "rules_and_humans_only",
                    "releaseDisabled": True,
                },
                scene=payment_scene,
            )
            await self._pause(scene)

        return self.payment_response(payment_id)

    def _approval_data(self, payment: dict[str, Any]) -> dict[str, Any]:
        method = (
            "DUAL_CONTROL"
            if len(payment["approvalRequiredBy"]) > 1
            else "SCA"
        )
        return {
            "by": payment["approvalRequiredBy"],
            "method": method,
            "hash": payment.get("approvalHash", "approval-required"),
        }

    async def approve_payment(
        self,
        payment_id: str,
        approver: str,
        *,
        allow_conditional_hold: bool = False,
        combined_event: bool = False,
        scene: str | None = None,
    ) -> dict[str, Any]:
        payment = self._payment(payment_id)
        role = approver.lower()
        if role not in payment["approvalRequiredBy"]:
            raise ValueError("approver is not required for this payment")
        if role in payment["approvals"]:
            return self.payment_response(payment_id)
        if payment["approvalBlock"] and not (
            allow_conditional_hold
            and payment.get("route", {}).get("settlement")
            in {"ONCHAIN_ESCROW", "FIAT_HOLD"}
        ):
            raise PermissionError("verification is required before approval")

        approved_at = int(time.time())
        approval_nonce = self.nonce
        self.nonce += 1
        approval_method = (
            "DUAL_CONTROL"
            if len(payment["approvalRequiredBy"]) > 1
            else "SCA"
        )
        approval_message = {
            "paymentId": payment_id,
            "approverId": role,
            "method": approval_method,
            "approvedAt": approved_at,
            "nonce": approval_nonce,
        }
        signed = signer.sign(role, "Approval", approval_message)
        payment["approvals"].append(role)
        payment.setdefault("approvalSignatures", []).append(signed.signature)
        payment["approvalHash"] = _stable_hash(
            "".join(payment["approvalSignatures"])
        )
        payment["approval"] = {
            "by": list(payment["approvals"]),
            "method": approval_method,
            "hash": payment["approvalHash"],
        }
        should_publish = (
            not combined_event
            or payment["approvals"] == payment["approvalRequiredBy"]
        )
        if should_publish:
            self._publish(
                payment_id,
                "approval.granted",
                {"decision": {"approval": payment["approval"]}},
                scene=scene,
            )
            await self._pause(scene)
        if payment["approvals"] == payment["approvalRequiredBy"]:
            await self._commit_payment(payment, scene=scene)
        return self.payment_response(payment_id)

    def _build_intent(self, payment: dict[str, Any]) -> dict[str, Any]:
        order: PaymentOrder = payment["order"]
        token = os.getenv("TOKEN_ADDRESS", DEV_TOKEN if self.chain_mode == "fake" else FUJI_EURC)
        beneficiary = _address_for(order.creditor.accountId)
        amount = int(float(order.amount.value) * 1_000_000)
        decision_data = {
            "normChecks": payment["normChecks"],
            "risk": payment["risk"],
            "route": payment["route"],
        }
        intent = {
            "paymentId": payment["paymentId"],
            "corridorId": "FR-GH",
            "beneficiary": beneficiary,
            "token": to_checksum_address(token),
            "amount": amount,
            "offchainHash": _stable_hash(
                json.dumps(order.model_dump(), sort_keys=True)
            ),
            "decisionHash": _stable_hash(
                json.dumps(decision_data, sort_keys=True)
            ),
            "approvalHash": payment["approvalHash"],
            "tier": payment["risk"]["tier"],
            "validUntil": int(time.time()) + 600,
            "nonce": self.nonce,
        }
        self.nonce += 1
        return intent

    async def _commit_payment(
        self, payment: dict[str, Any], *, scene: str | None = None
    ) -> None:
        if payment.get("intent"):
            return
        if self.chain is None:
            payment["status"] = "DEGRADED_HOLD"
            return
        intent = self._build_intent(payment)
        try:
            signed = signer.sign("router", "PaymentIntent", intent)
            commit_result = self.chain.commit(intent, signed.signature)
        except Exception as error:
            payment["status"] = "DEGRADED_HOLD"
            self._publish(
                payment["paymentId"],
                "mode.degraded",
                {
                    "dependency": "chain",
                    "status": "unavailable",
                    "policy": "rules_and_humans_only",
                    "releaseDisabled": True,
                },
                scene=scene,
            )
            LOGGER.warning("Chain commit failed; payment remains held (%s).", type(error).__name__)
            return
        payment["intent"] = intent
        payment["intentHash"] = commit_result["intentHash"]
        payment["intentSignature"] = signed.signature
        payment["status"] = "COMMITTED"
        payment["intentSummary"] = {
            "hash": commit_result["intentHash"],
            "txHash": commit_result["txHash"],
        }
        commit_event = self._publish(
            payment["paymentId"],
            "intent.committed",
            {
                "txHash": commit_result["txHash"],
                "contract": "PaymentRegistry",
                "status": commit_result["status"],
                "intentHash": commit_result["intentHash"],
            },
            scene=scene,
            explorer_url=commit_result["explorerUrl"],
        )
        await self._pause(scene)

        if payment["route"]["settlement"] == "ONCHAIN_ESCROW":
            try:
                deposit = self.chain.escrowDeposit(
                    payment["paymentId"],
                    intent=intent,
                    intentHash=commit_result["intentHash"],
                    payer=DEFAULT_PAYER,
                    beneficiary=intent["beneficiary"],
                    amount=intent["amount"],
                    token=intent["token"],
                )
            except Exception as error:
                payment["status"] = "DEGRADED_HOLD"
                self._publish(
                    payment["paymentId"],
                    "mode.degraded",
                    {
                        "dependency": "chain",
                        "status": "unavailable",
                        "policy": "rules_and_humans_only",
                        "releaseDisabled": True,
                    },
                    scene=scene,
                )
                LOGGER.warning("Escrow deposit failed (%s).", type(error).__name__)
                return
            payment["status"] = "ESCROWED"
            self._publish(
                payment["paymentId"],
                "escrow.deposited",
                {
                    "txHash": deposit["txHash"],
                    "contract": "PaymentEscrow",
                    "status": deposit["status"],
                    "amount": f"{payment['order'].amount.value} EUR",
                    "expiresAt": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(int(time.time()) + 24 * 60 * 60),
                    ),
                },
                scene=scene,
                explorer_url=deposit["explorerUrl"],
            )
            await self._pause(scene)
        elif not payment["riskDegraded"] and not self.chain_error:
            await self._settle_payment(payment, scene=scene)

        del commit_event

    async def _settle_payment(
        self, payment: dict[str, Any], *, scene: str | None = None
    ) -> None:
        rail = payment["route"]["chosen"]
        adapter = self.adapters[rail]
        intent = payment["intent"]
        leg = {
            "paymentId": payment["paymentId"],
            "intentHash": payment["intentHash"],
            "nonce": intent["nonce"],
            "intent": intent,
            "rail": rail,
            "validUntil": intent["validUntil"],
        }
        idempotency_key = f"{payment['paymentId']}:{rail}:{intent['nonce']}"
        try:
            adapter.initiate(
                leg,
                intent,
                self.chain,
                expected_intent_hash=payment["intentHash"],
                tier=payment["risk"]["tier"],
                idempotency_key=idempotency_key,
            )
        except ChainRevert:
            payment["status"] = "REJECTED"
            return
        payment["legs"].append(
            {
                "uetr": payment["uetr"],
                "intentHash": payment["intentHash"],
                "nonce": intent["nonce"],
                "rail": rail,
                "rank": 1,
                "status": "pending",
                "idempotencyKey": idempotency_key,
            }
        )
        self._publish(
            payment["paymentId"],
            "leg.sent",
            {
                "leg": {"rail": rail, "rank": 1, "status": "pending"},
                "intentHash": payment["intentHash"],
            },
            scene=scene,
        )
        await self._pause(scene)
        settled = adapter.settle(leg)
        payment["legs"][0]["status"] = settled["status"]
        self._publish(
            payment["paymentId"],
            "leg.settled",
            {
                "leg": {"rail": rail, "rank": 1, "status": "settled"},
                "amount": f"{payment['order'].amount.value} EUR",
                "simulated": True,
            },
            scene=scene,
        )
        await self._pause(scene)
        self.chain.markExecuted(
            payment["paymentId"], payment["uetr"]
        )
        payment["status"] = "SETTLED"

    async def play_scene(self, scene: str) -> dict[str, Any]:
        selected = scene.lower()
        if selected not in {"1", "2", "2b"}:
            raise ValueError("scene must be 1, 2 or 2b")
        self.reset(clear_events=True)
        if selected == "2b":
            await self._play_attack_sequence()
            return {"scene": "2b", "events": self.bus.snapshot()}

        fixture = _read_fixture(selected)
        payment = await self.submit_order(
            fixture,
            idempotency_key=fixture["order"]["id"],
            scene=selected,
        )
        payment_id = fixture["order"]["id"]
        approvers = payment["approvalsRequired"]
        for approver in approvers:
            await self.approve_payment(
                payment_id,
                approver,
                allow_conditional_hold=(selected == "2"),
                combined_event=(selected == "2"),
                scene=selected,
            )

        if selected == "2":
            await self._run_scene_two_after_deposit(payment_id, fixture)
        return {"scene": selected, "payment": self.payment_response(payment_id), "events": self.bus.snapshot()}

    async def _run_scene_two_after_deposit(
        self, payment_id: str, fixture: dict[str, Any]
    ) -> None:
        payment = self._payment(payment_id)
        contact = next(
            (
                item
                for item in payment["payeeRegistry"].get("knownContacts", [])
                if item.get("since")
            ),
            None,
        )
        if contact is None:
            raise ValueError("no registered supplier contact is available")
        simswap = fixture.get("telecom", {}).get("simSwap", {})
        self._publish(
            payment_id,
            "simswap.checked",
            {
                "msisdn": contact["msisdn"],
                "lookbackDays": 7,
                "swapped": bool(simswap.get("swapped", False)),
                "simulated": True,
            },
            scene="2",
        )
        await self._pause("2")
        self._publish(
            payment_id,
            "oob.requested",
            {
                "contact": "Kwame",
                "msisdn": contact["msisdn"],
                "channel": "simulated_phone",
                "prompt": "Have you changed your account?",
            },
            scene="2",
        )
        await self._pause("2")
        intent_hash_value = payment["intentHash"]
        verification = {
            "paymentId": payment_id,
            "intentHash": intent_hash_value,
            "method": "OOB_KNOWN_CONTACT",
            "result": "DENIED",
            "simSwapChecked": True,
            "evidenceHash": _stable_hash("known-contact-denied"),
            "verifiedAt": int(time.time()),
            "nonce": self.nonce,
        }
        self.nonce += 1
        verification_signature = signer.sign(
            "verifier", "VerificationAttestation", verification
        )
        chain_result = self.chain.deny(
            payment_id,
            verification | {"signature": verification_signature.signature},
        )
        self._publish(
            payment_id,
            "verification.recorded",
            {
                "txHash": chain_result["txHash"],
                "contract": "PaymentRegistry",
                "status": "VERIFICATION_DENIED",
                "result": "DENIED",
                "by": "Kwame",
                "method": "OOB_KNOWN_CONTACT",
                "simulated": True,
            },
            scene="2",
            explorer_url=chain_result["explorerUrl"],
        )
        await self._pause("2")
        self._publish(
            payment_id,
            "alert.raised",
            {
                "alertId": "alert_scene2",
                "tier": payment["risk"]["tier"],
                "uetr": payment["uetr"],
                "recipient": "Ama's bank",
                "freezeRequested": True,
            },
            scene="2",
        )
        await self._pause("2")
        fired_refs = {
            reason["ref"] for reason in payment["risk"].get("topReasons", [])
        }
        events = [
            event
            for event in self.bus.snapshot()
            if event["paymentId"] == payment_id
        ]
        case = await investigate(events, fired_refs)
        case_id = "case_scene2"
        case_payload = {
            "caseId": case_id,
            "tier": payment["risk"]["tier"],
            **case,
        }
        self.cases[case_id] = case_payload
        payment["caseId"] = case_id
        self._publish(payment_id, "case.ready", case_payload, scene="2")
        await self._pause("2")

        revocation = {
            "paymentId": payment_id,
            "reasonCode": 1,
            "caseHash": _stable_hash(case_id),
            "nonce": self.nonce,
        }
        self.nonce += 1
        revoke_result = self.chain.revoke(payment_id, revocation)
        self._publish(
            payment_id,
            "intent.revoked",
            {
                "txHash": revoke_result["txHash"],
                "contract": "PaymentRegistry",
                "status": "REVOKED",
                "reason": "Supplier denied account change",
            },
            scene="2",
            explorer_url=revoke_result["explorerUrl"],
        )
        await self._pause("2")
        refund = self.chain.escrowRefund(payment_id, caller="analyst")
        self._publish(
            payment_id,
            "escrow.refunded",
            {
                "txHash": refund["txHash"],
                "contract": "PaymentEscrow",
                "status": "REFUNDED",
                "reason": "Verification denied",
            },
            scene="2",
            explorer_url=refund["explorerUrl"],
        )
        payment["status"] = "REFUNDED"
        await self._pause("2")
        payment["journal"].verify()

    async def _play_attack_sequence(self) -> None:
        for attack in ("A", "B", "C"):
            self._prepare_attack_context()
            await self.simulate_attack(attack, scene="2b")

    def _prepare_attack_context(self) -> dict[str, Any]:
        fixture = _read_fixture("2")
        order = PaymentOrder.model_validate(fixture["order"])
        payment_id = order.id
        if payment_id not in self.payments:
            self.payments[payment_id] = {
                "paymentId": payment_id,
                "uetr": order.uetr,
                "scene": "2b",
                "order": order,
                "payeeRegistry": fixture["payeeRegistry"],
                "risk": fixture["expectedRisk"],
                "normChecks": [],
                "taxNotices": [],
                "status": "REVOKED",
                "legs": [],
            }
            self._new_journal(payment_id, order.uetr, "2b")
        self.active_payment_id = payment_id
        return fixture

    def _attack_intent(
        self, fixture: dict[str, Any], payment_id: str, nonce: int
    ) -> dict[str, Any]:
        order = PaymentOrder.model_validate(fixture["order"])
        return {
            "paymentId": payment_id,
            "corridorId": "FR-GH",
            "beneficiary": _address_for(order.creditor.accountId),
            "token": DEV_TOKEN,
            "amount": int(float(order.amount.value) * 1_000_000),
            "offchainHash": _stable_hash(f"attack:{payment_id}"),
            "decisionHash": _stable_hash("scene2-decision"),
            "approvalHash": _stable_hash("scene2-approval"),
            "tier": "MEDIUM",
            "validUntil": int(time.time()) + 600,
            "nonce": nonce,
        }

    async def simulate_attack(
        self, attack: str, *, scene: str = "2b"
    ) -> dict[str, Any]:
        selected = attack.upper()
        if selected not in {"A", "B", "C"}:
            raise ValueError("attack must be A, B or C")
        fixture = self._prepare_attack_context()
        payment = self._payment("pay_scene2")
        payment_id = payment["paymentId"]
        self.active_payment_id = payment_id
        chain = self.chain
        if not isinstance(chain, FakeChain):
            raise RuntimeError("attack simulation requires CHAIN_MODE=fake")

        if selected == "A":
            payment_a = "attack_a"
            intent = self._attack_intent(fixture, payment_a, 901)
            chain.commit(intent)
            chain.escrowDeposit(payment_a, intent=intent)
            chain.revoke(payment_a)
            try:
                chain.escrowRelease(payment_a)
            except ChainRevert as error:
                tx = chain._tx("REVERTED")
                self._publish(
                    payment_id,
                    "tx.reverted",
                    {
                        "txHash": tx["txHash"],
                        "contract": "PaymentEscrow",
                        "status": "REVERTED",
                        "attack": "A",
                        "function": "release",
                        "revertReason": error.reason,
                    },
                    scene=scene,
                )
                await self._pause(scene)
                return {"attack": selected, "failedClosed": True, "reason": error.reason}

        if selected == "B":
            payment_b = "attack_b"
            intent = self._attack_intent(fixture, payment_b, 902)
            committed = chain.commit(intent)
            swapped = dict(intent)
            swapped["beneficiary"] = _address_for("substituted-beneficiary")
            received_hash = signer.intent_hash(swapped)
            adapter = self.adapters["R3"]
            leg = {
                "intentHash": received_hash,
                "nonce": intent["nonce"],
            }
            try:
                adapter.initiate(
                    leg,
                    swapped,
                    chain,
                    expected_intent_hash=committed["intentHash"],
                    tier="MEDIUM",
                    idempotency_key="attack-b-adapter",
                    attack="B",
                )
            except ChainRevert:
                pass
            await self._pause(scene)
            try:
                chain.escrowDeposit(payment_b, intent=swapped)
            except ChainRevert as error:
                tx = chain._tx("REVERTED")
                self._publish(
                    payment_id,
                    "tx.reverted",
                    {
                        "txHash": tx["txHash"],
                        "contract": "PaymentEscrow",
                        "status": "REVERTED",
                        "attack": "B",
                        "function": "deposit",
                        "revertReason": error.reason,
                    },
                    scene=scene,
                )
                await self._pause(scene)
                adapter.record_failure("CommitmentMismatch")
                await self._pause(scene)
                return {"attack": selected, "failedClosed": True, "reason": error.reason}

        if selected == "C":
            payment_c = "attack_c"
            intent = self._attack_intent(fixture, payment_c, 903)
            chain.commit(intent)
            replay = dict(intent)
            replay["paymentId"] = "attack_c_replay"
            try:
                chain.commit(replay)
            except ChainRevert as error:
                self.adapters["R3"].integrity_failure(
                    "nonce already consumed",
                    attack="C",
                    nonce=intent["nonce"],
                )
                await self._pause(scene)
                journal = self.journals[payment_id]
                entry = journal.append(
                    "decision",
                    {"tier": "MEDIUM", "reason": "new beneficiary"},
                )
                entry["payload"]["tier"] = "LOW"
                journal.verify()
                await self._pause(scene)
                return {"attack": selected, "failedClosed": True, "reason": error.reason}

        raise RuntimeError(f"attack {selected} unexpectedly succeeded")

    def payment_response(self, payment_id: str) -> dict[str, Any]:
        payment = self._payment(payment_id)
        response = {
            "paymentId": payment_id,
            "uetr": payment["uetr"],
            "status": payment.get("status", "PENDING_APPROVAL"),
            "decision": self._decision_payload(payment),
            "approvalsRequired": payment.get("approvalRequiredBy", []),
            "approvalsGranted": payment.get("approvals", []),
            "routeReason": payment.get("route", {}).get("reason"),
            "priceOfSafety": payment.get("route", {}).get("priceOfSafety"),
            "legs": payment.get("legs", []),
        }
        if payment.get("intent"):
            response["intent"] = payment["intent"]
        if payment.get("caseId"):
            response["caseId"] = payment["caseId"]
        return response

    def _payment(self, payment_id: str) -> dict[str, Any]:
        if payment_id in self.payments:
            return self.payments[payment_id]
        for payment in self.payments.values():
            if payment.get("uetr") == payment_id:
                return payment
        raise KeyError(f"payment not found: {payment_id}")

    def payment_proof(self, payment_id: str) -> dict[str, Any]:
        payment = self._payment(payment_id)
        intent = payment.get("intent")
        return {
            "paymentId": payment["paymentId"],
            "typedData": (
                signer.build_typed_data("PaymentIntent", intent)
                if intent
                else None
            ),
            "intentHash": payment.get("intentHash"),
            "intentSignature": payment.get("intentSignature"),
            "approvalSignatures": payment.get("approvalSignatures", []),
            "events": [
                event
                for event in self.bus.snapshot()
                if event["paymentId"] == payment["paymentId"]
            ],
            "journal": (
                payment["journal"].entries if payment.get("journal") else []
            ),
        }

    def verify_payee(
        self,
        payee_id: str,
        payment_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        registry = self.payees.get(payee_id)
        if registry is None:
            raise KeyError(f"payee not found: {payee_id}")
        contact = next(
            (
                item
                for item in registry.get("knownContacts", [])
                if item.get("since")
            ),
            None,
        )
        if contact is None:
            raise ValueError("no eligible known contact is registered")
        supplied_number = payload.get("msisdn")
        if supplied_number and supplied_number != contact["msisdn"]:
            raise PermissionError("verification may only use a registered contact")
        if not payment_id:
            return {
                "status": "requested",
                "contact": contact["msisdn"],
                "channel": "simulated_phone",
            }
        payment = self._payment(payment_id)
        result = payload.get("result")
        if result not in {"CONFIRMED", "DENIED"}:
            return {"status": "requested", "contact": contact["msisdn"]}
        verification = {
            "paymentId": payment["paymentId"],
            "intentHash": payment.get("intentHash", _stable_hash(payment["paymentId"])),
            "method": "OOB_KNOWN_CONTACT",
            "result": result,
            "simSwapChecked": True,
            "evidenceHash": _stable_hash("payee-verification"),
            "verifiedAt": int(time.time()),
            "nonce": self.nonce,
        }
        self.nonce += 1
        if result == "CONFIRMED":
            chain_result = self.chain.confirm(payment["paymentId"], verification)
        else:
            chain_result = self.chain.deny(payment["paymentId"], verification)
        payment["verified"] = result == "CONFIRMED"
        return {
            "status": result,
            "by": payload.get("by", "registered-contact"),
            **chain_result,
        }

    def list_cases(self) -> list[dict[str, Any]]:
        return list(self.cases.values())

    async def create_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        payment_id = payload.get("paymentId")
        payment = self._payment(payment_id) if payment_id else None
        case_id = payload.get("caseId") or f"case_{len(self.cases) + 1}"
        refs = (
            {
                reason["ref"]
                for reason in payment["risk"].get("topReasons", [])
            }
            if payment
            else set()
        )
        case = await investigate(
            payload.get("events", []),
            refs,
        )
        record = {
            "caseId": case_id,
            "paymentId": payment_id,
            "tier": payment["risk"]["tier"] if payment else "MEDIUM",
            **case,
        }
        self.cases[case_id] = record
        return record

    async def case_action(
        self, case_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        case = self.cases.get(case_id)
        if case is None:
            raise KeyError(f"case not found: {case_id}")
        action = str(payload.get("action", "")).upper()
        payment = self._payment(case["paymentId"]) if case.get("paymentId") else None
        if action == "REVOKE" and payment:
            result = self.chain.revoke(
                payment["paymentId"],
                {
                    "paymentId": payment["paymentId"],
                    "reasonCode": 1,
                    "caseHash": _stable_hash(case_id),
                    "nonce": self.nonce,
                },
            )
            self.nonce += 1
            return {"action": action, **result}
        if action == "REFUND" and payment:
            return {
                "action": action,
                **self.chain.escrowRefund(payment["paymentId"], caller="analyst"),
            }
        if action == "CONFIRM" and payment:
            return {
                "action": action,
                **self.chain.confirm(payment["paymentId"]),
            }
        if action in {"FREEZE", "ESCALATE", "REPORT"}:
            case["lastAction"] = action
            return {"action": action, "status": "recorded"}
        raise ValueError(f"unsupported case action: {action}")


orchestrator = Orchestrator()
