"""Issue #6: parser resource bounds and truthful format support."""
import io

import openpyxl
import pytest
from pypdf import PdfWriter

from apps.api.services.integrations.local_files import (
    LocalFilesAdapter, MAX_CSV_ROWS, MAX_XLSX_ROWS, MAX_PDF_PAGES,
)


def test_binary_disguised_as_text_is_rejected():
    with pytest.raises(UnicodeDecodeError):
        LocalFilesAdapter.extract_text(b"\xff\xfe", "fake.txt")


def test_legacy_xls_is_not_silently_parsed_as_xlsx():
    with pytest.raises(ValueError, match="Unsupported file extension"):
        LocalFilesAdapter.extract_text(b"not an excel file", "legacy.xls")


def test_csv_row_limit_enforced():
    csv_data = "name\n" + "value\n" * (MAX_CSV_ROWS + 1)
    with pytest.raises(ValueError, match="CSV row limit"):
        LocalFilesAdapter.extract_text(csv_data.encode(), "records.csv")


@pytest.mark.parametrize("rows,valid", [(MAX_XLSX_ROWS, True), (MAX_XLSX_ROWS + 1, False)])
def test_spreadsheet_row_limit(rows, valid):
    wb = openpyxl.Workbook()
    ws = wb.active
    for index in range(rows):
        ws.append([f"row-{index}"])
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    if valid:
        result = LocalFilesAdapter.extract_text(buf.getvalue(), "records.xlsx")
        assert result["metadata"]["row_count"] == MAX_XLSX_ROWS
    else:
        with pytest.raises(ValueError, match="Spreadsheet row limit"):
            LocalFilesAdapter.extract_text(buf.getvalue(), "records.xlsx")


def test_invalid_pdf_signature_rejected():
    with pytest.raises(ValueError, match="Invalid PDF signature"):
        LocalFilesAdapter.extract_text(b"not a PDF", "fake.pdf")


def test_pdf_page_limit_enforced():
    writer = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 1):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(ValueError, match="PDF page limit"):
        LocalFilesAdapter.extract_text(buf.getvalue(), "long.pdf")
