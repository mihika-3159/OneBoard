from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from apps.api.core.database import get_db
from apps.api.models.business import Business
from apps.api.models.entities import Customer, Product, Invoice, Expense
from apps.api.models.goals_tasks import Goal, Task
from apps.api.services.seed_data import seed_northstar_studio, DEMO_BUSINESS_ID

router = APIRouter(prefix="/api/business", tags=["Business"])

@router.get("")
def get_business_profile(db: Session = Depends(get_db)):
    biz = db.query(Business).filter(Business.id == DEMO_BUSINESS_ID).first()
    if not biz:
        biz = seed_northstar_studio(db)
    return biz

@router.post("/seed-demo")
def reset_demo(db: Session = Depends(get_db)):
    biz = seed_northstar_studio(db, reset=True)
    return {"status": "success", "message": "Northstar Studio demo environment reset to default state.", "business": biz}

@router.get("/metrics")
def get_dashboard_metrics(db: Session = Depends(get_db)):
    biz = db.query(Business).filter(Business.id == DEMO_BUSINESS_ID).first()
    if not biz:
        biz = seed_northstar_studio(db)

    customers = db.query(Customer).filter(Customer.business_id == DEMO_BUSINESS_ID, Customer.status == "active").all()
    invoices = db.query(Invoice).filter(Invoice.business_id == DEMO_BUSINESS_ID).all()
    expenses = db.query(Expense).filter(Expense.business_id == DEMO_BUSINESS_ID).all()
    goals = db.query(Goal).filter(Goal.business_id == DEMO_BUSINESS_ID).all()
    tasks = db.query(Task).filter(Task.business_id == DEMO_BUSINESS_ID).all()

    total_mrr = sum(c.mrr for c in customers)
    monthly_burn = sum(e.amount for e in expenses)
    overdue_invoices = [i for i in invoices if i.status == "overdue"]
    overdue_receivables = sum(i.amount for i in overdue_invoices)
    
    net_burn = max(monthly_burn - total_mrr, 0.0)
    cash_balance = biz.current_cash_balance or 132840.0
    runway_months = round(cash_balance / (net_burn or 1.0), 1) if net_burn > 0 else 24.0

    return {
        "mrr": round(total_mrr, 2),
        "monthly_burn": round(monthly_burn, 2),
        "runway_months": runway_months,
        "cash_balance": cash_balance,
        "active_customers_count": len(customers),
        "overdue_invoices_count": len(overdue_invoices),
        "overdue_receivables_amount": round(overdue_receivables, 2),
        "pending_tasks_count": len([t for t in tasks if t.status != "done"]),
        "goals_count": len(goals),
        "health_score": 88
    }
