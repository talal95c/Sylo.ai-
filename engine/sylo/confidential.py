"""Confidential chain leg with eERC (PRD §13.6, roadmap A3.3).

A payment that needs no hold can cross the chain as an eERC confidential transfer: the amount is not
readable on-chain, the recipient decrypts it, and a designated auditor can decrypt every amount. A
payment that must be held keeps the public escrow, because a contract cannot hold and release eEURC.

``CONFIDENTIAL_MODE=eerc`` calls Lane C's service (``chain/eerc``, ``POST /transfer``), which sends a real
confidential transfer on Fuji from the sending institution's pre-funded eEURC float; the receiver unwraps
netted totals later (``POST /settle``, not the engine's business). ``simulated`` returns a labelled fake
receipt, for a laptop without that service.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from sylo_spec.canonical import keccak_text, to_hex

log = logging.getLogger("sylo.confidential")

TOKEN = "eEURC"
VISIBLE = ("sender and receiver addresses", "the float wrapped at one end and the netted totals unwrapped at the other")
HIDDEN = ("transfer amount", "eEURC balances", "payment reference (encrypted metadata)")


class ConfidentialUnavailable(Exception):
    """The confidential leg could not be made. ``str(error)`` says why, without any secret."""


@dataclass(frozen=True)
class ConfidentialReceipt:
    tx_hash: str
    explorer_url: str | None
    auditor_amount_eur: float | None
    metadata_payment_id: str | None
    simulated: bool
    deposit_tx_hash: str | None = None
    withdraw_tx_hash: str | None = None


class ConfidentialLeg(Protocol):
    mode: str

    def transfer(self, payment_id: str, amount_eur: float) -> ConfidentialReceipt: ...


class SimulatedConfidentialLeg:
    """No chain: a deterministic, labelled receipt. The 'auditor' reads back the amount that was sent."""

    mode = "simulated"

    def transfer(self, payment_id: str, amount_eur: float) -> ConfidentialReceipt:
        return ConfidentialReceipt(
            tx_hash=to_hex(keccak_text(f"eerc-simulated:{payment_id}")),
            explorer_url=None,
            auditor_amount_eur=float(amount_eur),
            metadata_payment_id=payment_id,
            simulated=True,
        )


class EercServiceLeg:
    """Client of Lane C's eERC service. One leg takes about 10 s on Fuji (one proof and one transaction)."""

    mode = "eerc"

    def __init__(self, base_url: str, explorer_base_url: str, timeout: float = 120.0) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ConfidentialUnavailable("EERC_URL must be an http(s) URL")
        self._base_url = base_url.rstrip("/")
        self._explorer = explorer_base_url.rstrip("/")
        self._timeout = timeout

    def transfer(self, payment_id: str, amount_eur: float) -> ConfidentialReceipt:
        request = urllib.request.Request(
            f"{self._base_url}/transfer",
            data=json.dumps({"paymentId": payment_id, "amountEur": amount_eur}).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as err:
            raise ConfidentialUnavailable(f"the eERC service answered HTTP {err.code}") from None
        except (OSError, ValueError) as err:
            raise ConfidentialUnavailable(f"the eERC service did not answer ({type(err).__name__})") from None
        return self._receipt(body)

    def _receipt(self, body: Any) -> ConfidentialReceipt:
        txs = body.get("txs") if isinstance(body, dict) else None
        tx_hash = txs.get("transfer") if isinstance(txs, dict) else None
        if not isinstance(tx_hash, str) or not tx_hash.startswith("0x") or len(tx_hash) != 66:
            raise ConfidentialUnavailable("the eERC service returned no confidential transfer hash")
        auditor = body.get("auditor") if isinstance(body.get("auditor"), dict) else {}
        amount = auditor.get("decryptedAmountEur", body.get("auditorDecryptedAmountEur"))
        metadata = body.get("receiverMetadata") if isinstance(body.get("receiverMetadata"), dict) else {}
        links = body.get("links") if isinstance(body.get("links"), dict) else {}
        link = links.get("transfer")
        return ConfidentialReceipt(
            tx_hash=tx_hash,
            explorer_url=link if isinstance(link, str) and link.startswith("https://") else f"{self._explorer}/tx/{tx_hash}",
            auditor_amount_eur=float(amount) if isinstance(amount, (int, float)) else None,
            metadata_payment_id=metadata.get("paymentId") if isinstance(metadata.get("paymentId"), str) else None,
            simulated=False,
            deposit_tx_hash=txs.get("deposit") if isinstance(txs.get("deposit"), str) else None,
            withdraw_tx_hash=txs.get("withdraw") if isinstance(txs.get("withdraw"), str) else None,
        )


def load_confidential_leg(mode: str, eerc_url: str, explorer_base_url: str) -> tuple[ConfidentialLeg | None, bool]:
    """The confidential leg for ``CONFIDENTIAL_MODE``. Returns (leg or None, degraded)."""
    if mode == "off":
        return None, False
    if mode == "simulated":
        return SimulatedConfidentialLeg(), False
    if mode == "eerc":
        try:
            return EercServiceLeg(eerc_url, explorer_base_url), False
        except ConfidentialUnavailable as err:
            log.warning("CONFIDENTIAL_MODE=eerc but %s; chain legs stay public", err)
            return None, True
    log.warning("unknown CONFIDENTIAL_MODE %r; chain legs stay public", mode)
    return None, True
