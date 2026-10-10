"""Shared fixtures: a deterministic engine core on a virtual clock."""

import pytest

from sylo.config import Settings
from sylo.main import build_core
from sylo.pacer import VirtualPacer
from sylo_spec.scenarios import DEMO_NOW


@pytest.fixture
def core():
    return build_core(Settings(seed=42, demo_speed=1.0), VirtualPacer(DEMO_NOW, 1.0))
