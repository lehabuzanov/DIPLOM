from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass

from pypdf import PdfReader

from sem_corpus.apps.corpus.text_quality import assess_text_quality, count_private_use, sanitize_extracted_text

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional dependency fallback
    fitz = None


@dataclass(frozen=True)
class PDFTextExtractionResult:
    text: str
    engine: str
    page_count: int
    empty_pages: int
    image_only_pages: int
    private_use_count: int
    warnings: tuple[str, ...] = ()


def _candidate_score(result: PDFTextExtractionResult) -> float:
    quality = assess_text_quality(result.text)
    return (
        quality.word_count * 10
        + quality.char_count
        - result.private_use_count * 1000
        - result.empty_pages * 450
        - result.image_only_pages * 250
    )


def _is_healthy_primary_candidate(result: PDFTextExtractionResult) -> bool:
    quality = assess_text_quality(result.text)
    return quality.ok and result.empty_pages == 0 and result.image_only_pages == 0


def _extract_with_pymupdf(payload: bytes) -> PDFTextExtractionResult | None:
    if fitz is None:
        return None

    warnings: list[str] = []
    pages: list[str] = []
    empty_pages = 0
    image_only_pages = 0
    with fitz.open(stream=payload, filetype="pdf") as document:
        for page in document:
            page_text = page.get_text("text", sort=True) or ""
            pages.append(page_text)
            if not page_text.strip():
                empty_pages += 1
                if page.get_images(full=True):
                    image_only_pages += 1

        page_count = document.page_count

    if image_only_pages:
        warnings.append(f"{image_only_pages} page(s) contain images but no extractable text")

    raw_text = "\n\n".join(pages)
    text = sanitize_extracted_text(raw_text)
    return PDFTextExtractionResult(
        text=text,
        engine="pymupdf",
        page_count=page_count,
        empty_pages=empty_pages,
        image_only_pages=image_only_pages,
        private_use_count=count_private_use(raw_text),
        warnings=tuple(warnings),
    )


def _extract_pypdf_page_text(page) -> str:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            layout_text = page.extract_text(extraction_mode="layout") or ""
        except TypeError:
            layout_text = ""
        except Exception:
            layout_text = ""

        try:
            plain_text = page.extract_text() or ""
        except Exception:
            plain_text = ""

    if len(plain_text.strip()) > len(layout_text.strip()) * 1.2:
        return plain_text
    return layout_text or plain_text


def _extract_with_pypdf(payload: bytes) -> PDFTextExtractionResult:
    reader = PdfReader(io.BytesIO(payload))
    pages: list[str] = []
    empty_pages = 0
    for page in reader.pages:
        page_text = _extract_pypdf_page_text(page)
        pages.append(page_text)
        if not page_text.strip():
            empty_pages += 1

    raw_text = "\n\n".join(pages)
    text = sanitize_extracted_text(raw_text)
    return PDFTextExtractionResult(
        text=text,
        engine="pypdf",
        page_count=len(reader.pages),
        empty_pages=empty_pages,
        image_only_pages=0,
        private_use_count=count_private_use(raw_text),
    )


def extract_pdf_text_result(payload: bytes) -> PDFTextExtractionResult:
    if not payload:
        raise ValueError("Empty PDF payload.")

    candidates: list[PDFTextExtractionResult] = []
    errors: list[str] = []

    try:
        primary_result = _extract_with_pymupdf(payload)
    except Exception as exc:  # noqa: BLE001
        primary_result = None
        errors.append(f"_extract_with_pymupdf: {exc}")

    if primary_result is not None:
        if _is_healthy_primary_candidate(primary_result):
            return primary_result
        candidates.append(primary_result)

    try:
        candidates.append(_extract_with_pypdf(payload))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"_extract_with_pypdf: {exc}")

    if not candidates:
        detail = "; ".join(errors) if errors else "no extractor available"
        raise ValueError(f"PDF text extraction failed: {detail}")

    candidates.sort(key=_candidate_score, reverse=True)
    return candidates[0]


def extract_pdf_text(payload: bytes) -> str:
    return extract_pdf_text_result(payload).text


def validate_pdf_payload(payload: bytes) -> None:
    if not payload:
        raise ValueError("Empty PDF payload.")
    if fitz is not None:
        with fitz.open(stream=payload, filetype="pdf") as document:
            if document.page_count < 1:
                raise ValueError("PDF has no pages.")
        return
    reader = PdfReader(io.BytesIO(payload))
    if len(reader.pages) < 1:
        raise ValueError("PDF has no pages.")
