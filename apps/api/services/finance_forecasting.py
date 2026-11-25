"""Reproducible scenario forecasts and outcomes linked to immutable period closes."""
from decimal import Decimal,ROUND_HALF_UP
from datetime import date,datetime
from apps.api.core.money import decimal_value
from apps.api.models.operations import AccountingClose,FinanceForecast
from apps.api.services.finance_ledger import digest,serialize_close,minor,major,period_key,workspace
from apps.api.services.tenant_storage import _lock

def next_month(period,offset):
    y,m=map(int,period.split("-"));n=y*12+m-1+offset
    return f"{n//12:04d}-{n%12+1:02d}"

def rate(value):
    d=decimal_value(value)
    if not Decimal("-1")<=d<=Decimal("5"):raise ValueError("Growth assumption must be -1 to 5")
    return d

def scenarios(snapshot,months,assumptions):
    if type(months) is not int or not 1<=months<=24:raise ValueError("Forecast horizon must be 1–24 months")
    if set(assumptions)!={"low","base","high"}:raise ValueError("Exactly low, base and high assumptions required")
    currency=snapshot["currency"];scale=Decimal(10)**__import__("apps.api.services.finance_ledger",fromlist=["precision"]).precision(currency)
    cash=Decimal(snapshot["cash_balance"]);revenue=Decimal(snapshot["revenue"]);cost=Decimal(snapshot["cost_of_sales"])+Decimal(snapshot["operating_expenses"])
    if revenue<0 or cost<0:raise ValueError("Negative baseline revenue or expense requires review")
    normalized={};result={}
    for name,config in assumptions.items():
        if not isinstance(config,dict) or set(config)!={"revenue_growth","expense_growth","collection_fraction"}:raise ValueError("Each scenario needs revenue growth, expense growth and collection fraction")
        rg,eg,cf=rate(config["revenue_growth"]),rate(config["expense_growth"]),rate(config["collection_fraction"])
        if not 0<=cf<=1:raise ValueError("Collection fraction must be between zero and one")
        normalized[name]={"revenue_growth":str(rg),"expense_growth":str(eg),"collection_fraction":str(cf)}
        r,c,b=revenue,cost,cash;points=[]
        def rnd(v):return (v*scale).quantize(Decimal(1),rounding=ROUND_HALF_UP)/scale
        for n in range(1,months+1):
            r=rnd(r*(1+rg));c=rnd(c*(1+eg));collections=rnd(r*cf);b=rnd(b+collections-c)
            if any(abs(v)>Decimal("100000000000") for v in (r,c,b)):raise ValueError("Scenario exceeds monetary bound")
            points.append({"period":next_month(snapshot["period"],n),"revenue":str(r),"expenses":str(c),"collections":str(collections),"cash":str(b)})
        result[name]=points
    # Low/high are ordered ranges rather than statistical confidence intervals.
    for i in range(months):
        for key in ("revenue","cash"):
            if not Decimal(result["low"][i][key])<=Decimal(result["base"][i][key])<=Decimal(result["high"][i][key]):raise ValueError("Scenario low/base/high ranges cross")
    return normalized,result

def create(db,tenant,actor,baseline_period,months,assumptions):
    _lock(db,tenant);baseline_period=period_key(baseline_period)
    if db.query(FinanceForecast).filter_by(business_id=tenant).count()>=1000:raise ValueError("Forecast capacity reached")
    closed=db.query(AccountingClose).filter_by(business_id=tenant,period=baseline_period).first()
    if not closed:raise ValueError("Forecast requires a closed accounting baseline")
    base=serialize_close(closed)
    if next_month(baseline_period,1)<=date.today().isoformat()[:7]:raise ValueError("Forecast baseline must immediately precede a future observation period")
    normalized,result=scenarios(base["snapshot"],months,assumptions)
    row=FinanceForecast(business_id=tenant,actor_id=actor,assumptions={"months":months,"scenarios":normalized,"method":"monthly_compound_growth_and_collection_fraction","uncertainty":"assumption_based_not_probability"},
        baseline={"close_id":base["id"],"period":baseline_period,"snapshot":base["snapshot"]},baseline_hash=base["snapshot_sha256"],results=result,due_period=next_month(baseline_period,months))
    db.add(row);db.commit();return serialize(row)

def serialize(row):
    return {"id":row.id,"actor_id":row.actor_id,"created_at":row.created_at.isoformat(),"baseline":row.baseline,
            "baseline_sha256":row.baseline_hash,"assumptions":row.assumptions,"scenarios":row.results,
            "due_period":row.due_period,"outcome":row.outcome,"provenance":"deterministic_assumption_based_not_verified_prediction"}

def observe(db,tenant,actor,ident):
    _lock(db,tenant)
    row=db.query(FinanceForecast).filter_by(business_id=tenant,id=ident).first()
    if not row:raise ValueError("Forecast unavailable")
    if row.outcome:return serialize(row)
    closed=db.query(AccountingClose).filter_by(business_id=tenant,period=row.due_period).first()
    if not closed:raise ValueError("Forecast outcome requires the due period's immutable close")
    actual=serialize_close(closed);values={}
    for metric,actual_key in (("revenue","revenue"),("cash","cash_balance")):
        a=Decimal(actual["snapshot"][actual_key]);p=Decimal(row.results["base"][-1][metric])
        low=Decimal(row.results["low"][-1][metric]);high=Decimal(row.results["high"][-1][metric])
        values[metric]={"actual":str(a),"predicted":str(p),"absolute_error":str(abs(a-p)),"within_scenario_range":low<=a<=high}
    row.outcome={"close_id":actual["id"],"snapshot_sha256":actual["snapshot_sha256"],"actor_id":actor,
                 "recorded_at":datetime.utcnow().isoformat(),"metrics":values,"independently_verified":False}
    db.commit();return serialize(row)
