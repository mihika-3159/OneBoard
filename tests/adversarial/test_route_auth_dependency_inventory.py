"""Fail-closed route inventory: every nonpublic API endpoint must authenticate.

The high-impact DB mutation endpoints must additionally require the central
founder privilege dependency. This checks the actual FastAPI dependency graph,
not source-code substrings, so nested dependencies are included.
"""
from fastapi.routing import APIRoute

from apps.api.core.auth import get_current_user, require_founder_role
from apps.api.main import app

PUBLIC_API = {
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),  # Signed-session revocation and cookie CSRF checked internally.
    ("GET", "/api/council/roles"),  # Static public adviser role descriptions only.
}
FOUNDER_MUTATIONS = {
    "/api/agents",
    "/api/agents/{agent_id}/toggle-status",
    "/api/workflows",
    "/api/workflows/{workflow_id}/execute",
    "/api/workflows/approvals/{request_id}/action",
    "/api/council/deliberate",
    "/api/council/meetings/{meeting_id}/approve",
    "/api/ai/profile",
    "/api/memory/conflicts/{conflict_id}/resolve",
    "/api/memory/upload",
    "/api/integrations/{integration_id}/sync",
    "/api/accountability/verify-outcome",
}


def _dependency_calls(dependant):
    for child in dependant.dependencies:
        yield child.call
        yield from _dependency_calls(child)


def test_all_nonpublic_business_routes_require_current_authenticated_user():
    observed = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            identity = (method, route.path)
            observed.add(identity)
            if identity in PUBLIC_API:
                continue
            calls = set(_dependency_calls(route.dependant))
            assert get_current_user in calls, (
                f"{method} {route.path} has no centralized auth dependency"
            )
    assert PUBLIC_API <= observed


def test_all_privileged_mutations_have_central_founder_role_guard():
    observed = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if "POST" not in route.methods or route.path not in FOUNDER_MUTATIONS:
            continue
        observed.add(route.path)
        calls = set(_dependency_calls(route.dependant))
        assert require_founder_role in calls, (
            f"POST {route.path} must check live founder privileges"
        )
    assert observed == FOUNDER_MUTATIONS, (
        "Founder mutation inventory changed; review authorization policy: "
        f"missing={FOUNDER_MUTATIONS - observed}"
    )
