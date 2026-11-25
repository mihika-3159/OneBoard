"""ASVS authentication/session boundary: reject session swapping before DB writes."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from apps.api.core.auth import verify_session_issuance_origin
from apps.api.core.config import settings

def request(headers):
    return Request({"type":"http","method":"POST","path":"/api/auth/login","headers":[(k.lower().encode(),v.encode()) for k,v in headers.items()]})

@pytest.mark.parametrize("headers",[
    {"origin":"https://foreign.example"},
    {"origin":"null"},
    {"referer":"https://foreign.example/path"},
    {"referer":"https://oneboard.example@foreign.example/"},
    {"X-OneBoard-Session-Mode":"cookie"},
])
def test_production_untrusted_session_issuance_denied(monkeypatch,headers):
    monkeypatch.setattr(settings,"ONEBOARD_PRODUCTION_MODE",True)
    monkeypatch.setattr(settings,"CORS_ORIGINS","https://oneboard.example")
    with pytest.raises(HTTPException) as exc:verify_session_issuance_origin(request(headers))
    assert exc.value.status_code==403

@pytest.mark.parametrize("headers",[
    {},
    {"origin":"https://oneboard.example","X-OneBoard-Session-Mode":"cookie"},
    {"referer":"https://oneboard.example/path","X-OneBoard-Session-Mode":"cookie"},
])
def test_production_valid_session_issuance(monkeypatch,headers):
    monkeypatch.setattr(settings,"ONEBOARD_PRODUCTION_MODE",True)
    monkeypatch.setattr(settings,"CORS_ORIGINS","https://oneboard.example")
    verify_session_issuance_origin(request(headers))
