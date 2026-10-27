"""Unicode normalization and conservative OCR confusion correction."""

from __future__ import annotations

import re
import unicodedata

from src.core.models import (
    OCRBlock,
    OCRDocument,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
)
from src.core.spell_corrector import VietnameseSpellCorrector

_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_TONE_MARKS = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}
_MODERN_TONE_PAIRS = {"oa", "oe", "uy"}
_VALID_TONE_STYLES = ("modern", "traditional", "preserve")


_SENTENCE_END = (".", "!", "?", ":", ";", "…")
_MAX_FRAGMENT_WORDS = 3


def _has_vietnamese_marks(word: str) -> bool:
    """True for letters carrying Vietnamese marks (Ề, Ố); acronyms such as
    UBND, THPT or ĐHQG have none and must stay in capitals."""
    return any(
        unicodedata.combining(char) for char in unicodedata.normalize("NFD", word)
    )


def _lower_shouted_fragments(lines: list[OCRLine]) -> list[OCRLine]:
    """Lower-case short capitalised fragments in the middle of a sentence.

    Line recognisers often read a short wrapped tail such as "về số" as
    "VỀ SỐ", which then reads "dẫn đầu VỀ SỐ lượng tuyển dụng".
    """
    result = list(lines)
    for index in range(1, len(result)):
        line = result[index]
        words = line.text.split()
        previous = result[index - 1].text.rstrip()
        following = result[index + 1].text.lstrip() if index + 1 < len(result) else ""
        if (
            not words
            or len(words) > _MAX_FRAGMENT_WORDS
            or not all(word.isupper() and _has_vietnamese_marks(word) for word in words)
            or not previous
            or previous.endswith(_SENTENCE_END)
            or not previous.split()[-1].islower()
            or (following and not following[:1].islower())
        ):
            continue
        result[index] = line.with_updates(
            words=tuple(
                word.with_updates(text=word.text.lower()) for word in line.words
            )
        )
    return result


