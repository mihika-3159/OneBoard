"""Conservative OneBoard API entrypoint behind a local HTTPS reverse proxy.

Does not create accounts, initiate deployment, or send live data. Production
always binds to loopback, trusts only explicit operator-configured proxy IPs,
and disables development reload. The reverse proxy must provide real HTTPS,
forwarded Host, and overwrite forwarded headers. An owner-approved deployment
requires independent external validation after this launcher is configured.
"""
from __future__ import annotations

from apps.api.core.config import Settings, settings, validate_production_configuration


def secure_uvicorn_options(config: Settings) -> dict:
    """Build bounded Uvicorn options with no wildcard trusted proxy."""
    validate_production_configuration(config)
    if config.ONEBOARD_PRODUCTION_MODE:
        return {
            "host": "127.0.0.1",
            "port": 8000,
            "proxy_headers": True,
            "forwarded_allow_ips": config.TRUSTED_PROXY_IPS,
            "reload": False,
            "workers": 1,
        }
    return {
        "host": "127.0.0.1", "port": 8000,
        "proxy_headers": False,
        "reload": False, "workers": 1,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.api.main:app", **secure_uvicorn_options(settings))
