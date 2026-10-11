"""Scene 4 (roadmap C2.1): a stolen verifier key confirms a held payment, then the thief tries to release it.

    uv run python -m sylo_chain.stolen_verifier_key PAY-2026-0002 [--wait 8]

Run it while the engine waits for the supplier on a MEDIUM payment and the guardian is watching. The
forged confirmation is signed with the verifier key (a simulated theft) and sent from the attacker's
account. The guardian should freeze the hold first; the release is then mined as a failed transaction.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests
from sylo_spec.canonical import hash_record, to_hex
from sylo_spec.eip712 import sign
from sylo_spec.models import Status, TxRef, VerificationAttestation, VerificationMethod, VerificationResult
from sylo_spec.ports import ChainReverted

from .envfile import load_env_file
from .fuji import FujiChain


def forge_confirmation(chain: FujiChain, chain_pid: str, verifier_key: str) -> TxRef:
    attestation = VerificationAttestation(
        payment_id=chain_pid,
        intent_hash=to_hex(chain.intent_hash(chain_pid)),
        method=int(VerificationMethod.OOB_KNOWN_CONTACT),
        result=int(VerificationResult.CONFIRMED),
        sim_swap_checked=True,
        evidence_hash=hash_record({"paymentId": chain_pid, "forged": True, "at": time.time()}),
        verified_at=int(time.time()),
        nonce=int.from_bytes(os.urandom(7), "big"),
    )
    return chain.record_verification(attestation, sign(attestation, chain.domain(), verifier_key), caller="attacker")


def try_release(chain: FujiChain, chain_pid: str) -> tuple[bool, str, TxRef | None]:
    """(released, reason, tx). The attacker's call is mined even when it reverts."""
    try:
        return True, "released", chain.release(chain_pid, caller="attacker")
    except ChainReverted as err:
        return False, err.reason, err.tx


def _chain_pid(engine_url: str, payment_id: str) -> str:
    response = requests.get(f"{engine_url.rstrip('/')}/v1/payments/{payment_id}/proof", timeout=5)
    response.raise_for_status()
    return str(response.json()["chainPaymentId"])


def _link(ref: TxRef | None) -> str:
    return (ref.explorer_url or ref.tx_hash) if ref else "-"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sylo_chain.stolen_verifier_key", description=__doc__.split("\n\n")[0])
    parser.add_argument("payment_id", help="the engine's payment id, e.g. PAY-2026-0002")
    parser.add_argument("--wait", type=float, default=8.0, help="seconds between the forged confirmation and the release")
    parser.add_argument("--engine-url", help="default: ENGINE_URL or http://localhost:$ENGINE_PORT")
    parser.add_argument("--chain-pid", help="bytes32 payment id, if the engine is not running")
    args = parser.parse_args(argv)

    load_env_file()
    verifier_key = os.environ.get("VERIFIER_SIGNER_PK")
    if not verifier_key:
        parser.error("VERIFIER_SIGNER_PK is not set")
    chain = FujiChain.from_env()
    if not chain.address("attacker"):
        parser.error("ATTACKER_PK is not set")
    engine_url = args.engine_url or os.environ.get("ENGINE_URL") or f"http://localhost:{os.environ.get('ENGINE_PORT') or 8000}"
    chain_pid = args.chain_pid or _chain_pid(engine_url, args.payment_id)

    status, hold = chain.status(chain_pid), chain.hold(chain_pid)
    if status != Status.COMMITTED or hold["expiresAt"] == 0:
        print(f"{args.payment_id} is {status.name} with {'no' if not hold['expiresAt'] else 'a'} hold: "
              "start a MEDIUM payment that waits for the supplier first", file=sys.stderr)
        return 2

    print(f"[simulated theft] verifier key used from the attacker's account {chain.address('attacker')}")
    forged = forge_confirmation(chain, chain_pid, verifier_key)
    print(f"1. forged CONFIRMED recorded: {_link(forged)}")
    print(f"2. waiting {args.wait:g} s (the guardian polls every 2 s)")
    time.sleep(args.wait)
    released, reason, tx = try_release(chain, chain_pid)
    if released:
        print(f"3. release WENT THROUGH: {_link(tx)} (the guardian lost the race)")
        return 1
    print(f"3. release refused on chain ({reason}): {_link(tx)}")
    hold = chain.hold(chain_pid)
    print(f"   hold frozen: {hold['frozen']}, corridor paused: {chain.corridor_paused(hold['corridorId'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
