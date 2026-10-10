"""Public Anvil development keys (mnemonic "test test test test test test test test test test test junk").

THESE KEYS ARE PUBLIC. Use them only in mock and local (Anvil) mode. Never fund them on Fuji.
"""

from __future__ import annotations

from functools import lru_cache

from eth_account import Account
from eth_account.signers.local import LocalAccount

MNEMONIC = "test test test test test test test test test test test junk"

ROLES: tuple[str, ...] = (
    "deployer",  # 0
    "relayer",  # 1
    "router_signer",  # 2
    "verifier_signer",  # 3
    "analyst_signer",  # 4
    "guardian",  # 5
    "eu_casp",  # 6  payer treasury on-chain
    "gh_vasp",  # 7  beneficiary on-chain
    "attacker",  # 8
)

Account.enable_unaudited_hdwallet_features()


@lru_cache(maxsize=None)
def dev_account(role: str) -> LocalAccount:
    if role not in ROLES:
        raise KeyError(f"unknown role {role!r}; expected one of {ROLES}")
    return Account.from_mnemonic(MNEMONIC, account_path=f"m/44'/60'/0'/0/{ROLES.index(role)}")


def dev_key(role: str) -> str:
    return "0x" + bytes(dev_account(role).key).hex()


def dev_address(role: str) -> str:
    return dev_account(role).address
