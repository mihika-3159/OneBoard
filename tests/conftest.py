import os
import pytest

# Ensure test environment variables are set before any apps.api modules are loaded
os.environ.setdefault("AUTH_SECRET_KEY", "test-ci-secret-key-for-oneboard-test-suite-2026")
os.environ.setdefault("ONEBOARD_DEMO_MODE", "true")
