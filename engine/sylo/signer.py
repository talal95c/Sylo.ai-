"""Role keys and EIP-712 signing (v0 spec §5.8).

Keys come from the environment; when unset (mock and local mode only) the public Anvil dev keys of
``sylo_spec.devkeys`` are used.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from eth_account import Account

from sylo_spec import eip712
from sylo_spec.devkeys import dev_key
from sylo_spec.eip712 import Message
from sylo_spec.models import Eip712Domain

ROLE_ENV = {
    "router_signer": "ROUTER_SIGNER_PK",
    "verifier_signer": "VERIFIER_SIGNER_PK",
    "analyst_signer": "ANALYST_SIGNER_PK",
}


class Signer:
    def __init__(self, env: Mapping[str, str] | None = None, *, allow_dev_keys: bool = True) -> None:
        env = os.environ if env is None else env
        self._keys: dict[str, str] = {}
        self.uses_dev_keys = False
        for role, variable in ROLE_ENV.items():
            key = (env.get(variable) or "").strip()
            if not key:
                if not allow_dev_keys:
                    raise RuntimeError(f"{variable} is not set")
                key = dev_key(role)
                self.uses_dev_keys = True
            self._keys[role] = key
        self._addresses = {role: Account.from_key(key).address for role, key in self._keys.items()}
        self._nonces = dict.fromkeys(ROLE_ENV, 0)

    def address(self, role: str) -> str:
        return self._addresses[role]

    def next_nonce(self, role: str) -> int:
        self._nonces[role] += 1
        return self._nonces[role]

    def start_nonces_at(self, base: int) -> None:
        """Number this session's signed messages from ``base``.

        The registry remembers every nonce of a signer for ever. On a chain that outlives the engine a
        new session must therefore not start again at 1: its first commit, verification or revocation
        would revert ``NonceUsed``. Nonces only have to be unique per signer, not consecutive."""
        self._nonces = dict.fromkeys(ROLE_ENV, base)

    def sign(self, role: str, message: Message, domain: Eip712Domain) -> bytes:
        return eip712.sign(message, domain, self._keys[role])
