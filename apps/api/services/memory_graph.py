"""Resolve tenant-owned typed IDs and unique names. Never infer an unrecorded edge."""
import unicodedata
from apps.api.models.memory import EntityRelationship
from apps.api.models.entities import Customer,Product,Invoice,Commitment,SupportTicket
from apps.api.models.goals_tasks import Task,Goal
from apps.api.models.decision_evidence import Decision

def normalize(value):
    return " ".join(unicodedata.normalize("NFKC",value or "").casefold().split())

def graph(db,tenant):
    models={"Customer":(Customer,"name"),"Product":(Product,"name"),"Invoice":(Invoice,"invoice_number"),
            "Commitment":(Commitment,"title"),"SupportTicket":(SupportTicket,"subject"),
            "Task":(Task,"title"),"Goal":(Goal,"title"),"Decision":(Decision,"title")}
    nodes={};links={};lookup={};names={};truncated=False
    for kind,(model,label) in models.items():
        rows=db.query(model).filter_by(business_id=tenant).order_by(model.id).limit(5001).all()
        truncated=truncated or len(rows)>5000
        lookup[kind]={row.id:row for row in rows[:5000]}
        byname={}
        for row in rows[:5000]:
            byname.setdefault(normalize(getattr(row,label,None)),[]).append(row)
        names[kind]=byname if len(rows)<=5000 else {}
    def resolve(kind,ident,allow_name=True):
        if kind not in models:return None
        row=lookup[kind].get(ident)
        if not row and allow_name:
            matches=names[kind].get(normalize(ident),[])
            if len(matches)==1:row=matches[0]
        if row is None:return None
        key=kind+":"+row.id
        nodes[key]={"id":key,"label":getattr(row,models[kind][1],None) or row.id,"type":kind}
        return key
    def link(source,target,relation,evidence):
        if not source or not target:return
        key=(source,target,relation)
        if key not in links:links[key]={"id":"|".join(key),"source":source,"target":target,"relationship":relation,"properties":{},"evidence":[]}
        links[key]["evidence"].append(evidence)
    unresolved=[]
    recorded=db.query(EntityRelationship).filter_by(business_id=tenant).order_by(EntityRelationship.id).limit(2001).all()
    truncated=truncated or len(recorded)>2000
    for row in recorded[:2000]:
        source=resolve(row.source_type,row.source_id);target=resolve(row.target_type,row.target_id)
        if source and target:link(source,target,row.relationship,{"type":"recorded_relationship","id":row.id,"verified":False})
        else:unresolved.append({"id":row.id,"source_type":row.source_type,"target_type":row.target_type,"reason":"Unresolved or ambiguous tenant entity"})
    for kind in ("Invoice","SupportTicket"):
        for row in lookup[kind].values():
            if row.customer_id:target=resolve("Customer",row.customer_id,False)
            else:target=resolve("Customer",row.customer_name)
            if target:link(resolve(kind,row.id,False),target,"belongs_to_customer",{"type":"structured_record","id":row.id,"field":"customer_id" if row.customer_id else "unique_customer_name","verified":False})
    used={x[k] for x in links.values() for k in ("source","target")}
    return {"nodes":[v for k,v in nodes.items() if k in used],"links":list(links.values()),"unresolved":unresolved,
            "resolution":"tenant_id_or_unique_normalized_name","bounded":truncated}
