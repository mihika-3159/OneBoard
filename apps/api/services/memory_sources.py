"""Stable offsets into exact stored extracted text; immutable source revisions."""
import hashlib,re
from apps.api.models.memory import MemoryDocument,MemoryChunk,MemoryDocumentState
from apps.api.models.operations import SemanticVector
from apps.api.services.tenant_storage import _lock,check_document
from apps.api.services.semantic_index import ensure_state
from apps.api.core.config import settings

def split_text(text,file_type,source_segments=None):
    # Only parser-generated offsets may identify physical pages/sheets.
    # A page-like string embedded in user content is not provenance.
    regions=[(0,len(text),None)]
    if source_segments is not None:
        if file_type not in ("pdf","xlsx") or not isinstance(source_segments,list) or not 1<=len(source_segments)<=100:
            raise ValueError("Invalid source locations")
        regions=[];previous=0
        for segment in source_segments:
            start,end,location=segment["start"],segment["end"],segment["location"]
            if type(start) is not int or type(end) is not int or not previous<=start<end<=len(text) or not isinstance(location,str) or not 1<=len(location)<=120:
                raise ValueError("Invalid source locations")
            if text[previous:start].strip():raise ValueError("Incomplete source locations")
            regions.append((start,end,location));previous=end
        if text[previous:].strip():raise ValueError("Incomplete source locations")
    result=[];seen=set()
    for start,end,location in regions:
        while start<end:
            stop=min(start+1200,end)
            if stop<end:
                window=text[start+700:stop]
                cut=max(window.rfind("\n"),window.rfind(" "))
                if cut>=0:stop=start+700+cut+1
            raw=text[start:stop]
            left=start+len(raw)-len(raw.lstrip());right=stop-(len(raw)-len(raw.rstrip()))
            body=text[left:right]
            digest=hashlib.sha256(body.encode()).hexdigest()
            if body and (digest,location) not in seen:
                seen.add((digest,location));result.append((body,left,right,location,digest))
            if stop==end:break
            start=max(start+1,stop-100)
    return result

def citation(doc,chunk,state):
    meta=chunk.metadata_tags or {}
    start,end=meta.get("char_start"),meta.get("char_end")
    verified=type(start) is int and type(end) is int and doc.raw_content is not None and 0<=start<end<=len(doc.raw_content) and doc.raw_content[start:end]==chunk.content
    return {"document_id":doc.id,"chunk_id":chunk.id,"title":doc.title,"version":state.version if state else 1,
            "source_connector":doc.source_connector,"file_type":doc.file_type,"document_sha256":doc.content_hash,
            "chunk_sha256":hashlib.sha256(chunk.content.encode()).hexdigest(),"chunk_index":chunk.chunk_index,
            "char_start":start if verified else None,"char_end":end if verified else None,
            "location":meta.get("location") if verified else None,"offset_verified":verified,
            "source_path":"/api/memory/sources/"+chunk.id}

def ingest(db,tenant,title,raw,file_type,connector,supersedes_id=None,source_segments=None):
    if not tenant or not isinstance(title,str) or not 1<=len(title.strip())<=255:raise ValueError("Invalid document title")
    if not isinstance(raw,str) or not raw.strip() or len(raw)>1000000 or "\x00" in raw:raise ValueError("Invalid or empty extracted document")
    if not isinstance(file_type,str) or len(file_type)>20 or not isinstance(connector,str) or len(connector)>50:raise ValueError("Invalid source metadata")
    _lock(db,tenant)
    digest=hashlib.sha256(raw.encode()).hexdigest()
    previous=None;old_state=None
    if supersedes_id:
        previous=db.query(MemoryDocument).filter_by(business_id=tenant,id=supersedes_id).first()
        if not previous:raise ValueError("Source to replace unavailable")
        old_state=ensure_state(db,tenant,previous.id)
        if not old_state.active:
            successor=db.query(MemoryDocument,MemoryDocumentState).join(MemoryDocumentState,MemoryDocumentState.document_id==MemoryDocument.id).filter(
                MemoryDocument.business_id==tenant,MemoryDocumentState.business_id==tenant,
                MemoryDocumentState.supersedes_id==supersedes_id,MemoryDocument.content_hash==digest).first()
            if successor:return successor[0]
            raise ValueError("Source already superseded; reload")
        if previous.content_hash==digest:return previous
    else:
        existing=db.query(MemoryDocument).outerjoin(MemoryDocumentState,(MemoryDocumentState.document_id==MemoryDocument.id)&(MemoryDocumentState.business_id==MemoryDocument.business_id)).filter(
            MemoryDocument.business_id==tenant,MemoryDocument.title==title,MemoryDocument.content_hash==digest,
            MemoryDocument.file_type==file_type,MemoryDocument.source_connector==connector,
            (MemoryDocumentState.document_id.is_(None)|MemoryDocumentState.active.is_(True))).first()
        if existing:return existing
    parts=split_text(raw,file_type,source_segments)
    if not parts:raise ValueError("No extractable text")
    if settings.ONEBOARD_PRODUCTION_MODE:check_document(db,tenant,raw,[p[0] for p in parts])
    doc=MemoryDocument(business_id=tenant,title=title,file_type=file_type,source_connector=connector,content_hash=digest,
                       raw_content=raw,summary=raw[:200]+("..." if len(raw)>200 else ""),chunk_count=len(parts))
    db.add(doc);db.flush()
    state=MemoryDocumentState(business_id=tenant,document_id=doc.id,root_id=old_state.root_id if old_state else doc.id,
                              version=old_state.version+1 if old_state else 1,supersedes_id=supersedes_id,active=True)
    db.add(state)
    for idx,(body,start,end,location,sha) in enumerate(parts):
        db.add(MemoryChunk(document_id=doc.id,business_id=tenant,chunk_index=idx,content=body,
             metadata_tags={"source":title,"index":idx,"char_start":start,"char_end":end,"location":location,"sha256":sha}))
    if old_state:
        old_state.active=False;old_state.status="superseded";old_state.claim_token=None;old_state.lease_until=0
        ids=db.query(MemoryChunk.id).filter_by(business_id=tenant,document_id=previous.id)
        db.query(SemanticVector).filter(SemanticVector.business_id==tenant,SemanticVector.chunk_id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return doc
