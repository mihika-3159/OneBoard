"""The recovery drill must refuse real databases and detect tampered archives."""
import hashlib
import json

import pytest

from scripts.verify_postgres_restore import (
    checked_disposable_url, verify_backup_manifest,
)


def test_disposable_restore_requires_explicit_flag(monkeypatch):
    monkeypatch.delenv("ONEBOARD_CI_DISPOSABLE_RESTORE", raising=False)
    monkeypatch.setenv(
        "ONEBOARD_TEST_POSTGRES_URL",
        "postgresql+psycopg://ci:placeholder@127.0.0.1/oneboard_ci",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://ci:placeholder@127.0.0.1/oneboard_ci",
    )
    with pytest.raises(RuntimeError, match="confirmation"):
        checked_disposable_url()


@pytest.mark.parametrize("untrusted_url", [
    "postgresql+psycopg://ci:placeholder@db.example.com/oneboard_ci",
    "postgresql+psycopg://ci:placeholder@127.0.0.1/customer_data",
    "sqlite:///./oneboard_ci.db",
])
def test_disposable_restore_refuses_remote_or_customer_database(monkeypatch, untrusted_url):
    monkeypatch.setenv("ONEBOARD_CI_DISPOSABLE_RESTORE", "1")
    monkeypatch.setenv("ONEBOARD_TEST_POSTGRES_URL", untrusted_url)
    monkeypatch.setenv("DATABASE_URL", untrusted_url)
    with pytest.raises(RuntimeError, match="Refusing"):
        checked_disposable_url()


def test_backup_manifest_detects_corruption_before_restore(tmp_path):
    archive = tmp_path / "source.dump"
    manifest = tmp_path / "manifest.json"
    archive.write_bytes(b"synthetic disposable archive fixture")
    manifest.write_text(json.dumps({
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source_database": "oneboard_ci",
    }))
    verify_backup_manifest(archive, manifest)
    archive.write_bytes(b"corrupted")
    with pytest.raises(RuntimeError, match="integrity"):
        verify_backup_manifest(archive, manifest)


def test_backup_manifest_rejects_wrong_source_database(tmp_path):
    archive = tmp_path / "source.dump"
    manifest = tmp_path / "manifest.json"
    archive.write_bytes(b"synthetic")
    manifest.write_text(json.dumps({
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source_database": "customer_production",
    }))
    with pytest.raises(RuntimeError, match="integrity"):
        verify_backup_manifest(archive, manifest)
