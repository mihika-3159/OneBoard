"""Closed-period unit economics with explicitly sourced cohort counts."""
from decimal import Decimal,ROUND_HALF_UP
import hashlib
from apps.api.models.operations import AccountingClose,UnitEconomicsObservation
from apps.api.services.finance_ledger import digest,period_key,serialize_close,precision
from apps.api.services.tenant_storage import _lock

def compute(snapshot,starting_customers,new_customers,lost_customers,ending_customers):
    counts=(starting_customers,new_customers,lost_customers,ending_customers)
    if any(type(n) is not int or not 0<=n<=10000000 for n in counts):raise ValueError("Invalid cohort count")
    if lost_customers>starting_customers or ending_customers!=starting_customers+new_customers-lost_customers:raise ValueError("Customer cohort does not reconcile")
    r=Decimal(snapshot["revenue"]);cost=Decimal(snapshot["cost_of_sales"])
    acquisition=Decimal(snapshot["acquisition_expense"])
    if acquisition<0 or cost<0 or r<0:raise ValueError("Negative baseline values require review")
    unit=Decimal(1).scaleb(-precision(snapshot["currency"]))
    def m(v):return str(v.quantize(unit,rounding=ROUND_HALF_UP))
    avg=Decimal(starting_customers+ending_customers)/2
    churn=Decimal(lost_customers)/starting_customers if starting_customers else None
    margin=(r-cost)/r if r else None
    arpu=r/avg if avg else None
    cac=acquisition/new_customers if new_customers else None
    # Estimate only a constant-churn gross-profit lifetime; no extrapolation
    # when the churn denominator or margin is unavailable or nonpositive.
    ltv=arpu*margin/churn if arpu is not None and margin is not None and margin>0 and churn else None
    return {"currency":snapshot["currency"],"cac":m(cac) if cac is not None else None,
      "arpu":m(arpu) if arpu is not None else None,"gross_margin_pct":str((margin*100).quantize(Decimal(".01"))) if margin is not None else None,
      "churn_pct":str((churn*100).quantize(Decimal(".01"))) if churn is not None else None,"ltv_estimate":m(ltv) if ltv is not None else None,
      "ltv_to_cac":str((ltv/cac).quantize(Decimal(".01"))) if ltv is not None and cac else None,
      "method":"acquisition spend/new customers; revenue/mean opening and closing customers; gross profit/mean customers divided by monthly starting-cohort churn",
      "limitations":"User-reported cohort counts and recorded ledger; constant churn and margin assumption, not a verified lifetime prediction"}

def serialize(row):
    return {"id":row.id,"period":row.period,"close_id":row.close_id,"source_sha256":row.source_hash,
            "inputs":row.inputs,"results":row.results,"actor_id":row.actor_id,"created_at":row.created_at.isoformat(),"independently_verified":False}

def record(db,tenant,actor,period,starting_customers,new_customers,lost_customers,ending_customers,evidence_text):
    period=period_key(period)
    if not isinstance(evidence_text,str) or not 1<=len(evidence_text.encode())<=262144 or not evidence_text.strip():raise ValueError("Cohort evidence required")
    _lock(db,tenant)
    close=db.query(AccountingClose).filter_by(business_id=tenant,period=period).first()
    if not close:raise ValueError("Unit economics requires a closed period")
    snapshot=serialize_close(close)["snapshot"]
    inputs=dict(starting_customers=starting_customers,new_customers=new_customers,lost_customers=lost_customers,ending_customers=ending_customers)
    result=compute(snapshot,**inputs)
    source_hash=hashlib.sha256(evidence_text.encode()).hexdigest()
    request=digest([inputs,source_hash,close.snapshot_hash])
    old=db.query(UnitEconomicsObservation).filter_by(business_id=tenant,period=period).first()
    if old:
        if old.request_hash!=request:raise ValueError("Cohort record already locked for this period")
        return serialize(old)
    row=UnitEconomicsObservation(business_id=tenant,period=period,close_id=close.id,source_hash=source_hash,request_hash=request,
       inputs=inputs,results=result,actor_id=actor)
    db.add(row);db.commit();return serialize(row)
