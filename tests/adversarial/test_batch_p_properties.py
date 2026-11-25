"""Deterministic generated properties with reproducible seeds; no external services."""
from decimal import Decimal
import random
import pytest
from apps.api.core.money import storage_units,ExactMoney
from apps.api.services.finance_ledger import minor,major
from apps.api.services.workflow_conditions import condition_result
from apps.api.services.inference_budget import inference_tenant,current_inference_tenant
from apps.api.services.financial_reconciliation import parse_evidence

def test_exact_money_roundtrip_generated():
    rng=random.Random(127013)
    for _ in range(3000):
        n=rng.randint(-10**11,10**11)
        d=Decimal(n).scaleb(-3)
        assert storage_units(d)==n
        assert ExactMoney().process_result_value(n,None)==d
        for currency,scale in (("USD",2),("JPY",0),("KWD",3)):
            value=Decimal(n).scaleb(-scale)
            assert minor(value,currency,signed=True)==n
            assert Decimal(major(n,currency))==value

@pytest.mark.parametrize("value",["NaN","Infinity","-Infinity","0.00001","100000000001",True,None])
def test_invalid_money_fails_closed(value):
    with pytest.raises(ValueError):storage_units(value)

def test_generated_conditions_preserve_comparison_and_no_bool_numeric_coercion():
    rng=random.Random(612)
    for _ in range(1000):
        a,b=rng.randint(-100000,100000),rng.randint(-100000,100000)
        for op,expected in (("eq",a==b),("ne",a!=b),("gt",a>b),("lte",a<=b)):
            assert condition_result({"left":a,"right":b,"operator":op})["branch"] is expected
    assert condition_result({"left":True,"right":1,"operator":"eq"})["branch"] is False
    with pytest.raises(ValueError):condition_result({"left":"1","right":1,"operator":"gt"})

def test_nested_tenant_context_always_unwinds():
    assert current_inference_tenant() is None
    with inference_tenant("synthetic-a"):
        with pytest.raises(RuntimeError):
            with inference_tenant("synthetic-b"):
                assert current_inference_tenant()=="synthetic-b"
                raise RuntimeError("synthetic fault")
        assert current_inference_tenant()=="synthetic-a"
    assert current_inference_tenant() is None

def test_csv_malformed_input_fuzz():
    rng=random.Random(193)
    for _ in range(300):
        tail="".join(rng.choice("abc,\n\"012345") for _ in range(rng.randrange(1,80)))
        # Intentionally invalid header cannot be interpreted as financial data.
        with pytest.raises(ValueError):parse_evidence("wrong_header\n"+tail)

def test_valid_and_corrupted_financial_csv_rows():
    import csv,io
    rng=random.Random(351)
    header=["record_type","record_id","amount","currency","as_of"]
    def encode(rows):
        out=io.StringIO();writer=csv.writer(out);writer.writerow(header);writer.writerows(rows);return out.getvalue()
    for i in range(150):
        amount=Decimal(rng.randint(1,100000)).scaleb(-2)
        row=["invoice","test-"+str(i),str(amount),"USD","2020-01-01"]
        assert len(parse_evidence(encode([row])))==1
        for column,bad in ((0,"unexpected"),(1,"invalid id"),(2,"NaN"),(3,"$$$"),(4,"not-a-date")):
            mutated=row.copy();mutated[column]=bad
            with pytest.raises(ValueError):parse_evidence(encode([mutated]))
        with pytest.raises(ValueError):parse_evidence(encode([row,row]))
