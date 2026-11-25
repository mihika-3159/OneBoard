"""Direct read-only adapters for seven representative provider categories.

Provider-specific authorization and record transforms use fixed vendor endpoints.
Live authorization and app registration are separate, explicit operator gates.
Native writes are deliberately unavailable unless a normalized adapter supplies
a durable idempotency/status contract; never fake an external delivery receipt.
"""
from datetime import datetime,timezone
import hashlib,json,re,time
from urllib.parse import urlencode,urlsplit,quote
from apps.api.core.config import settings
from apps.api.services.integrations.provider_transport import request,fingerprint,ProviderFailure

GOOGLE_AUTH="https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN="https://oauth2.googleapis.com/token"
GOOGLE_REVOKE="https://oauth2.googleapis.com/revoke"
GOOGLE_USER="https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_API="https://www.googleapis.com"
NOTION="https://api.notion.com/v1"
HUBSPOT="https://api.hubapi.com"
GITHUB="https://api.github.com"
STRIPE="https://api.stripe.com"
NATIVE={
    "crm":("contacts.read","crm.objects.contacts.read","https://app.hubspot.com/oauth/authorize",HUBSPOT+"/oauth/v3/token"),
    "email":("mail.read","https://www.googleapis.com/auth/gmail.metadata",GOOGLE_AUTH,GOOGLE_TOKEN),
    "calendar":("calendar.read","https://www.googleapis.com/auth/calendar.events.readonly",GOOGLE_AUTH,GOOGLE_TOKEN),
    "finance":("transactions.read","read_only","https://connect.stripe.com/oauth/authorize","https://connect.stripe.com/oauth/token"),
    "github":("repository.read","read:user","https://github.com/login/oauth/authorize","https://github.com/login/oauth/access_token"),
    "notion":("content.read",None,"https://api.notion.com/v1/oauth/authorize",NOTION+"/oauth/token"),
    "google":("drive.read","https://www.googleapis.com/auth/drive.metadata.readonly",GOOGLE_AUTH,GOOGLE_TOKEN),
}
GOOGLE_FAMILY={"google","calendar","email"}

def native_configuration(provider,raw):
    if provider not in NATIVE or raw.get("enabled") is not True:raise ValueError("Native adapter unavailable")
    client_id=raw.get("client_id");secret=raw.get("client_secret")
    if not isinstance(client_id,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,512}",client_id) or not isinstance(secret,str) or not 1<=len(secret)<=4096 or any(ord(c)<32 for c in secret):raise ValueError("Native OAuth app credentials unavailable")
    origin=settings.PUBLIC_API_ORIGIN
    u=urlsplit(origin)
    if u.scheme!="https" or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:raise ValueError("Native OAuth requires a public HTTPS origin")
    if provider=="notion" and (raw.get("notion_read_only_app") is not True or not isinstance(raw.get("native_scope"),str) or not 1<=len(raw["native_scope"])<=2000):
        raise ValueError("Notion requires a read-only app registration and exact introspection scope")
    if provider=="finance" and type(raw.get("stripe_livemode")) is not bool:raise ValueError("Stripe test/live mode must be selected explicitly")
    return {**raw,"mode":"native","authorize_url":NATIVE[provider][2],"token_url":NATIVE[provider][3],
            "redirect_uri":origin+"/api/integrations/providers/oauth/callback"}

