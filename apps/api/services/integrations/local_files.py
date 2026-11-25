"""Bounded local document extraction. These adapters never contact external services."""
import csv
import io
import json
import zipfile
import os,sys,subprocess
from threading import BoundedSemaphore
_PARSE_SLOTS=BoundedSemaphore(2)
from itertools import islice
from pathlib import Path
from typing import Dict, Any

import openpyxl
from pypdf import PdfReader

MAX_EXTRACTED_CHARS = 1_000_000
MAX_CSV_ROWS = 1_000
MAX_XLSX_ROWS = 1_000
MAX_XLSX_COLUMNS = 100
MAX_PDF_PAGES = 100
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
SAFE_ERRORS={"Invalid PDF signature","Encrypted PDF unsupported","PDF page limit exceeded","PDF text extraction limit exceeded","Spreadsheet archive exceeds extraction limit","Spreadsheet row limit exceeded","Spreadsheet column limit exceeded","Workbook sheet limit exceeded","Workbook row limit exceeded","Workbook text limit exceeded","Invalid workbook archive","Extracted document text exceeds processing limit"}


def _bounded_text(text: str) -> str:
    if "\x00" in text or len(text) > MAX_EXTRACTED_CHARS:
        raise ValueError("Extracted document text exceeds processing limit")
    return text


