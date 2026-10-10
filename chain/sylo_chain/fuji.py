"""`FujiChain`: the Avalanche Fuji implementation of `sylo_spec.ports.ChainPort` (Lane C, v1)."""


class FujiChain:
    """Sends real transactions to the PaymentRegistry and PaymentEscrow contracts on Fuji.

    Contract (see `sylo_spec.ports.ChainPort` and `sylo_spec.conformance.run_chain_conformance`):
    - `mode = "fuji"` (or "anvil" against a local node); refuse to start unless the chain id is 43113.
    - `commit`, `deposit`, `record_verification`, `revoke`, `release`, `refund`, `mark_executed` return a
      `TxRef` with the explorer URL; custom errors are decoded to their names and raised as `ChainReverted(reason)`.
    - `status` and `intent_hash` read the registry.
    """

    mode = "fuji"

    def __init__(self) -> None:
        raise NotImplementedError("Lane C implements FujiChain in v1 (docs/roadmap-and-lanes.md, C1.3)")