def stable(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def record(ident,payload,revision=None):
    if not isinstance(ident,(str,int)) or not str(ident):raise ValueError("Native provider record lacks identity")
    return {"id":str(ident),"revision":str(revision)[:128] if revision else stable(payload),"payload":payload}

def cursor(value):
    if value is None:return {}
    try:
        out=json.loads(value)
        if not isinstance(out,dict):raise ValueError()
        return out
    except (ValueError,TypeError):raise ValueError("Invalid native checkpoint") from None

def result(records,state,more=False):
    return {"records":records,"next_cursor":json.dumps(state,sort_keys=True,separators=(",",":")),"has_more":bool(more)}

def subset(row,fields):
    return {k:row[k] for k in fields if k in row}

def safe_rows(response,key):
    rows=response.get(key,[])
    if not isinstance(rows,list) or len(rows)>100 or any(not isinstance(x,dict) for x in rows):raise ValueError("Malformed native provider page")
    return rows

class NativeAdapter:
    def __init__(self,provider,config):
        self.provider=provider;self.config=config
        self.allowed_scopes={NATIVE[provider][0]};self.actions={}
        self.fingerprint=fingerprint(config,provider)
        self.account=None
    def authorization_url(self,state,challenge,scopes):
        if set(scopes)!=self.allowed_scopes:raise ValueError("Unsupported native scope")
        p=self.provider;scope=NATIVE[p][1]
        args={"response_type":"code","client_id":self.config["client_id"],"redirect_uri":self.config["redirect_uri"],"state":state}
        if p in GOOGLE_FAMILY:
            args.update(scope="openid "+scope,access_type="offline",prompt="consent",code_challenge=challenge,code_challenge_method="S256")
        elif p=="github":args.update(scope=scope+" offline_access",code_challenge=challenge,code_challenge_method="S256")
        elif p=="notion":args["owner"]="user"
        elif p=="crm":args["scope"]=scope
        else:args["scope"]="read_only"
        return self.config["authorize_url"]+"?"+urlencode(args)
    def call(self,url,**kwargs):
        # All URL origins in this class are constants. Path identifiers are
        # quoted or strictly validated before use; cursors are parameters only.
        if self.provider=="notion":
            kwargs["extra_headers"]={"Notion-Version":"2026-03-11",**kwargs.get("extra_headers",{})}
        return request(self.config,url,**kwargs)
    def token(self,grant,**fields):
        p=self.provider;cfg=self.config
        form={"grant_type":grant,**fields}
        if p=="notion":
            out=self.call(cfg["token_url"],payload=form,auth=(cfg["client_id"],cfg["client_secret"]))
        elif p=="finance":
            out=self.call(cfg["token_url"],form=form,auth=(cfg["client_secret"],""))
        else:
            out=self.call(cfg["token_url"],form={**form,"client_id":cfg["client_id"],"client_secret":cfg["client_secret"]})
        if out.get("error"):raise ValueError("Native OAuth rejected")
        if str(out.get("token_type","")).lower()!="bearer":raise ValueError("Unexpected native token type")
        access=out.get("access_token")
        expiry=out.get("expires_in")
        refresh=out.get("refresh_token")
        if p in GOOGLE_FAMILY:
            granted=set(str(out.get("scope","")).split())
            if granted!={"openid",NATIVE[p][1]}:raise ValueError("Native Google scope mismatch")
        elif p=="github":
            granted={s for s in re.split(r"[ ,]+",str(out.get("scope",""))) if s}
            if granted!={"read:user"}:raise ValueError("Native GitHub scope mismatch")
            if expiry is None:raise ValueError("GitHub app must issue expiring OAuth tokens")
        elif p=="crm":
            granted=out.get("scopes")
            if not isinstance(granted,list) or set(granted) not in ({NATIVE[p][1]},{NATIVE[p][1],"oauth"}):raise ValueError("Native CRM scope mismatch")
            account=out.get("hub_id")
            if type(account) is not int or account<=0:raise ValueError("HubSpot account unavailable")
            self.account=str(account)
        elif p=="notion":
            introspection=self.call(NOTION+"/oauth/introspect",payload={"token":access},auth=(cfg["client_id"],cfg["client_secret"]))
            if introspection.get("active") is not True or introspection.get("scope")!=cfg["native_scope"]:raise ValueError("Notion token scope mismatch")
            self.account=out.get("workspace_id")
            if not isinstance(self.account,str) or not self.account:raise ValueError("Notion workspace unavailable")
            # Notion does not return an OAuth expiry. This is a conservative
            # local rotation/revalidation interval, not a provider expiry claim.
            expiry=expiry or 86400
            # Verify read capability without importing anything.
            self.call(NOTION+"/search",token=access,payload={"page_size":1})
        else:
            if out.get("scope")!="read_only" or out.get("livemode") is not cfg["stripe_livemode"]:raise ValueError("Stripe scope or mode mismatch")
            account=out.get("stripe_user_id")
            if not isinstance(account,str) or not re.fullmatch(r"acct_[A-Za-z0-9]+",account):raise ValueError("Stripe account unavailable")
            # Use the scoped account header with the operator's secret key,
            # not deprecated Connect bearer/refresh tokens. Local TTL is a
            # reauthorization gate rather than provider expiry.
            access=account;refresh=None;expiry=86400*30
            self.account=("live:" if cfg["stripe_livemode"] else "test:")+account
        return {"token_type":"Bearer","access_token":access,"refresh_token":refresh,
                "scope":list(self.allowed_scopes),"expires_in":expiry}
    def exchange(self,code,verifier):
        fields={"code":code}
        if self.provider!="finance":fields["redirect_uri"]=self.config["redirect_uri"]
        if self.provider in GOOGLE_FAMILY or self.provider=="github":fields["code_verifier"]=verifier
        return self.token("authorization_code",**fields)
    def refresh(self,refresh_token):
        if self.provider=="finance":raise ProviderFailure("refresh_required")
        value=self.token("refresh_token",refresh_token=refresh_token)
        if value.get("refresh_token") is None:value["refresh_token"]=refresh_token
        return value
    def identity(self,token):
        p=self.provider
        if p in GOOGLE_FAMILY:
            value=self.call(GOOGLE_USER,token=token,method="GET")
            account=value.get("sub")
        elif p=="github":
            value=self.call(GITHUB+"/user",token=token,method="GET")
            account=str(value["id"]) if type(value.get("id")) is int else None
        elif p=="finance":
            value=self.stripe_call("/v1/account",token)
            if value.get("id")!=token:raise ValueError("Stripe account mismatch")
            account=self.account
        else:account=self.account
        if not isinstance(account,str) or not 1<=len(account)<=255:raise ValueError("Native identity unavailable")
        return {"account_id":account}
    def stripe_call(self,path,account,params=None):
        if not re.fullmatch(r"acct_[A-Za-z0-9]+",account):raise ValueError("Invalid Stripe account identity")
        return self.call(STRIPE+path,method="GET",auth=(self.config["client_secret"],""),extra_headers={"Stripe-Account":account},params=params)
    def revoke_all(self,credentials,remote_account):
        cfg=self.config;p=self.provider;token=credentials["access_token"];refresh=credentials.get("refresh_token")
        if p in GOOGLE_FAMILY:
            self.call(GOOGLE_REVOKE,form={"token":refresh or token},empty_ok=True);return True
        if p=="github":
            # Only revoke this token, not every other installation of the app.
            self.call(GITHUB+"/applications/"+quote(cfg["client_id"],safe="")+"/token",method="DELETE",auth=(cfg["client_id"],cfg["client_secret"]),payload={"access_token":token},empty_ok=True)
            return not bool(refresh) # no unsupported claim that refresh was revoked
        if p=="notion":
            self.call(NOTION+"/oauth/revoke",payload={"token":token},auth=(cfg["client_id"],cfg["client_secret"]),empty_ok=True)
            proof=self.call(NOTION+"/oauth/introspect",payload={"token":token},auth=(cfg["client_id"],cfg["client_secret"]))
            return proof.get("active") is False and not bool(refresh)
        if p=="finance":
            out=self.call("https://connect.stripe.com/oauth/deauthorize",auth=(cfg["client_secret"],""),form={"client_id":cfg["client_id"],"stripe_user_id":token})
            return out.get("stripe_user_id")==token
        if refresh:
            self.call(HUBSPOT+"/oauth/2026-03/token/revoke",form={"token":refresh,"client_id":cfg["client_id"],"client_secret":cfg["client_secret"]},empty_ok=True)
        return False # revoking refresh does not prove active access token revoked
    def page(self,token,checkpoint,scopes):
        if set(scopes)!=self.allowed_scopes:raise ValueError("Native scope mismatch")
        state=cursor(checkpoint);p=self.provider
        if p=="google":return self.drive(token,state)
        if p=="calendar":return self.calendar(token,state)
        if p=="email":return self.gmail(token,state)
        if p=="crm":return self.crm(token,state)
        if p=="finance":return self.finance(token,state)
        if p=="github":return self.github(token,state)
        return self.notion(token,state)
    def drive(self,token,state):
        base=GOOGLE_API+"/drive/v3";phase=state.get("phase","files")
        if phase=="files":
            start=state.get("start")
            if not start:start=self.call(base+"/changes/startPageToken",token=token,method="GET").get("startPageToken")
            if not isinstance(start,str) or not start:raise ValueError("Drive start token unavailable")
            params={"pageSize":100,"fields":"nextPageToken,files(id,name,mimeType,modifiedTime,trashed,webViewLink)","spaces":"drive"}
            if state.get("page"):params["pageToken"]=state["page"]
            value=self.call(base+"/files",token=token,method="GET",params=params)
            rows=[record(x.get("id"),{"kind":"drive_file",**subset(x,("name","mimeType","modifiedTime","trashed","webViewLink"))}) for x in safe_rows(value,"files")]
            next_page=value.get("nextPageToken")
            return result(rows,{"phase":"files","start":start,"page":next_page} if next_page else {"phase":"changes","page":start},bool(next_page))
        if phase!="changes" or not state.get("page"):raise ValueError("Invalid Drive changes checkpoint")
        value=self.call(base+"/changes",token=token,method="GET",params={"pageToken":state["page"],"pageSize":100,"includeRemoved":"true","fields":"nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,modifiedTime,trashed,webViewLink))"})
        rows=[]
        for change in safe_rows(value,"changes"):
            file=change.get("file") or {}
            payload={"kind":"drive_file","removed":bool(change.get("removed")),**subset(file,("name","mimeType","modifiedTime","trashed","webViewLink"))}
            rows.append(record(change.get("fileId"),payload))
        next_page=value.get("nextPageToken");next_start=value.get("newStartPageToken")
        if not next_page and not next_start:raise ValueError("Missing Drive changes token")
        return result(rows,{"phase":"changes","page":next_page or next_start},bool(next_page))
    def calendar(self,token,state):
        params={"maxResults":100,"showDeleted":"true","fields":"nextPageToken,nextSyncToken,items(id,summary,start,end,status,updated,htmlLink)"}
        if state.get("sync"):params["syncToken"]=state["sync"]
        if state.get("page"):params["pageToken"]=state["page"]
        value=self.call(GOOGLE_API+"/calendar/v3/calendars/primary/events",token=token,method="GET",params=params)
        rows=[record(x.get("id"),{"kind":"calendar_event",**subset(x,("summary","start","end","status","updated","htmlLink"))}) for x in safe_rows(value,"items")]
        next_page=value.get("nextPageToken")
        next_sync=value.get("nextSyncToken")
        if not next_page and not next_sync:raise ValueError("Calendar sync token unavailable")
        return result(rows,{"sync":state.get("sync"),"page":next_page} if next_page else {"sync":next_sync},bool(next_page))
    def gmail(self,token,state):
        base=GOOGLE_API+"/gmail/v1/users/me";phase=state.get("phase","messages")
        if phase=="messages":
            start=state.get("start")
            if not start:start=self.call(base+"/profile",token=token,method="GET").get("historyId")
            if not isinstance(start,str) or not start:raise ValueError("Gmail history start unavailable")
            params={"maxResults":100,"includeSpamTrash":"false"}
            if state.get("page"):params["pageToken"]=state["page"]
            value=self.call(base+"/messages",token=token,method="GET",params=params)
            rows=[record("message:"+str(x.get("id")),{"kind":"mail_message_identity","message_id":x.get("id"),"thread_id":x.get("threadId")}) for x in safe_rows(value,"messages") if x.get("id")]
            next_page=value.get("nextPageToken")
            return result(rows,{"phase":"messages","start":start,"page":next_page} if next_page else {"phase":"history","start":start},bool(next_page))
        if phase!="history" or not state.get("start"):raise ValueError("Invalid Gmail checkpoint")
        params={"startHistoryId":state["start"],"maxResults":20}
        if state.get("page"):params["pageToken"]=state["page"]
        try:value=self.call(base+"/history",token=token,method="GET",params=params)
        except ProviderFailure as exc:
            if exc.code=="resource_missing":raise ProviderFailure("checkpoint_expired") from None
            raise
        rows=[]
        for entry in safe_rows(value,"history"):
            changes={}
            for kind in ("messagesAdded","messagesDeleted","labelsAdded","labelsRemoved"):
                changes[kind]=[{"message_id":x.get("message",{}).get("id"),"label_ids":x.get("labelIds",[])} for x in entry.get(kind,[])]
            ident=entry.get("id")
            if not ident:raise ValueError("Gmail history record lacks identity")
            rows.append(record("history:"+ident,{"kind":"mail_history","changes":changes}))
        next_page=value.get("nextPageToken");end=value.get("historyId")
        if not next_page and not end:raise ValueError("Gmail history checkpoint unavailable")
        return result(rows,{"phase":"history","start":state["start"],"page":next_page} if next_page else {"phase":"history","start":end},bool(next_page))
    def github(self,token,state):
        page=state.get("page",1)
        if type(page) is not int or not 1<=page<=200:raise ValueError("Invalid GitHub page")
        rows=self.call(GITHUB+"/user/repos",token=token,method="GET",params={"visibility":"public","per_page":100,"page":page,"sort":"updated","direction":"desc"},allow_list=True)
        if not isinstance(rows,list) or len(rows)>100:raise ValueError("Invalid GitHub repository list")
        normalized=[record(x.get("id"),{"kind":"github_public_repository",**subset(x,("name","full_name","html_url","updated_at","description","language","archived"))}) for x in rows if x.get("private") is False]
        # GitHub OAuth read:user does not grant access to private repositories.
        # Pagination is durable; subsequent scans deduplicate by revision.
        return result(normalized,{"page":page+1} if len(rows)==100 else {"page":1},len(rows)==100)
    def notion(self,token,state):
        payload={"page_size":100,"filter":{"property":"object","value":"page"},"sort":{"direction":"descending","timestamp":"last_edited_time"}}
        if state.get("page"):payload["start_cursor"]=state["page"]
        value=self.call(NOTION+"/search",token=token,payload=payload)
        rows=[]
        for x in safe_rows(value,"results"):
            title=""
            for prop in (x.get("properties") or {}).values():
                if isinstance(prop,dict) and prop.get("type")=="title":title="".join(str(t.get("plain_text","")) for t in prop.get("title",[]))[:1000];break
            rows.append(record(x.get("id"),{"kind":"notion_page_metadata","title":title,**subset(x,("last_edited_time","url","archived","in_trash"))}))
        next_page=value.get("next_cursor")
        if value.get("has_more") and not next_page:raise ValueError("Notion pagination token unavailable")
        return result(rows,{"page":next_page} if next_page else {"page":None},bool(value.get("has_more")))
    def crm(self,token,state):
        start=state.get("start",int(time.time()*1000));watermark=state.get("watermark")
        props=["firstname","lastname","email","company","lastmodifieddate"]
        if watermark is None:
            params={"limit":100,"properties":",".join(props),"archived":"false"}
            if state.get("page"):params["after"]=state["page"]
            value=self.call(HUBSPOT+"/crm/v3/objects/contacts",token=token,method="GET",params=params)
        else:
            payload={"limit":100,"properties":props,"sorts":["lastmodifieddate"],"filterGroups":[{"filters":[{"propertyName":"lastmodifieddate","operator":"GTE","value":str(max(0,watermark-300000))}]}]}
            if state.get("page"):payload["after"]=state["page"]
            value=self.call(HUBSPOT+"/crm/v3/objects/contacts/search",token=token,payload=payload)
        rows=[record(x.get("id"),{"kind":"crm_contact","properties":subset(x.get("properties") or {},props),"updated_at":x.get("updatedAt")}) for x in safe_rows(value,"results")]
        page=(value.get("paging") or {}).get("next",{}).get("after")
        return result(rows,{"start":start,"watermark":watermark,"page":page} if page else {"watermark":start},bool(page))
    def finance(self,token,state):
        start=state.get("start",int(time.time()));watermark=state.get("watermark")
        params={"limit":100}
        if watermark is not None:params["created[gte]"]=max(0,watermark-300)
        if state.get("page"):params["starting_after"]=state["page"]
        value=self.stripe_call("/v1/balance_transactions",token,params)
        raw=safe_rows(value,"data")
        rows=[record(x.get("id"),{"kind":"stripe_balance_transaction","amount_unit":"provider_minor_units",**subset(x,("amount","currency","fee","net","created","available_on","type","status","reporting_category"))}) for x in raw]
        more=value.get("has_more") is True
        if more and not raw:raise ValueError("Stripe pagination did not progress")
        return result(rows,{"start":start,"watermark":watermark,"page":raw[-1]["id"]} if more else {"watermark":start},more)
