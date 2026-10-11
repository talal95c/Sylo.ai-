from __future__ import annotations

import json
from pathlib import Path

from eth_utils import to_checksum_address
from sylo_spec.devkeys import dev_key

from sylo_chain import FujiChain, fuji

REGISTRY = "0x0000000000000000000000000000000000000001"
ESCROW = "0x0000000000000000000000000000000000000002"
TOKEN = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"


def _offline_chain(monkeypatch) -> None:
    monkeypatch.setattr(FujiChain, "_connect", lambda self, urls, timeout: [])
    monkeypatch.setattr(FujiChain, "_read_domain", lambda self: None)


def _env(**overrides: str) -> dict[str, str]:
    return {
        "FUJI_RPC_URL": "http://127.0.0.1:9650",
        "RELAYER_PK": dev_key("relayer"),
        **overrides,
    }


def test_from_env_uses_token_address_from_environment(monkeypatch, tmp_path):
    _offline_chain(monkeypatch)
    monkeypatch.setattr(fuji, "DEPLOYMENTS", tmp_path)

    chain = FujiChain.from_env(
        _env(
            REGISTRY_ADDRESS=REGISTRY,
            ESCROW_ADDRESS=ESCROW,
            TOKEN_ADDRESS=TOKEN,
        )
    )

    assert chain.token_address == to_checksum_address(TOKEN)


def test_from_env_falls_back_to_deployment_token_when_only_token_is_missing(monkeypatch, tmp_path):
    _offline_chain(monkeypatch)
    monkeypatch.setattr(fuji, "DEPLOYMENTS", tmp_path)
    deployment = tmp_path / "43113.json"
    deployment.write_text(json.dumps({"registry": REGISTRY, "escrow": ESCROW, "token": TOKEN}), encoding="utf-8")

    original_read_text = Path.read_text
    reads = 0

    def count_deployment_reads(path: Path, *args, **kwargs):
        nonlocal reads
        if path == deployment:
            reads += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", count_deployment_reads)
    chain = FujiChain.from_env(_env(REGISTRY_ADDRESS=REGISTRY, ESCROW_ADDRESS=ESCROW))

    assert chain.token_address == to_checksum_address(TOKEN)
    assert reads == 1
