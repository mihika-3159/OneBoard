"""Fail-closed startup tests for conflicting demo/production authentication flags."""
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("production,demo,secret,expected_success", [
    ("true", "true", "", False),
    ("true", "false", "", False),
    ("false", "true", "", True),
    ("true", "false", "x" * 48, True),
])
def test_auth_secret_startup_modes(production, demo, secret, expected_success):
    # A fresh interpreter matters: auth resolves its secret at import time.
    # Override .env values explicitly so the test never depends on developer keys.
    env = dict(os.environ)
    env.update({
        "ONEBOARD_PRODUCTION_MODE": production,
        "ONEBOARD_DEMO_MODE": demo,
        "AUTH_SECRET_KEY": secret,
    })
    result = subprocess.run(
        [sys.executable, "-c", "from apps.api.core.auth import SECRET_KEY; print(SECRET_KEY)"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert (result.returncode == 0) is expected_success, result.stderr
    if expected_success:
        if secret:
            assert result.stdout.strip() == secret
        else:
            assert result.stdout.strip() == "oneboard-LOCAL-DEMO-ONLY-NOT-FOR-PRODUCTION"
    else:
        assert "AUTH_SECRET_KEY" in result.stderr
