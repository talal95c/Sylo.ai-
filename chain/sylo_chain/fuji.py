"""FujiChain: ChainPort over the deployed PaymentRegistry and PaymentEscrow on Avalanche Fuji.

Lane C builds it in v1. It must pass ``sylo_spec.conformance.run_chain_conformance``.
"""

from __future__ import annotations


class FujiChain:
    mode = "fuji"

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("Lane C implements FujiChain in v1 (docs/roadmap-and-lanes.md, C1.3)")

    @classmethod
    def from_env(cls) -> "FujiChain":
        return cls()
