"""Operator-configured OAuth and normalized provider adapter protocol.

No tenant-supplied URLs, redirects, credentials in logs, or implicit network access.
The normalized API is an explicit bridge contract, not a claim that every vendor
implements these endpoints. Operators must configure a trusted adapter.
"""
import json,re
from urllib.parse import urlsplit,urlencode
import httpx
from apps.api.core.config import settings

CAPABILITIES={
    "crm":({"contacts.read","contacts.write"},{"contact.upsert":"contacts.write"}),
    "email":({"mail.read","mail.send"},{"email.send":"mail.send"}),
    "calendar":({"calendar.read","calendar.write"},{"event.create":"calendar.write"}),
    "finance":({"transactions.read"},{}),
    "github":({"repository.read","issues.write"},{"issue.create":"issues.write"}),
    "notion":({"content.read","content.write"},{"page.create":"content.write"}),
    "google":({"drive.read","calendar.read","drive.write"},{"document.create":"drive.write"}),
}
MAX_BODY=1024*1024

class ProviderFailure(Exception):
    def __init__(self,code,retryable=False,retry_after=0):
        super().__init__(code);self.code=code;self.retryable=retryable;self.retry_after=retry_after

def scopes_valid(provider,scopes):
    if provider not in CAPABILITIES or not isinstance(scopes,list) or not scopes or len(scopes)>16 or any(not isinstance(x,str) for x in scopes) or len(set(scopes))!=len(scopes) or not set(scopes)<=CAPABILITIES[provider][0]:
        raise ValueError("Unsupported provider scopes")
    return sorted(scopes)

def endpoint(value,host):
    try:
        u=urlsplit(value)
        if u.scheme!="https" or u.hostname!=host or u.username or u.password or u.fragment or u.query or u.port not in (None,443) or not u.path.startswith("/") or u.netloc!=host:
            raise ValueError()
        return value
    except (ValueError,TypeError,AttributeError):raise ValueError("Unsafe provider endpoint") from None

def configuration(provider):
    if provider not in CAPABILITIES:raise ValueError("Unsupported provider")
    raw=settings.PROVIDER_CONNECTORS.get(provider)
    if not isinstance(raw,dict) or raw.get("enabled") is not True:raise ValueError("Provider adapter is not configured")
    host=raw.get("host")
    if not isinstance(host,str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]+\.[a-z]{2,63}",host) or host.endswith((".local",".internal",".localhost")):raise ValueError("Invalid provider host")
    config=dict(raw)
    for name in ("authorize_url","token_url","identity_url","sync_url","revoke_url","action_url","status_url"):
        if name in ("action_url","status_url") and not CAPABILITIES[provider][1]:continue
        config[name]=endpoint(raw.get(name),host)
    if not isinstance(config.get("client_id"),str) or not 1<=len(config["client_id"])<=512:raise ValueError("Provider client is not configured")
    if not isinstance(config.get("client_secret",""),str) or len(config.get("client_secret",""))>4096:raise ValueError("Invalid provider client secret")
    origin=settings.PUBLIC_API_ORIGIN
    try:
        u=urlsplit(origin)
        if u.scheme!="https" or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:raise ValueError()
    except (ValueError,TypeError):raise ValueError("Provider authorization needs a configured HTTPS public origin") from None
    config["redirect_uri"]=origin+"/api/integrations/providers/oauth/callback"
    return config

def request(config,url,*,token=None,form=None,payload=None,method="POST"):
    # URL is chosen exclusively from server-validated connector configuration.
    headers={"Accept":"application/json"}
    if token is not None:headers["Authorization"]="Bearer "+token
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0,connect=4.0),follow_redirects=False,trust_env=False) as client:
            with client.stream(method,url,headers=headers,data=form,json=payload) as response:
                status=response.status_code
                if status==429 or status>=500:
                    retry=response.headers.get("Retry-After","")
                    try:seconds=min(3600,max(0,int(retry)))
                    except ValueError:seconds=0
                    raise ProviderFailure("rate_limited" if status==429 else "provider_unavailable",True,seconds)
                if status in (401,403):raise ProviderFailure("authorization_rejected")
                if not 200<=status<300:raise ProviderFailure("provider_rejected")
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>MAX_BODY:raise ProviderFailure("response_too_large")
                try:
                    out=json.loads(raw)
                    if not isinstance(out,dict):raise ValueError()
                    return out
                except (ValueError,UnicodeError):raise ProviderFailure("invalid_provider_response") from None
    except httpx.RequestError:raise ProviderFailure("transport_uncertain",True) from None

class Adapter:
    def __init__(self,provider):
        self.provider=provider
        self.config=configuration(provider)
    def authorization_url(self,state,challenge,scopes):
        return self.config["authorize_url"]+"?"+urlencode({"response_type":"code","client_id":self.config["client_id"],
            "redirect_uri":self.config["redirect_uri"],"scope":" ".join(scopes),"state":state,"code_challenge":challenge,"code_challenge_method":"S256"})
    def token(self,grant,**fields):
        data={"grant_type":grant,"client_id":self.config["client_id"],**fields}
        if self.config.get("client_secret"):data["client_secret"]=self.config["client_secret"]
        return request(self.config,self.config["token_url"],form=data)
    def exchange(self,code,verifier):
        return self.token("authorization_code",code=code,code_verifier=verifier,redirect_uri=self.config["redirect_uri"])
    def refresh(self,refresh_token):
        return self.token("refresh_token",refresh_token=refresh_token)
    def identity(self,token):
        return request(self.config,self.config["identity_url"],token=token,method="GET")
    def page(self,token,cursor,scopes):
        return request(self.config,self.config["sync_url"],token=token,payload={"cursor":cursor,"scopes":scopes,"limit":100})
    def revoke(self,token):
        return request(self.config,self.config["revoke_url"],form={"token":token,"client_id":self.config["client_id"],"client_secret":self.config.get("client_secret","")})
    def deliver(self,token,action,payload,key):
        return request(self.config,self.config["action_url"],token=token,payload={"action":action,"payload":payload,"idempotency_key":key})
    def delivery_status(self,token,key):
        return request(self.config,self.config["status_url"],token=token,payload={"idempotency_key":key})

def adapter_for(provider):
    return Adapter(provider)
