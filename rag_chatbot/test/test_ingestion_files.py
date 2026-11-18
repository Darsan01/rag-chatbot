import pandas as pd
import pytest

from rag_chatbot.core.ingestion import LocalDataIngestion
from rag_chatbot.ui.ui import LocalChatbotUI, MAX_FILE_SIZE


def test_extracts_xlsx_sheets(tmp_path):
    workbook = tmp_path / "report.xlsx"
    with pd.ExcelWriter(workbook) as writer:
        pd.DataFrame({"name": ["Ada"], "score": [98]}).to_excel(
            writer, sheet_name="Results", index=False
        )

    text = LocalDataIngestion()._extract_text(str(workbook))

    assert "Sheet: Results" in text
    assert "Ada,98" in text


def test_extracts_source_code(tmp_path):
    source = tmp_path / "example.py"
    source.write_text("def answer():\n    return 42\n", encoding="utf-8")

    assert "return 42" in LocalDataIngestion()._extract_text(str(source))


def test_rejects_unsupported_attachment(tmp_path):
    attachment = tmp_path / "archive.zip"
    attachment.write_bytes(b"archive")
    ui = LocalChatbotUI.__new__(LocalChatbotUI)

    with pytest.raises(ValueError, match="not supported"):
        ui._validate_message_files({"files": [str(attachment)]})


def test_rejects_oversized_attachment(tmp_path):
    attachment = tmp_path / "large.pdf"
    with attachment.open("wb") as file:
        file.seek(MAX_FILE_SIZE)
        file.write(b"\0")
    ui = LocalChatbotUI.__new__(LocalChatbotUI)

    with pytest.raises(ValueError, match="25 MB"):
        ui._validate_message_files({"files": [str(attachment)]})
