"""Exact fixed-millesimal storage for legacy base-currency records; ledger uses currency-specific minor units."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator

MAX=Decimal("100000000000")
STORAGE_QUANTUM=Decimal("0.001")

def decimal_value(value):
    if value is None or isinstance(value,bool):raise ValueError("Missing or invalid monetary amount")
    try:d=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as exc:raise ValueError("Invalid monetary amount") from exc
    if not d.is_finite() or abs(d)>MAX:raise ValueError("Nonfinite or excessive monetary amount")
    return d

def storage_units(value):
    d=decimal_value(value)
    if d!=d.quantize(STORAGE_QUANTUM):raise ValueError("Monetary amount exceeds storage precision")
    return int(d*1000)

class ExactMoney(TypeDecorator):
    impl=BigInteger
    cache_ok=True
    def process_bind_param(self,value,dialect):
        return None if value is None else storage_units(value)
    def process_result_value(self,value,dialect):
        if value is None:return None
        if type(value) is not int:raise ValueError("Invalid stored monetary integer")
        return Decimal(value)/1000
