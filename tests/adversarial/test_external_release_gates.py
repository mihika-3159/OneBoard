"""External release guards are testable without network, hosts or accounts."""
from pathlib import Path
import hashlib
import json
from types import SimpleNamespace
import pytest

from apps.api.core.config import Settings, validate_production_configuration
from scripts.operations.backup_encrypted import _pg_environment, backup, verify_manifest
from scripts.operations.verify_https_edge import validate_target, probe


def production(**overrides):
    values = {
        "ONEBOARD_PRODUCTION_MODE": True,
        "ONEBOARD_DEMO_MODE": False, "DEBUG": False, "COOKIE_SECURE": True,
        "AUTH_SECRET_KEY": "a" * 64,
        "DATABASE_URL": "postgresql+psycopg://ci:placeholder@localhost/oneboard",
        "PUBLIC_API_ORIGIN": "https://api.example.test",
        "CORS_ORIGINS": "https://app.example.test",
        "TRUSTED_PROXY_IPS": "127.0.0.1",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("bad", [
    {"OLLAMA_BASE_URL": "http://model.example.test:11434"},
    {"OLLAMA_BASE_URL": "https://model.example.test"},
    {"OLLAMA_BASE_URL": "https://model.example.test", "OLLAMA_REMOTE_APPROVED": True},
    {"OLLAMA_BASE_URL": "https://user:pass@model.example.test"},
    {"OLLAMA_BASE_URL": "https://model.example.test/private"},
    {"OLLAMA_BASE_URL": "https://169.254.169.254",
     "OLLAMA_REMOTE_APPROVED": True, "OLLAMA_REMOTE_HOST": "169.254.169.254"},
    {"OLLAMA_BASE_URL": "https://host.internal",
     "OLLAMA_REMOTE_APPROVED": True, "OLLAMA_REMOTE_HOST": "host.internal"},
    {"OLLAMA_REMOTE_APPROVED": True},
])
def test_production_rejects_unapproved_inference_host(bad):
    with pytest.raises(RuntimeError, match="OLLAMA|Ollama"):
        validate_production_configuration(production(**bad))


def test_approved_host_syntax_only_not_live_eligibility():
    validate_production_configuration(production(
        OLLAMA_BASE_URL="https://model.example.test",
        OLLAMA_REMOTE_APPROVED=True, OLLAMA_REMOTE_HOST="model.example.test"
    ))


def test_backup_cannot_start_without_approval(tmp_path, monkeypatch):
    destination = tmp_path / "private"
    destination.mkdir(mode=0o700)
    env = {
        "ONEBOARD_PRODUCTION_MODE": "true",
        "DATABASE_URL": "postgresql+psycopg://ci:placeholder@localhost/oneboard",
    }
    def forbid(*args, **kwargs):
        pytest.fail("Unexpected backup subprocess")
    monkeypatch.setattr("subprocess.Popen", forbid)
    with pytest.raises(RuntimeError, match="approval"):
        backup(destination, "age1" + "q" * 58, env)
    env["ONEBOARD_BACKUP_OPERATION_APPROVED"] = "YES"
    env["ONEBOARD_PRODUCTION_MODE"] = "false"
    with pytest.raises(RuntimeError, match="approval"):
        backup(destination, "age1" + "q" * 58, env)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("url", [
    "sqlite:///tmp/customer.db",
    "postgresql+psycopg://ci:placeholder@db.example.test/customers",
    "postgresql+psycopg://ci:placeholder@db.example.test/customers?sslmode=require",
])
def test_backup_refuses_unverified_remote_database_or_sqlite(url):
    with pytest.raises(RuntimeError):
        _pg_environment({
            "ONEBOARD_BACKUP_OPERATION_APPROVED": "YES",
            "ONEBOARD_PRODUCTION_MODE": "true", "DATABASE_URL": url,
        })


def test_encrypted_manifest_detects_tampering(tmp_path):
    artifact = tmp_path / "fake.dump.age"
    artifact.write_bytes(b"fictional encrypted archive; no production data")
    manifest = Path(str(artifact) + ".json")
    manifest.write_text(json.dumps({
        "format": "age-encrypted-pg-custom-v1",
        "filename": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }))
    assert verify_manifest(artifact, manifest)["filename"] == artifact.name
    artifact.write_bytes(b"modified archive")
    with pytest.raises(RuntimeError, match="integrity"):
        verify_manifest(artifact, manifest)


@pytest.mark.parametrize("origin,configured", [
    ("http://api.example.test", "https://api.example.test"),
    ("https://api.example.test/path", "https://api.example.test"),
    ("https://evil.example.test", "https://api.example.test"),
    ("https://user@api.example.test", "https://user@api.example.test"),
])
def test_probe_denies_noncanonical_or_unapproved_target(origin, configured):
    with pytest.raises(RuntimeError, match="canonical HTTPS"):
        validate_target(origin, configured)


def test_probe_checks_hsts_host_rejection_and_forwarded_header_rewrite():
    def result(code=200, hsts="max-age=31536000"):
        return SimpleNamespace(
            status_code=code,
            headers={"strict-transport-security": hsts},
            json=lambda: {"status": "healthy"},
        )

    class FakeClient:
        def __init__(self, *, missing_hsts=False, spoofed_code=200, host_code=421):
            self.missing_hsts = missing_hsts
            self.spoofed_code = spoofed_code
            self.host_code = host_code

        def get(self, url, headers=None):
            if headers and "Host" in headers:
                return result(self.host_code)
            if headers and "X-Forwarded-Proto" in headers:
                return result(self.spoofed_code)
            return result(hsts="" if self.missing_hsts else "max-age=31536000")

    assert validate_target("https://api.example.test", "https://api.example.test")
    assert probe("https://api.example.test", FakeClient())["https"] == "passed"
    with pytest.raises(RuntimeError, match="HSTS"):
        probe("https://api.example.test", FakeClient(missing_hsts=True))
    with pytest.raises(RuntimeError, match="forwarding"):
        probe("https://api.example.test", FakeClient(spoofed_code=403))
    with pytest.raises(RuntimeError, match="Host"):
        probe("https://api.example.test", FakeClient(host_code=200))


def test_backup_manifest_collision_preserves_existing_file(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from io import BytesIO
    from scripts.operations import backup_encrypted as module

    destination = tmp_path / "private"
    destination.mkdir(mode=0o700)
    fixed = datetime(2026, 11, 25, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda _: fixed))
    monkeypatch.setattr(module.os, "urandom", lambda n: bytes([1]) * n)
    archive = destination / "oneboard-20261125T000000Z-01010101.dump.age"
    manifest = Path(str(archive) + ".json")
    manifest.write_text("existing manifest")

    def fake_popen(command, **kwargs):
        if command[0] == "age":
            kwargs["stdout"].write(b"fictional ciphertext " * 8)
        return SimpleNamespace(stdout=BytesIO(b"fictional dump"),
                               wait=lambda **_: 0, poll=lambda: 0)

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    env = {
        "ONEBOARD_BACKUP_OPERATION_APPROVED": "YES",
        "ONEBOARD_PRODUCTION_MODE": "true",
        "DATABASE_URL": "postgresql+psycopg://ci:placeholder@localhost/oneboard",
    }
    with pytest.raises(FileExistsError):
        backup(destination, "age1" + "q" * 58, env)
    assert manifest.read_text() == "existing manifest"
    assert not archive.exists()
    assert list(destination.iterdir()) == [manifest]


def test_manifest_verifier_rejects_symlink(tmp_path):
    artifact = tmp_path / "actual.dump.age"
    artifact.write_bytes(b"fictional ciphertext")
    linked = tmp_path / "linked.dump.age"
    linked.symlink_to(artifact)
    manifest = Path(str(linked) + ".json")
    manifest.write_text(json.dumps({
        "format": "age-encrypted-pg-custom-v1",
        "filename": linked.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }))
    with pytest.raises(RuntimeError, match="non-symlink"):
        verify_manifest(linked, manifest)
