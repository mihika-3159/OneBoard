"""Guard against shipping a fixed demo password in the public browser bundle.

This is a source-level regression check, not a substitute for secret scanning
or rotating credentials previously exposed in Git history.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "apps" / "web" / "src" / "App.tsx"


def test_demo_shortcut_does_not_embed_or_prefill_password():
    source = APP.read_text(encoding="utf-8")
    assert "oneboard2026" not in source
    assert "setAuthEmail('founder@northstar.studio')" in source
    assert "setAuthPassword('')" in source
    assert "Use Demo Email" in source


def test_demo_shortcut_explains_password_is_not_bundled():
    source = APP.read_text(encoding="utf-8")
    assert "Demo credentials are not bundled in the browser." in source
