from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

import fitz  # PyMuPDF
import pandas as pd
from pptx import Presentation

from palimind.exceptions import ParseError
from palimind.ingestion.ocr import extract_text_from_image


def parse_pdf(file_path: Path) -> str:
    text_content = []
    try:
        doc = fitz.open(file_path)
        for page_no, page in enumerate(doc, start=1):
            page_text = page.get_text("text").strip()
            if not page_text:
                pix = page.get_pixmap()
                image_bytes = pix.tobytes("png")
                page_text = extract_text_from_image(image_bytes)

            if page_text:
                text_content.append(f"[Page {page_no}]\n{page_text}")
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"Error parsing PDF {file_path}: {e}") from e

    return "\n\n".join(text_content)


def parse_pptx(file_path: Path) -> str:
    text_content = []
    try:
        prs = Presentation(file_path)
        for slide in prs.slides:
            slide_text = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    slide_text.append(shape.text)
            text = "\n".join(slide_text).strip()
            if text:
                text_content.append(text)
    except Exception as e:
        raise ParseError(f"Error parsing PPTX {file_path}: {e}") from e

    return "\n\n".join(text_content)


def parse_xlsx(file_path: Path) -> str:
    text_content = []
    try:
        df_dict = pd.read_excel(file_path, sheet_name=None, engine="openpyxl")
        for sheet_name, df in df_dict.items():
            text_content.append(f"Sheet: {sheet_name}")
            text_content.append(df.to_csv(index=False))
    except Exception as e:
        raise ParseError(f"Error parsing XLSX {file_path}: {e}") from e

    return "\n\n".join(text_content)


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(root) -> str:
    """Extract text from a DOCX body, paragraph- and table-aware, in order."""
    lines: list[str] = []
    for p in root.iter(f"{_W_NS}p"):
        text = "".join(t.text or "" for t in p.iter(f"{_W_NS}t")).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def parse_docx(file_path: Path) -> str:
    """Extract text + tables from a .docx by parsing its OOXML directly.

    Avoids adding python-docx as a hard dependency.
    """
    try:
        with zipfile.ZipFile(file_path) as zf:
            with zf.open("word/document.xml") as fh:
                root = ElementTree.parse(fh).getroot()
        return _docx_text(root).strip()
    except Exception as e:
        raise ParseError(f"Error parsing DOCX {file_path}: {e}") from e


def parse_document(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return parse_pdf(file_path)
    if ext == ".pptx":
        return parse_pptx(file_path)
    if ext == ".docx":
        return parse_docx(file_path)
    if ext in [".xlsx", ".xls"]:
        return parse_xlsx(file_path)
    return ""