class Postprocessor:
    """Apply deterministic text cleanup and contextual N-gram spell correction."""

    def __init__(
        self,
        spell_corrector: VietnameseSpellCorrector | None = None,
        *,
        spell_check: bool = True,
        tone_style: str = "modern",
    ) -> None:
        if tone_style not in _VALID_TONE_STYLES:
            raise ValueError("Kiểu đặt dấu thanh tiếng Việt không hợp lệ.")
        self._spell_corrector = spell_corrector or VietnameseSpellCorrector()
        self._spell_check = spell_check
        self._tone_style = tone_style

    @property
    def spell_corrector(self) -> VietnameseSpellCorrector:
        return self._spell_corrector

    @property
    def tone_style(self) -> str:
        return self._tone_style

    def set_options(
        self,
        *,
        tone_style: str | None = None,
        custom_dictionary: str | None = None,
    ) -> None:
        """Update postprocessing tone placement style and user dictionary live."""
        if tone_style is not None:
            if tone_style not in _VALID_TONE_STYLES:
                raise ValueError("Kiểu đặt dấu thanh tiếng Việt không hợp lệ.")
            self._tone_style = tone_style
        if custom_dictionary is not None:
            self._spell_corrector.load_custom_dictionary(custom_dictionary)

    def correct_text(self, text: str, *, spell_check: bool | None = None) -> str:
        if not isinstance(text, str):
            raise TypeError("text phải là chuỗi văn bản.")
        normalized = unicodedata.normalize("NFC", text)
        corrected = _TOKEN_PATTERN.sub(self._correct_token, normalized)
        use_spell = self._spell_check if spell_check is None else spell_check
        if use_spell:
            corrected = self._spell_corrector.fix_spelling(corrected)
        return self._standardize_tone_positions(corrected, self._tone_style)

    def process_word(
        self, word: OCRWord, *, spell_check: bool | None = None
    ) -> OCRWord:
        if not isinstance(word, OCRWord):
            raise TypeError("word phải là đối tượng OCRWord.")
        return word.with_updates(
            text=self.correct_text(word.text, spell_check=spell_check)
        )

    def process_line(
        self, line: OCRLine, *, spell_check: bool | None = None
    ) -> OCRLine:
        if not isinstance(line, OCRLine):
            raise TypeError("line phải là đối tượng OCRLine.")
        cleaned = [
            self.process_word(word, spell_check=spell_check) for word in line.words
        ]
        use_spell = self._spell_check if spell_check is None else spell_check
        if use_spell and len(cleaned) > 1:
            joined = " ".join(w.text for w in cleaned)
            fixed_line = self._standardize_tone_positions(
                self._spell_corrector.fix_spelling(joined),
                self._tone_style,
            )
            tokens = fixed_line.split(" ")

            if len(tokens) == len(cleaned):
                cleaned = [
                    w.with_updates(text=tok)
                    for w, tok in zip(cleaned, tokens, strict=True)
                ]
        return line.with_updates(words=tuple(cleaned))

    def process_block(
        self, block: OCRBlock, *, spell_check: bool | None = None
    ) -> OCRBlock:
        if not isinstance(block, OCRBlock):
            raise TypeError("block phải là đối tượng OCRBlock.")
        lines = [
            self.process_line(line, spell_check=spell_check) for line in block.lines
        ]
        use_spell = self._spell_check if spell_check is None else spell_check
        if use_spell:
            lines = _lower_shouted_fragments(lines)
        return block.with_updates(lines=tuple(lines))

    def process_table(
        self, table: OCRTable, *, spell_check: bool | None = None
    ) -> OCRTable:
        if not isinstance(table, OCRTable):
            raise TypeError("table phải là đối tượng OCRTable.")
        rows = tuple(
            tuple(self.correct_text(cell, spell_check=spell_check) for cell in row)
            for row in table.rows
        )
        return table.with_updates(rows=rows)

    def process_page(
        self, page: OCRPage, *, spell_check: bool | None = None
    ) -> OCRPage:
        if not isinstance(page, OCRPage):
            raise TypeError("page phải là đối tượng OCRPage.")
        return page.with_updates(
            blocks=tuple(
                self.process_block(block, spell_check=spell_check)
                for block in page.blocks
            ),
            tables=tuple(
                self.process_table(table, spell_check=spell_check)
                for table in page.tables
            ),
        )

    def process_document(
        self, document: OCRDocument, *, spell_check: bool | None = None
    ) -> OCRDocument:
        if not isinstance(document, OCRDocument):
            raise TypeError("document phải là đối tượng OCRDocument.")
        return document.with_updates(
            pages=tuple(
                self.process_page(page, spell_check=spell_check)
                for page in document.pages
            )
        )

    @staticmethod
    def _correct_token(match: re.Match[str]) -> str:
        token = match.group(0)
        if token[0].isdigit() and token[-1].isdigit():
            return token.translate(str.maketrans("OIl", "011"))
        characters = list(token)
        for index, character in enumerate(characters):
            previous = token[index - 1] if index else ""
            following = token[index + 1] if index + 1 < len(token) else ""
            adjacent_letters = previous.isalpha() or following.isalpha()
            if character == "0" and adjacent_letters:
                neighboring = previous + following
                characters[index] = "O" if neighboring.isupper() else "o"
            elif character == "1" and adjacent_letters:
                neighboring = previous + following
                characters[index] = "I" if neighboring.isupper() else "l"
            elif character == "I" and (previous.islower() or following.islower()):
                characters[index] = "i"
        return "".join(characters)

    @staticmethod
    def _standardize_tone_positions(text: str, tone_style: str = "modern") -> str:
        if tone_style == "preserve":
            return unicodedata.normalize("NFC", text)
        if tone_style == "traditional":
            return Postprocessor._apply_traditional_tones(text)
        characters = list(text)
        for index in range(len(characters) - 1):
            first = unicodedata.normalize("NFD", characters[index])
            second = unicodedata.normalize("NFD", characters[index + 1])
            pair = (first[0] + second[0]).lower()
            tones = [mark for mark in first[1:] if mark in _TONE_MARKS]
            second_has_tone = any(mark in _TONE_MARKS for mark in second[1:])
            if pair not in _MODERN_TONE_PAIRS or not tones or second_has_tone:
                continue
            first_without_tone = first[0] + "".join(
                mark for mark in first[1:] if mark not in _TONE_MARKS
            )
            characters[index] = unicodedata.normalize("NFC", first_without_tone)
            characters[index + 1] = unicodedata.normalize("NFC", second + tones[0])
        return unicodedata.normalize("NFC", "".join(characters))

    @staticmethod
    def _apply_traditional_tones(text: str) -> str:
        characters = list(text)
        for index in range(len(characters) - 1):
            first = unicodedata.normalize("NFD", characters[index])
            second = unicodedata.normalize("NFD", characters[index + 1])
            pair = (first[0] + second[0]).lower()
            tones = [mark for mark in second[1:] if mark in _TONE_MARKS]
            first_has_tone = any(mark in _TONE_MARKS for mark in first[1:])
            if pair not in _MODERN_TONE_PAIRS or not tones or first_has_tone:
                continue
            prev_base = (
                unicodedata.normalize("NFD", characters[index - 1])[0].lower()
                if index > 0
                else ""
            )
            next_is_alpha = (
                index + 2 < len(characters) and characters[index + 2].isalpha()
            )
            if prev_base == "q" or next_is_alpha:
                continue
            second_without_tone = second[0] + "".join(
                mark for mark in second[1:] if mark not in _TONE_MARKS
            )
            characters[index] = unicodedata.normalize("NFC", first + tones[0])
            characters[index + 1] = unicodedata.normalize("NFC", second_without_tone)
        return unicodedata.normalize("NFC", "".join(characters))
