"""Independent integer arithmetic and lifecycle regressions for Batch K."""
from datetime import date,datetime,timedelta
from decimal import Decimal
from random import Random
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from sqlalchemy.exc import StatementError
import pytest
from apps.api.core.database import Base
from apps.api.models.business import Business
from apps.api.models.entities import Invoice,Customer,Expense
from apps.api.models.operations import JournalEntry,AccountingClose,BankStatementLine,FinanceForecast
from apps.api.services import finance_ledger as ledger,bank_reconciliation as bank,finance_forecasting as forecast,unit_economics as economics
from apps.api.services.financial_metrics import calculate_business_financials

@pytest.fixture
def db():
    import apps.api.models.goals_tasks,apps.api.models.agent_council,apps.api.models.memory
    import apps.api.models.workflow,apps.api.models.decision_evidence,apps.api.models.integrations
    engine=create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Business(id="a",name="A",currency="AED",current_cash_balance="123.45"),Business(id="b",name="B",currency="USD")])
        db.commit()
        yield db
    engine.dispose()

def invoice(db,amount="100.00",tenant="a",ident="inv"):
    row=Invoice(id=ident,business_id=tenant,invoice_number=ident,customer_name="Fixture",amount=amount,status="overdue",due_date=datetime(2020,1,1))
    db.add(row);db.commit();return row

def post(db,kind,amount,reference,invoice_id=None,currency="AED",rate="1",source="same_currency",date="2020-01-01",related=None,tenant="a"):
    return ledger.post(db,tenant,"actor",reference=reference,kind=kind,amount=amount,currency=currency,fx_rate=rate,
      fx_source=source,booked_on=date,evidence_text="Recorded source "+reference,invoice_id=invoice_id,related_entry_id=related)

def test_exact_money_is_integer_in_sqlite_and_decimal_in_orm(db):
    inv=invoice(db,"0.10")
    db.add_all([Customer(business_id="a",name="one",mrr="0.10"),Customer(business_id="a",name="two",mrr="0.20"),
               Expense(business_id="a",category="Hosting",vendor="Fixture",amount="0.30")])
    db.commit()
    assert db.execute(text("SELECT amount,typeof(amount) FROM invoices WHERE id='inv'")).one()==(10,"integer")
    assert db.get(Invoice,"inv").amount==Decimal("0.10")
    summary=calculate_business_financials(db,"a")
    assert Decimal(summary["exact_amounts"]["mrr"])==Decimal("0.30")
    assert Decimal(summary["exact_amounts"]["monthly_burn"])==Decimal("0.30")
    assert summary["net_burn"]==0
    inv.amount="0.001"
    with pytest.raises(StatementError,match="sub-cent"):db.commit()
    db.rollback()
    assert db.get(Invoice,"inv").amount==Decimal("0.10")

def test_partial_payment_credit_refund_and_idempotency(db):
    inv=invoice(db)
    post(db,"invoice_issue","100","issue-0001",inv.id)
    p=post(db,"payment","20","payment-0001",inv.id)
    assert post(db,"payment","20","payment-0001",inv.id).id==p.id
    with pytest.raises(ValueError,match="reference"):post(db,"payment","21","payment-0001",inv.id)
    db.rollback()
    c=post(db,"credit","10","credit-0001",inv.id)
    assert ledger.invoice_balance(db,"a",inv)==Decimal("70")
    post(db,"refund","5","refund-0001",inv.id,related=p.id)
    post(db,"credit_reversal","2","reverse-0001",inv.id,related=c.id)
    post(db,"debit_adjustment","3","debit-0001",inv.id)
    assert ledger.invoice_balance(db,"a",inv)==Decimal("80")
    assert calculate_business_financials(db,"a")["overdue_receivables_amount"]==80
    with pytest.raises(ValueError,match="exceeds"):post(db,"refund","16","refund-0002",inv.id,related=p.id)
    db.rollback()
    with pytest.raises(ValueError,match="exceeds"):post(db,"payment","80.01","payment-0002",inv.id)
    db.rollback()
    post(db,"payment","80","payment-0003",inv.id)
    assert inv.status=="paid" and ledger.invoice_balance(db,"a",inv)==0
    post(db,"refund","5","refund-0003",inv.id,related=p.id)
    assert inv.status=="overdue" and ledger.invoice_balance(db,"a",inv)==5
    assert sum(ledger.trial_balance(db.query(JournalEntry).all(),"AED").values())==0

def test_currency_conversion_and_original_payment_reversal(db):
    inv=invoice(db)
    post(db,"opening_invoice","100","opening-0001",inv.id)
    p=post(db,"payment","10.01","payment-0001",inv.id,"USD","3.6725","dated supplied quote")
    # 10.01 * 3.6725 = 36.761725 -> 36.76 AED
    assert p.original_minor==1001 and p.base_minor==3676
    assert ledger.invoice_balance(db,"a",inv)==Decimal("63.24")
    post(db,"refund","10.01","refund-0001",inv.id,"USD","3.6725","dated supplied quote",related=p.id)
    assert ledger.invoice_balance(db,"a",inv)==100
    assert ledger.minor("123","JPY")==123
    assert ledger.minor("1.234","KWD")==1234
    with pytest.raises(ValueError,match="precision"):ledger.minor("1.01","JPY")
    with pytest.raises(ValueError,match="Same currency"):post(db,"expense","1","expense-0001",currency="AED",rate="2")
    db.rollback()
    with pytest.raises(ValueError,match="missing"):post(db,"payment","1","foreign-0001",inv.id,currency="USD",tenant="b")

