"""Adversarial checks for signed session claims (including valid-HMAC attacks)."""
import base64
import hashlib
import hmac
import json
import os
import time

import pytest

# Local test mode is explicitly opt-in; no production authentication bypass.
os.environ.setdefault("ONEBOARD_DEMO_MODE", "true")

from apps.api.core.auth import SECRET_KEY, create_access_token, decode_access_token


def _signed(payload):
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        SECRET_KEY.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def test_valid_token_round_trip():
    token = create_access_token("user", "tenant")
    assert decode_access_token(token)["biz"] == "tenant"


@pytest.mark.parametrize("mutation", [
    lambda p: {**p, "exp": int(time.time())},
    lambda p: {**p, "exp": None},
    lambda p: {**p, "exp": True},
    lambda p: {**p, "exp": "tomorrow"},
    lambda p: {**p, "iat": "yesterday"},
    lambda p: {**p, "iat": int(time.time()) + 3600},
    lambda p: {**p, "sub": None},
    lambda p: {**p, "biz": ""},
    lambda p: {k: v for k, v in p.items() if k != "jti"},
    lambda p: [],
])
def test_rejects_malformed_signed_claims(mutation):
    now = int(time.time())
    valid = {"jti": "session", "sub": "user", "biz": "tenant", "iat": now, "exp": now + 600}
    with pytest.raises(ValueError, match="Invalid access token"):
        decode_access_token(_signed(mutation(valid)))

def test_valid_signature_does_not_permit_duplicate_claims():
    now=int(time.time())
    raw=json.dumps({"jti":"session","sub":"user","biz":"tenant","iat":now,"exp":now+600})
    raw=raw[:-1]+',"biz":"other"}'
    encoded=base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    signature=hmac.new(SECRET_KEY.encode(),encoded.encode(),hashlib.sha256).hexdigest()
    with pytest.raises(ValueError):decode_access_token(encoded+"."+signature)

def test_valid_signature_does_not_permit_noncanonical_encoding():
    encoded=create_access_token("user","tenant").split(".")[0]+"="
    signature=hmac.new(SECRET_KEY.encode(),encoded.encode(),hashlib.sha256).hexdigest()
    with pytest.raises(ValueError):decode_access_token(encoded+"."+signature)
