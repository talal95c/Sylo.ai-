"""Public Anvil development keys.

These are the well-known accounts of the mnemonic below (the default of Anvil and Hardhat).
THEY ARE PUBLIC: use them only with the mock chain and a local Anvil node.
Never fund them on Fuji or any real network: anyone can sweep them.
"""

from dataclasses import dataclass
from functools import lru_cache

from eth_account import Account

MNEMONIC = "test test test test test test test test test test test junk"

# index -> role (build spec, section 4.7)
ROLES = (
    "deployer",
    "relayer",
    "router_signer",
    "verifier_signer",
    "analyst_signer",
    "guardian",
    "eu_casp",
    "gh_vasp",
    "attacker",
)


@dataclass(frozen=True)
class DevKey:
    role: str
    index: int
    address: str
    private_key: str


@lru_cache(maxsize=1)
def dev_keys() -> dict[str, DevKey]:
    Account.enable_unaudited_hdwallet_features()
    keys: dict[str, DevKey] = {}
    for index, role in enumerate(ROLES):
        account = Account.from_mnemonic(MNEMONIC, account_path=f"m/44'/60'/0'/0/{index}")
        keys[role] = DevKey(role=role, index=index, address=account.address, private_key=account.key.hex())
    return keys


def dev_key(role: str) -> DevKey:
    return dev_keys()[role]


def dev_address(role: str) -> str:
    return dev_keys()[role].address