def test_bank_reconciliation_close_and_immutable_history(db):
    inv=invoice(db)
    post(db,"opening_cash","500","opening-0001")
    post(db,"invoice_issue","100","issue-0001",inv.id)
    payment=post(db,"payment","100","payment-0001",inv.id)
    expense=post(db,"cogs","25","expense-0001")
    csv="reference,date,currency,amount\nreceipt,2020-01-01,AED,100.00\ncost,2020-01-01,AED,-25.00\n"
    preview=bank.import_lines(db,"a","Operating",csv,True)
    assert preview["new"]==2 and not db.query(BankStatementLine).count()
    imported=bank.import_lines(db,"a","Operating",csv)
    assert imported["new"]==2 and bank.import_lines(db,"a","Operating",csv)["duplicates"]==2
    lines={r["reference"]:r for r in imported["records"]}
    with pytest.raises(ValueError,match="Reconcile"):ledger.close_period(db,"a","actor","2020-01","CLOSE 2020-01")
    db.rollback()
    assert [r.id for r in bank.candidates(db,"a",db.get(BankStatementLine,lines["receipt"]["id"]))]==[payment.id]
    with pytest.raises(ValueError):bank.match(db,"b","actor",lines["receipt"]["id"],payment.id)
    db.rollback()
    with pytest.raises(ValueError):bank.match(db,"a","actor",lines["receipt"]["id"],expense.id)
    db.rollback()
    bank.match(db,"a","actor",lines["receipt"]["id"],payment.id)
    bank.match(db,"a","actor",lines["cost"]["id"],expense.id)
    closed=ledger.close_period(db,"a","actor","2020-01","CLOSE 2020-01")
    assert closed["snapshot"]["cash_balance"]=="575.00"
    assert closed["snapshot"]["gross_profit"]=="75.00"
    assert closed["snapshot"]["gross_margin_pct"]=="75.00"
    assert closed["snapshot"]["bank_verified"] is False
    assert ledger.close_period(db,"a","actor","2020-01","CLOSE 2020-01")==closed
    with pytest.raises(ValueError,match="closed"):post(db,"expense","1","blocked-0001")
    db.rollback()
    with pytest.raises(ValueError,match="closed"):post(db,"expense","1","blocked-0002",date="2019-12-31")
    db.rollback()
    assert ledger.serialize_close(db.query(AccountingClose).one())==closed

def test_independent_random_integer_receivable_matrix(db):
    rng=Random(198)
    inv=invoice(db,"5000")
    post(db,"invoice_issue","5000","issue-0001",inv.id)
    expected=500000
    for i in range(100):
        value=rng.randint(1,1000)
        kind=rng.choice(["payment","credit","debit_adjustment"])
        post(db,kind,str(Decimal(value)/100),f"matrix-{i:04}",inv.id)
        expected+=value if kind=="debit_adjustment" else -value
        assert ledger.invoice_balance(db,"a",inv)==Decimal(expected)/100
    assert ledger.trial_balance(db.query(JournalEntry).all(),"AED")["receivables"]==expected

def test_scenario_math_and_missing_denominators():
    s={"currency":"AED","period":"2026-01","cash_balance":"1000","revenue":"200","cost_of_sales":"50","operating_expenses":"50","acquisition_expense":"30"}
    assumptions={k:{"revenue_growth":"0","expense_growth":"0","collection_fraction":v} for k,v in (("low","0.5"),("base","0.75"),("high","1"))}
    _,res=forecast.scenarios(s,3,assumptions)
    assert [Decimal(x["cash"]) for x in res["base"]]==[1050,1100,1150]
    assert Decimal(res["low"][-1]["cash"])==1000
    assert Decimal(res["high"][-1]["cash"])==1300
    econ=economics.compute(s,10,2,2,10)
    assert econ["cac"]=="15.00" and econ["ltv_estimate"]=="75.00" and econ["gross_margin_pct"]=="75.00"
    assert economics.compute(s,10,0,0,10)["ltv_estimate"] is None
    assert economics.compute(s,10,0,0,10)["cac"] is None
    with pytest.raises(ValueError,match="cohort"):economics.compute(s,10,2,2,11)

def test_forecast_outcome_uses_closed_record_and_cannot_be_replaced(db,monkeypatch):
    class Clock(date):
        @classmethod
        def today(cls):return cls(2020,2,1)
    monkeypatch.setattr(forecast,"date",Clock)
    inv=invoice(db)
    post(db,"invoice_issue","100","issue-0001",inv.id)
    ledger.close_period(db,"a","actor","2020-01","CLOSE 2020-01")
    a={k:{"revenue_growth":"0","expense_growth":"0","collection_fraction":"0"} for k in ("low","base","high")}
    row=forecast.create(db,"a","actor","2020-01",1,a)
    with pytest.raises(ValueError,match="closed|close"):forecast.observe(db,"a","actor",row["id"])
    db.rollback()
    post(db,"debit_adjustment","90","adjust-0001",inv.id,date="2020-02-01")
    ledger.close_period(db,"a","actor","2020-02","CLOSE 2020-02")
    actual=forecast.observe(db,"a","actor",row["id"])
    assert actual["outcome"]["metrics"]["revenue"]["absolute_error"]=="10.00"
    assert actual["outcome"]["metrics"]["revenue"]["within_scenario_range"] is False
    assert forecast.observe(db,"a","other",row["id"])==actual
    with pytest.raises(ValueError):forecast.observe(db,"b","actor",row["id"])
