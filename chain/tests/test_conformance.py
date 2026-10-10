import os

import pytest

from sylo_spec.conformance import run_chain_conformance


def _chain_or_skip():
    from sylo_chain import FujiChain

    try:
        return FujiChain.from_env()
    except NotImplementedError as err:
        pytest.skip(str(err))


def test_fuji_chain_passes_the_chain_conformance_suite():
    _chain_or_skip()
    if not os.environ.get("SYLO_RUN_FUJI_TESTS"):
        pytest.skip("set SYLO_RUN_FUJI_TESTS=1 to run against Fuji (needs funded role wallets)")
    from sylo_chain import FujiChain

    run_chain_conformance(
        FujiChain.from_env,
        token=os.environ["TOKEN_ADDRESS"],
        payer=os.environ["EU_CASP_ADDRESS"],
    )
