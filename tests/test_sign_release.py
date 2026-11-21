"""The release signing utility produces well formed signatures and checksums."""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

import sign_release


@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> ed25519.Ed25519PrivateKey:
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    monkeypatch.setenv(sign_release.KEY_ENV, base64.b64encode(pem).decode("ascii"))
    return key


def test_public_key_is_32_bytes() -> None:
    assert len(base64.b64decode(sign_release.PUBLIC_KEY_B64)) == 32


def test_sign_writes_checksums_and_signatures(tmp_path, signing_key) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"release bytes")

    assert sign_release.sign([str(asset)]) == 0

    sums = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    assert sums == f"{digest}  asset.bin\n"
    assert len(base64.b64decode((tmp_path / "asset.bin.sig").read_text())) == 64
    assert len(base64.b64decode((tmp_path / "SHA256SUMS.sig").read_text())) == 64


def test_verify_rejects_corrupt_signature(tmp_path, signing_key) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"release bytes")
    sign_release.sign([str(asset)])

    sig = tmp_path / "asset.bin.sig"
    sig.write_text(base64.b64encode(b"x" * 64).decode("ascii"), encoding="ascii")
    assert sign_release.verify(str(asset), str(sig)) == 1
