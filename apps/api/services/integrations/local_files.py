"""Bounded local document extraction. These adapters never contact external services."""
import csv
import io
import json
import zipfile
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


def _bounded_text(text: str) -> str:
    if len(text) > MAX_EXTRACTED_CHARS:
        raise ValueError("Extracted document text exceeds processing limit")
    return text


class LocalFilesAdapter:
    """Parse supported local formats with explicit extraction limits."""

    @staticmethod
    def extract_text(file_bytes: bytes, filename: str) -> Dict[str, Any]:
        safe_filename = Path(filename.replace("\\", "/")).name
        ext = Path(safe_filename).suffix.lower()
        metadata = {"filename": safe_filename}

        if ext in (".txt", ".md"):
            text = _bounded_text(file_bytes.decode("utf-8"))
            return {"file_type": ext.lstrip("."), "text": text, "metadata": metadata}

        if ext == ".json":
            data = json.loads(file_bytes.decode("utf-8"))
            text = _bounded_text(json.dumps(data, indent=2, ensure_ascii=False))
            return {
                "file_type": "json", "text": text,
                "structured_data": data, "metadata": metadata
            }

        if ext == ".csv":
            content = _bounded_text(file_bytes.decode("utf-8-sig"))
            reader = csv.DictReader(io.StringIO(content))
            rows = list(islice(reader, MAX_CSV_ROWS + 1))
            if len(rows) > MAX_CSV_ROWS:
                raise ValueError("CSV row limit exceeded")
            return {
                "file_type": "csv",
                "text": _bounded_text(
                    f"CSV data with {len(rows)} records. Headers: {', '.join(reader.fieldnames or [])}.\n"
                    + content[:2000]
                ),
                "structured_data": rows,
                "metadata": {**metadata, "row_count": len(rows)}
            }

        if ext == ".xlsx":
            # XLSX is ZIP-based. A small upload can otherwise expand to a huge
            # workbook; check declared uncompressed size before parsing.
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise ValueError("Spreadsheet archive exceeds extraction limit")
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
            try:
                sheet = wb.active
                rows = []
                if sheet:
                    if sheet.max_row and sheet.max_row > MAX_XLSX_ROWS:
                        raise ValueError("Spreadsheet row limit exceeded")
                    if sheet.max_column and sheet.max_column > MAX_XLSX_COLUMNS:
                        raise ValueError("Spreadsheet column limit exceeded")
                    for row in sheet.iter_rows(
                        values_only=True, max_row=MAX_XLSX_ROWS + 1,
                        max_col=MAX_XLSX_COLUMNS + 1
                    ):
                        if len(rows) >= MAX_XLSX_ROWS:
                            raise ValueError("Spreadsheet row limit exceeded")
                        if len(row) > MAX_XLSX_COLUMNS and row[MAX_XLSX_COLUMNS] is not None:
                            raise ValueError("Spreadsheet column limit exceeded")
                        if any(cell is not None for cell in row[:MAX_XLSX_COLUMNS]):
                            rows.append([str(c) if c is not None else "" for c in row[:MAX_XLSX_COLUMNS]])
                text = _bounded_text("\n".join("\t".join(row) for row in rows[:100]))
                return {
                    "file_type": "xlsx", "text": text,
                    "structured_data": rows,
                    "metadata": {**metadata, "sheet_names": wb.sheetnames, "row_count": len(rows)}
                }
            finally:
                wb.close()

        if ext == ".pdf":
            if b"%PDF-" not in file_bytes[:1024]:
                raise ValueError("Invalid PDF signature")
            reader = PdfReader(io.BytesIO(file_bytes))
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
