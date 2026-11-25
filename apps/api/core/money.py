"""Exact fixed-cent storage for legacy base-currency records; ledger uses currency-specific minor units."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator

MAX=Decimal("100000000000")
CENT=Decimal("0.01")

def decimal_value(value):
    if value is None or isinstance(value,bool):raise ValueError("Missing or invalid monetary amount")
    try:d=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as exc:raise ValueError("Invalid monetary amount") from exc
    if not d.is_finite() or abs(d)>MAX:raise ValueError("Nonfinite or excessive monetary amount")
    return d

def cents(value):
    d=decimal_value(value)
    if d!=d.quantize(CENT):raise ValueError("Monetary amount has sub-cent precision")
    return int(d*100)

class ExactMoney(TypeDecorator):
    impl=BigInteger
    cache_ok=True
    def process_bind_param(self,value,dialect):
        return None if value is None else cents(value)
    def process_result_value(self,value,dialect):
        if value is None:return None
        if type(value) is not int:raise ValueError("Invalid stored monetary integer")
        return Decimal(value)/100