class LocalFilesAdapter:
    """Parse supported local formats with explicit extraction limits."""

    @staticmethod
    def extract_text(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        if not isinstance(file_bytes,bytes) or not 1<=len(file_bytes)<=10*1024*1024:
            raise ValueError("Invalid upload length")
        ext=Path(filename.replace("\\","/")).suffix.lower()
        if ext not in (".pdf",".xlsx"):
            try:return LocalFilesAdapter._extract(file_bytes,filename)
            except csv.Error as exc:raise ValueError("Malformed CSV") from exc
        # Untrusted compressed document parsing is isolated from the API
        # process. Bound concurrency and kill timed-out parser workers.
        if not _PARSE_SLOTS.acquire(timeout=2):
            raise ValueError("Parser busy; retry")
        try:
            env={key:os.environ[key] for key in ("PATH","SYSTEMROOT","WINDIR","TEMP","TMP","PYTHONPATH","LANG","LC_ALL") if key in os.environ}
            env.update(OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
            result=subprocess.run([sys.executable,"-m","apps.api.services.integrations.local_file_worker",ext],
                input=file_bytes,capture_output=True,timeout=25,env=env,check=False)
            if len(result.stdout)>8*1024*1024:raise ValueError("Document parser rejected input")
            parsed=json.loads(result.stdout)
            if result.returncode:
                reason=parsed.get("error") if isinstance(parsed,dict) else None
                if reason in SAFE_ERRORS:raise ValueError(reason)
                raise ValueError("Document parser rejected input")
            if not isinstance(parsed,dict) or parsed.get("file_type")!=ext[1:] or not isinstance(parsed.get("text"),str):
                raise ValueError("Invalid parser result")
            parsed["metadata"]={**parsed.get("metadata",{}),"filename":Path(filename.replace("\\","/")).name}
            return parsed
        except (subprocess.TimeoutExpired,OSError,ValueError) as exc:
            if str(exc) in SAFE_ERRORS:raise ValueError(str(exc)) from None
            raise ValueError("Document could not be parsed within resource limits") from None
        finally:
            _PARSE_SLOTS.release()

    @staticmethod
    def _extract(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        safe_filename = Path(filename.replace("\\", "/")).name
        ext = Path(safe_filename).suffix.lower()
        metadata = {"filename": safe_filename}

        if ext in (".txt", ".md"):
            text = _bounded_text(file_bytes.decode("utf-8"))
            return {"file_type": ext.lstrip("."), "text": text, "metadata": metadata}

        if ext == ".json":
            data = json.loads(file_bytes.decode("utf-8"),parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
            text = _bounded_text(json.dumps(data, indent=2, ensure_ascii=False))
            return {
                "file_type": "json", "text": text,
                "structured_data": data, "metadata": metadata
            }

        if ext == ".csv":
            content = _bounded_text(file_bytes.decode("utf-8-sig"))
            reader = csv.DictReader(io.StringIO(content),strict=True)
            if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or len(reader.fieldnames)>100:
                raise ValueError("Invalid CSV headers")
            rows = list(islice(reader, MAX_CSV_ROWS + 1))
            if any(None in row or any(v is None for v in row.values()) for row in rows):raise ValueError("Malformed CSV row")
            if len(rows) > MAX_CSV_ROWS:
                raise ValueError("CSV row limit exceeded")
            return {
                "file_type": "csv",
                "text": _bounded_text(
                    f"CSV data with {len(rows)} records. Headers: {', '.join(reader.fieldnames or [])}.\n"
                    + content
                ),
                "structured_data": rows,
                "metadata": {**metadata, "row_count": len(rows)}
            }

        if ext == ".xlsx":
            # XLSX is ZIP-based. A small upload can otherwise expand to a huge
            # workbook; check declared uncompressed size before parsing.
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                entries=archive.infolist()
                if len(entries)>1000 or len({e.filename for e in entries})!=len(entries) or any(e.flag_bits&1 for e in entries):raise ValueError("Invalid workbook archive")
                if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise ValueError("Spreadsheet archive exceeds extraction limit")
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
            try:
                if len(wb.worksheets)>20:raise ValueError("Workbook sheet limit exceeded")
                sections=[];total_rows=0;length=0
                for sheet in wb.worksheets:
                    if sheet.max_row and sheet.max_row>MAX_XLSX_ROWS:raise ValueError("Spreadsheet row limit exceeded")
                    if sheet.max_column and sheet.max_column>MAX_XLSX_COLUMNS:raise ValueError("Spreadsheet column limit exceeded")
                    lines=[]
                    for row in sheet.iter_rows(values_only=True,max_row=MAX_XLSX_ROWS+1,max_col=MAX_XLSX_COLUMNS+1):
                        if row[MAX_XLSX_COLUMNS] is not None:raise ValueError("Spreadsheet column limit exceeded")
                        if not any(c is not None for c in row[:MAX_XLSX_COLUMNS]):continue
                        total_rows+=1
                        if total_rows>MAX_XLSX_ROWS:raise ValueError("Workbook row limit exceeded")
                        line="\t".join(str(c) if c is not None else "" for c in row[:MAX_XLSX_COLUMNS])
                        length+=len(line)+1
                        if length>MAX_EXTRACTED_CHARS:raise ValueError("Workbook text limit exceeded")
                        lines.append(line)
                    sections.append("--- Sheet "+sheet.title+" ---\n"+"\n".join(lines))
                return {"file_type":"xlsx","text":_bounded_text("\n\n".join(sections)),
                        "metadata":{**metadata,"sheet_names":wb.sheetnames,"row_count":total_rows}}
            finally:
                wb.close()

        if ext == ".pdf":
            if b"%PDF-" not in file_bytes[:1024]:
                raise ValueError("Invalid PDF signature")
            reader = PdfReader(io.BytesIO(file_bytes),strict=True)
            if reader.is_encrypted:raise ValueError("Encrypted PDF unsupported")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError("PDF page limit exceeded")
            pages = []
            length = 0
            for idx, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                length += len(text)
                if length > MAX_EXTRACTED_CHARS:
                    raise ValueError("PDF text extraction limit exceeded")
                pages.append(f"--- Page {idx + 1} ---\n{text}")
            return {
                "file_type": "pdf",
                "text": _bounded_text("\n\n".join(pages)),
                "metadata": {**metadata, "page_count": len(reader.pages)}
            }

        raise ValueError(f"Unsupported file extension: {ext}")


local_files_adapter = LocalFilesAdapter()
