"""Opt-in external TLS, Host and forwarded-header smoke test (GET only).

No network requests are issued without BOTH --probe and owner approval.
A passing result does not prove network isolation or full security.
"""
import argparse
import os
from urllib.parse import urlsplit
import httpx


def validate_target(origin: str, expected_origin: str) -> str:
    url = urlsplit(origin)
    if (not origin or origin != expected_origin or url.scheme != "https"
            or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment
            or origin != "https://" + url.netloc):
        raise RuntimeError("Target must equal the configured canonical HTTPS API origin")
    return origin


def probe(origin: str, client) -> dict:
    normal = client.get(origin + "/health")
    if normal.status_code != 200 or normal.json().get("status") != "healthy":
        raise RuntimeError("HTTPS health probe failed")
    if "max-age=" not in normal.headers.get("strict-transport-security", ""):
        raise RuntimeError("HTTPS response is missing HSTS")
    for name,expected in (("x-content-type-options","nosniff"),("x-frame-options","DENY"),("referrer-policy","no-referrer")):
        if normal.headers.get(name)!=expected:raise RuntimeError("HTTPS response missing expected header: "+name)
    bad_host = client.get(origin + "/health", headers={"Host": "invalid-oneboard-host.invalid"})
    if bad_host.status_code not in (400, 421):
        raise RuntimeError("Unrecognized Host was not rejected")
    spoofed = client.get(origin + "/health", headers={
        "X-Forwarded-Proto": "http",
        "X-Forwarded-Host": "invalid-oneboard-host.invalid",
    })
    if spoofed.status_code != 200:
        raise RuntimeError("Proxy appears to trust forged forwarding headers")
    return dict(https="passed", host="rejected", forwarded_headers="sanitized",
                certificate="verified_by_http_client", backend_network_isolation="untested")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    origin = validate_target(args.origin, os.environ.get("PUBLIC_API_ORIGIN", ""))
    if not args.probe:
        print("Offline origin validation only; certificate and network UNVERIFIED")
        return
    if os.environ.get("ONEBOARD_EXTERNAL_PROBE_APPROVED") != "YES":
        raise RuntimeError("Explicit operator approval required for external HTTPS probe")
    with httpx.Client(verify=True, trust_env=False, timeout=5, follow_redirects=False) as client:
        print(probe(origin, client))
    print("Direct backend isolation and external security audit remain UNVERIFIED")


if __name__ == "__main__":
    main()
