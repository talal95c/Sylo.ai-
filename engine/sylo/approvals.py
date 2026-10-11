"""Payer approval and dual control (roadmap A1.3, PRD §12.3).

Dual control applies from EUR 20,000, or from EUR 5,000 when the beneficiary account is new. The
author of the payment approves first; the second approval must come from someone else. The
approval hash covers every approval record and goes into the signed intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sylo_spec.canonical import hash_record
from sylo_spec.models import Approver, Payer

from . import texts
from .pacer import iso_ms


class ApprovalError(Exception):
    """An approval that cannot be accepted. ``code`` is stable; ``str(error)`` is the sentence shown."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ApprovalRecord:
    approver: Approver
    at: str

    def to_event(self) -> dict[str, Any]:
        return {
            "id": self.approver.id,
            "name": self.approver.name,
            "role": texts.APPROVER_ROLES.get(self.approver.id, self.approver.role),
            "at": self.at,
        }


def required_approvers(
    payer: Payer, amount_eur: float, *, known_account: bool, dual_control_eur: float, new_payee_eur: float
) -> tuple[list[Approver], str]:
    """Who must approve, author first, and the method name (``SCA`` or ``DUAL_CONTROL``)."""
    author, *others = payer.approvers
    dual = amount_eur >= dual_control_eur or (not known_account and amount_eur >= new_payee_eur)
    if dual and others:
        return [author, others[0]], "DUAL_CONTROL"
    return [author], "SCA"


@dataclass
class ApprovalSession:
    required: list[Approver]
    method: str
    conditional: bool
    records: list[ApprovalRecord] = field(default_factory=list)

    @property
    def author(self) -> Approver:
        return self.required[0]

    @property
    def pending(self) -> list[Approver]:
        done = {record.approver.id for record in self.records}
        return [approver for approver in self.required if approver.id not in done]

    @property
    def complete(self) -> bool:
        return not self.pending

    def approve(self, approver_id: str, at: datetime) -> ApprovalRecord:
        approver = next((a for a in self.required if a.id == approver_id), None)
        if approver is None:
            raise ApprovalError("NOT_AN_APPROVER", f"{approver_id!r} is not an approver of this payment")
        if any(record.approver.id == approver_id for record in self.records):
            if approver_id == self.author.id and not self.complete:
                raise ApprovalError("AUTHOR_CANNOT_CO_APPROVE", texts.APPROVAL_AUTHOR_TWICE)
            raise ApprovalError("ALREADY_APPROVED", f"{approver.name} has already approved this payment")
        if not self.records and approver_id != self.author.id:
            raise ApprovalError("AUTHOR_FIRST", texts.APPROVAL_AUTHOR_FIRST.format(author=self.author.name))
        record = ApprovalRecord(approver=approver, at=iso_ms(at))
        self.records.append(record)
        return record

    def required_event(self, note: str) -> dict[str, Any]:
        return {
            "required": [
                {"id": a.id, "name": a.name, "role": texts.APPROVER_ROLES.get(a.id, a.role)} for a in self.required
            ],
            "received": [record.to_event() for record in self.records],
            "pending": [a.id for a in self.pending],
            "method": self.method,
            "conditional": self.conditional,
            "note": note,
        }

    def approval_hash(self, *, payment_id: str, route_id: str, amount: str) -> str:
        return hash_record(
            {
                "paymentId": payment_id,
                "routeId": route_id,
                "amount": amount,
                "method": self.method,
                "conditional": self.conditional,
                "approvals": [{"approver": r.approver.id, "role": r.approver.role, "at": r.at} for r in self.records],
            }
        )
