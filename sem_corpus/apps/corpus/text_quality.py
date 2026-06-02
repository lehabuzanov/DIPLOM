from __future__ import annotations

import re
from dataclasses import dataclass


PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
WORD_RE = re.compile(r"[A-Za-z\u0400-\u052f]{2,}")
ALPHA_RE = re.compile(r"[A-Za-z\u0400-\u052f]")
ONE_CHAR_LINE_RE = re.compile(r"^\W?.\W?$")


@dataclass(frozen=True)
class TextQualityReport:
    char_count: int
    word_count: int
    private_use_count: int
    alpha_density: float
    one_char_line_ratio: float
    flags: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.flags


def count_private_use(value: str | None) -> int:
    if not value:
        return 0
    return len(PRIVATE_USE_RE.findall(value))


def sanitize_extracted_text(value: str | None) -> str:
    if not value:
        return ""

    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "").replace("\u00ad", "")
    text = text.replace("\u2028", "\n").replace("\u2029", "\n")
    text = CONTROL_CHAR_RE.sub(" ", text)
    text = PRIVATE_USE_RE.sub(" ", text)
    text = re.sub(r"(?<=[A-Za-z\u0400-\u052f])-\s*\n\s*(?=[A-Za-z\u0400-\u052f])", "", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def assess_text_quality(value: str | None, *, min_words: int = 120) -> TextQualityReport:
    raw_text = value or ""
    text = sanitize_extracted_text(raw_text)
    char_count = len(text)
    words = WORD_RE.findall(text)
    word_count = len(words)
    private_use_count = count_private_use(raw_text)
    alpha_count = len(ALPHA_RE.findall(text))
    alpha_density = alpha_count / char_count if char_count else 0.0
    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    one_char_lines = [line for line in non_empty_lines if ONE_CHAR_LINE_RE.fullmatch(line)]
    one_char_line_ratio = len(one_char_lines) / len(non_empty_lines) if non_empty_lines else 0.0

    flags: list[str] = []
    if not char_count:
        flags.append("empty_text")
    if private_use_count:
        flags.append("private_use_symbols")
    if word_count and word_count < min_words:
        flags.append("suspiciously_short_text")
    if char_count and alpha_density < 0.35:
        flags.append("low_alpha_density")
    if len(non_empty_lines) >= 20 and one_char_line_ratio > 0.25:
        flags.append("fragmented_lines")

    return TextQualityReport(
        char_count=char_count,
        word_count=word_count,
        private_use_count=private_use_count,
        alpha_density=alpha_density,
        one_char_line_ratio=one_char_line_ratio,
        flags=tuple(flags),
    )
