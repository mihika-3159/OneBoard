"""Security regressions for the signed session's maximum permitted lifetime.

A signature proves integrity, but it must not permit an accidentally issued
multi-year session to bypass the configured seven-day expiration policy.
"""
import base64
import hashlib
import hmac
import json
import time

import pytest

from apps.api.core import auth


def _signed(payload):
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        auth.SECRET_KEY.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def _claims(now, *, lifetime):
    return {
        "jti": "test-session",
        "sub": "test-user",
        "biz": "test-tenant",
        "role": "founder",
        "iat": now,
        "exp": now + lifetime,
    }


def test_signed_token_cannot_exceed_configured_lifetime():
    now = int(time.time())
    with pytest.raises(ValueError, match="Invalid access token"):
        auth.decode_access_token(
            _signed(_claims(now, lifetime=auth.TOKEN_EXPIRY_SECONDS + 1))
        )


def test_signed_token_accepts_exact_maximum_lifetime():
    now = int(time.time())
    payload = _claims(now, lifetime=auth.TOKEN_EXPIRY_SECONDS)
    assert auth.decode_access_token(_signed(payload))["sub"] == "test-user"


def test_signed_token_rejects_ancient_issue_with_future_expiry():
    now = int(time.time())
    payload = _claims(now - auth.TOKEN_EXPIRY_SECONDS * 2, lifetime=auth.TOKEN_EXPIRY_SECONDS * 3)
    with pytest.raises(ValueError, match="Invalid access token"):
        auth.decode_access_token(_signed(payload))
