"""Runs the shared chain conformance suite against FujiChain (skipped until Lane C implements it)."""

import pytest

from sylo_spec.conformance import run_chain_conformance


def test_fuji_chain_passes_the_conformance_suite():
    from sylo_chain import FujiChain

    try:
        FujiChain()
    except NotImplementedError as err:
        pytest.skip(str(err))
    # Lane C: point this at a fresh Anvil deployment (fast, in CI); run against Fuji by hand.
    run_chain_conformance(lambda: FujiChain())


def test_the_conformance_suite_is_importable():
    from sylo_spec.conformance.chain import STEPS

    assert len(STEPS) == 7
