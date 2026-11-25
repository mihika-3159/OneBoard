"""Bounded DAG branches and explicit predecessor scalar bindings; no eval."""
from math import isfinite

OPS={"eq","ne","gt","gte","lt","lte"}

def ancestors(node,edges):
    result=set(); pending=[node]
    while pending:
        target=pending.pop()
        for edge in edges:
            if edge["target"]==target and edge["source"] not in result:
                result.add(edge["source"]);pending.append(edge["source"])
    return result

def validate_conditions(nodes,edges):
    by_id={n["id"]:n for n in nodes}
    for edge in edges:
        branch=edge.get("branch")
        if branch is not None and (type(branch) is not bool or by_id[edge["source"]].get("type")!="condition"):
            raise ValueError("Branch edges require a boolean condition source")
    for n in nodes:
        data=n.get("data",{})
        if n.get("type")=="condition" and data.get("operator") not in OPS:
            raise ValueError("Unsupported condition operator")
        bindings=data.get("bindings",{})
        if not isinstance(bindings,dict) or len(bindings)>8:
            raise ValueError("Invalid data bindings")
        for key,ref in bindings.items():
            if n.get("type")!="condition" or key!="left" or not isinstance(ref,dict) or ref.get("step") not in ancestors(n["id"],edges) or not isinstance(ref.get("field"),str):
                raise ValueError("Only condition operands may bind an ancestor result")

def resolve_data(data,node,edges,results):
    out=dict(data)
    for key,ref in out.pop("bindings",{}).items():
        if key!="left" or ref.get("step") not in ancestors(node,edges):
            raise ValueError("Invalid predecessor binding")
        result=results.get(ref["step"],{}).get("result")
        if not isinstance(result,dict) or ref["field"] not in result:
            raise ValueError("Missing predecessor value")
        out[key]=result[ref["field"]]
    return out

def condition_result(data):
    left,right=data.get("left"),data.get("right")
    if type(left) not in (str,int,float,bool) or type(right) not in (str,int,float,bool):
        raise ValueError("Condition requires scalar values")
    op=data.get("operator")
    if op not in OPS: raise ValueError("Invalid comparison")
    if op in ("eq","ne"):
        equal=type(left)==type(right) and left==right or type(left) in (int,float) and type(right) in (int,float) and left==right
        return {"branch":equal if op=="eq" else not equal}
    if type(left) not in (int,float) or type(right) not in (int,float) or not all(isfinite(x) for x in (left,right)):
        raise ValueError("Numeric comparison requires finite numbers")
    return {"branch":{"gt":left>right,"gte":left>=right,"lt":left<right,"lte":left<=right}[op]}

def should_skip(node,edges,results):
    incoming=[e for e in edges if e["target"]==node]
    if not incoming:return False
    for e in incoming:
        entry=results.get(e["source"],{})
        if entry.get("status") not in ("success","approved"):continue
        if "branch" not in e or entry.get("result",{}).get("branch") is e["branch"]:return False
    return True
