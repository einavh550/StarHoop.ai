"""HMAC request signing shared by FastAPI and the Modal worker.

Milestone 4 wires an async webhook: the Modal GPU worker POSTs detection
batches back to this API. To make sure only our worker can write detections,
both sides share an HMAC-SHA256 secret. The worker signs the exact raw request
body; this API recomputes the signature and compares it in constant time.
"""

from __future__ import annotations

import hashlib
import hmac

# Header the worker sends and this API verifies. Value is "sha256=<hexdigest>".
SIGNATURE_HEADER = "X-HoopStar-Signature"
_SCHEME = "sha256="


def sign_payload(secret: str, body: bytes) -> str:
    """Return the signature header value for ``body`` under ``secret``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{_SCHEME}{digest}"


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Constant-time check that ``signature`` matches ``body`` under ``secret``."""
    if not signature:
        return False
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, signature)
