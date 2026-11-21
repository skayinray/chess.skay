#!/usr/bin/env python3
"""Sign release assets with Ed25519 and verify the signatures.

Usage:
    sign_release.py sign FILE [FILE ...]
    sign_release.py verify FILE SIGNATURE

The signing key is read from the RELEASE_SIGNING_KEY environment variable.
It is a base64 encoded PKCS8 PEM private key. Signatures are base64 encoded
Ed25519 signatures over the raw file bytes.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

PUBLIC_KEY_B64 = "CtH8fQqA3o/mFsZ2fRRrUzmijmvKL6OMCaDqY4tt37c="
KEY_ENV = "RELEASE_SIGNING_KEY"


def _load_private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        raise SystemExit(f"error: {KEY_ENV} is not set")

    try:
        key_data = base64.b64decode("".join(raw.split()), validate=True)
    except Exception:
        # Also accept a plain PEM key, which is convenient for local testing.
        key_data = raw.encode()

    try:
        key = serialization.load_pem_private_key(key_data, password=None)
    except Exception as exc:
        raise SystemExit(f"error: cannot load private key from {KEY_ENV}: {exc}") from exc

    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise SystemExit(f"error: {KEY_ENV} must contain an Ed25519 private key")
    return key


def _public_key():
    from cryptography.hazmat.primitives.asymmetric import ed25519

    return ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))


def _write_signature(path: Path, key) -> Path:
    signature = key.sign(path.read_bytes())
    sig_path = path.with_name(path.name + ".sig")
    sig_path.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    return sig_path


def sign(paths: list[str]) -> int:
    if not paths:
        raise SystemExit("error: sign needs at least one file")

    files = [Path(path) for path in paths]
    for path in files:
        if not path.is_file():
            raise SystemExit(f"error: not a file: {path}")

    key = _load_private_key()
    sums_path = files[0].with_name("SHA256SUMS")
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}\n")
        sig_path = _write_signature(path, key)
        print(f"signed {path} -> {sig_path}")
    sums_path.write_text("".join(lines), encoding="utf-8")
    sums_sig = _write_signature(sums_path, key)
    print(f"wrote {sums_path} -> {sums_sig}")
    return 0


def verify(file_name: str, sig_name: str) -> int:
    from cryptography.exceptions import InvalidSignature

    path = Path(file_name)
    sig_path = Path(sig_name)
    if not path.is_file():
        raise SystemExit(f"error: not a file: {path}")
    if not sig_path.is_file():
        raise SystemExit(f"error: not a signature file: {sig_path}")

    try:
        signature = base64.b64decode(sig_path.read_text(encoding="ascii").strip(), validate=True)
        _public_key().verify(signature, path.read_bytes())
    except (ValueError, InvalidSignature) as exc:
        print(f"FAIL: {path} ({exc})", file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit(__doc__)
    command, rest = args[0], args[1:]
    if command == "sign":
        return sign(rest)
    if command == "verify":
        if len(rest) != 2:
            raise SystemExit("error: verify expects FILE SIGNATURE")
        return verify(rest[0], rest[1])
    raise SystemExit(f"error: unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
