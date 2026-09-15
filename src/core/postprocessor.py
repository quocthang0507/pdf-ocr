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

_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_TONE_MARKS = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}
_MODERN_TONE_PAIRS = {"oa", "oe", "uy"}


class Postprocessor:
    """Apply deterministic text cleanup without changing OCR confidence."""

    def correct_text(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("text phải là chuỗi văn bản.")
        normalized = unicodedata.normalize("NFC", text)
        corrected = _TOKEN_PATTERN.sub(self._correct_token, normalized)
        return self._standardize_tone_positions(corrected)

    def process_word(self, word: OCRWord) -> OCRWord:
        if not isinstance(word, OCRWord):
            raise TypeError("word phải là đối tượng OCRWord.")
        return word.with_updates(text=self.correct_text(word.text))

    def process_line(self, line: OCRLine) -> OCRLine:
        if not isinstance(line, OCRLine):
            raise TypeError("line phải là đối tượng OCRLine.")
        return line.with_updates(
            words=tuple(self.process_word(word) for word in line.words)
        )

    def process_block(self, block: OCRBlock) -> OCRBlock:
        if not isinstance(block, OCRBlock):
            raise TypeError("block phải là đối tượng OCRBlock.")
        return block.with_updates(
            lines=tuple(self.process_line(line) for line in block.lines)
        )

    def process_table(self, table: OCRTable) -> OCRTable:
        if not isinstance(table, OCRTable):
            raise TypeError("table phải là đối tượng OCRTable.")
        rows = tuple(
            tuple(self.correct_text(cell) for cell in row) for row in table.rows
        )
        return table.with_updates(rows=rows)

    def process_page(self, page: OCRPage) -> OCRPage:
        if not isinstance(page, OCRPage):
            raise TypeError("page phải là đối tượng OCRPage.")
        return page.with_updates(
            blocks=tuple(self.process_block(block) for block in page.blocks),
            tables=tuple(self.process_table(table) for table in page.tables),
        )

    def process_document(self, document: OCRDocument) -> OCRDocument:
        if not isinstance(document, OCRDocument):
            raise TypeError("document phải là đối tượng OCRDocument.")
        return document.with_updates(
            pages=tuple(self.process_page(page) for page in document.pages)
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
    def _standardize_tone_positions(text: str) -> str:
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
