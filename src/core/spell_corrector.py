"""Vietnamese OCR spell and diacritic correction using N-gram context and orthography.

Inspired by https://github.com/quangts2531/OCRSpellCorrection (1/2/3-gram contextual
disambiguation, token validation for numbers/emails/phones/proper nouns, and
Vietnamese diacritic/vowel confusion repair).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)*$")
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_VN_PHONE_RE = re.compile(r"^(?:0[35789]|\+?84[35789])[0-9]{8}$")
_WORD_TOKEN_RE = re.compile(r"([^\W\d_]+)", flags=re.UNICODE)
#: Surnames that are not also everyday words, so capitalising them before a
#: capitalised given name is safe ("nguyễn Văn An" -> "Nguyễn Văn An").
_DISTINCT_SURNAMES = frozenset(
    {
        "nguyễn",
        "trần",
        "phạm",
        "huỳnh",
        "vũ",
        "võ",
        "đặng",
        "bùi",
        "đỗ",
        "trương",
        "trịnh",
        "quách",
        "phùng",
        "nghiêm",
        "tôn",
    }
)
_SENTENCE_END = (".", "!", "?")
_CONTINUATION = ("...", "…")

# Direct single-syllable OCR vowel/horn/tone confusions that are orthographically
# invalid or overwhelmingly OCR errors in Vietnamese documents.
_ORTHOGRAPHIC_FIXES: dict[str, str] = {
    "đưạc": "được",
    "đưọc": "được",
    "dưỏi": "dưới",
    "dưởi": "dưới",
    "ngưòi": "người",
    "ngưởi": "người",
    "mưòi": "mười",
    "cưòi": "cười",
    "tưỏi": "tươi",
    "lưói": "lưới",
    "trưóc": "trước",
    "trưạc": "trước",
    "nưóc": "nước",
    "nưạc": "nước",
    "bưóc": "bước",
    "bưạc": "bước",
    "thưong": "thương",
    "trưòng": "trường",
    "trưạng": "trường",
    "đưòng": "đường",
    "đưạng": "đường",
    "hưóng": "hướng",
    "hưạng": "hướng",
    "lưọng": "lượng",
    "lưạng": "lượng",
    "phưong": "phương",
    "tưỏng": "tưởng",
    "thưòng": "thường",
    "chưong": "chương",
    "lưong": "lương",
    "vưòn": "vườn",
    "mưọn": "mượn",
    "mưạn": "mượn",
    "vưọt": "vượt",
    "vưạt": "vượt",
    "lưọt": "lượt",
    "lưạt": "lượt",
    "trưọt": "trượt",
    "gổm": "gồm",
    "ngửng": "ngừng",
}

# Contextual 2-gram (left, right) -> corrected (left, right) pairs for frequent
# Vietnamese OCR diacritic drops and tone confusions.
_BIGRAM_FIXES: dict[tuple[str, str], tuple[str, str]] = {
    ("nhan", "vien"): ("nhân", "viên"),
    ("nhân", "vien"): ("nhân", "viên"),
    ("nhan", "viên"): ("nhân", "viên"),
    ("cấp", "dưởi"): ("cấp", "dưới"),
    ("cấp", "duới"): ("cấp", "dưới"),
    ("tổ", "chửc"): ("tổ", "chức"),
    ("tổ", "chuc"): ("tổ", "chức"),
    ("to", "chức"): ("tổ", "chức"),
    ("không", "ngửng"): ("không", "ngừng"),
    ("khong", "ngừng"): ("không", "ngừng"),
    ("đổi", "mởi"): ("đổi", "mới"),
    ("đổi", "moi"): ("đổi", "mới"),
    ("doi", "mới"): ("đổi", "mới"),
    ("thuong", "hiệu"): ("thương", "hiệu"),
    ("thương", "hieu"): ("thương", "hiệu"),
    ("thuong", "hieu"): ("thương", "hiệu"),
    ("tiếp", "can"): ("tiếp", "cận"),
    ("tiep", "cận"): ("tiếp", "cận"),
    ("rộng", "hon"): ("rộng", "hơn"),
    ("nhiều", "hon"): ("nhiều", "hơn"),
    ("tốt", "hon"): ("tốt", "hơn"),
    ("cao", "hon"): ("cao", "hơn"),
    ("lớn", "hon"): ("lớn", "hơn"),
    ("kinh", "nghiem"): ("kinh", "nghiệm"),
    ("quản", "ly"): ("quản", "lý"),
    ("quan", "lý"): ("quản", "lý"),
    ("khách", "hang"): ("khách", "hàng"),
    ("khach", "hàng"): ("khách", "hàng"),
    ("sản", "pham"): ("sản", "phẩm"),
    ("san", "phẩm"): ("sản", "phẩm"),
    ("dịch", "vu"): ("dịch", "vụ"),
    ("dich", "vụ"): ("dịch", "vụ"),
    ("cải", "thien"): ("cải", "thiện"),
    ("trải", "nghiem"): ("trải", "nghiệm"),
    ("công", "ty"): ("công", "ty"),
    ("cong", "ty"): ("công", "ty"),
    ("hợp", "dong"): ("hợp", "đồng"),
    ("hop", "đồng"): ("hợp", "đồng"),
    ("quyết", "dinh"): ("quyết", "định"),
    ("quyet", "định"): ("quyết", "định"),
    ("thực", "hien"): ("thực", "hiện"),
    ("phát", "trien"): ("phát", "triển"),
    ("hệ", "thong"): ("hệ", "thống"),
    ("tài", "lieu"): ("tài", "liệu"),
    ("báo", "cao"): ("báo", "cáo"),
    ("ngân", "hang"): ("ngân", "hàng"),
    ("việt", "nam"): ("việt", "nam"),
    ("viet", "nam"): ("việt", "nam"),
    ("độc", "lap"): ("độc", "lập"),
    ("hạnh", "phuc"): ("hạnh", "phúc"),
}

# Contextual 3-gram fixes (w1, w2, w3) -> (c1, c2, c3)
_TRIGRAM_FIXES: dict[tuple[str, str, str], tuple[str, str, str]] = {
    ("kinh", "nghiệm", "lý"): ("kinh", "nghiệm", "quản lý"),
    ("cộng", "hoa", "xã"): ("cộng", "hòa", "xã"),
    ("xã", "hoi", "chủ"): ("xã", "hội", "chủ"),
    ("chủ", "nghia", "việt"): ("chủ", "nghĩa", "việt"),
}


def is_valid_token(token: str) -> bool:
    """Return True if `token` is an ordinary word eligible for spell correction.

    Mirrors OCRSpellCorrection's `Probability.is_valid_token`: numbers, emails,
    Vietnamese phone numbers, and tokens with non-alphabetic characters are skipped.
    """
    cleaned = token.strip()
    if not cleaned:
        return False
    if _NUMBER_RE.match(cleaned):
        return False
    if _EMAIL_RE.match(cleaned):
        return False
    if _VN_PHONE_RE.match(cleaned):
        return False
    if "_" in cleaned and all(
        part[:1].isupper() for part in cleaned.split("_") if part
    ):
        return False
    return all(ch.isalpha() or ch == "_" for ch in cleaned)


def _match_case(source: str, target: str) -> str:
    """Apply the casing pattern of `source` onto `target`."""
    if not source or not target:
        return target
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[0].isupper():
        return target[0].upper() + target[1:]
    return target


class VietnameseSpellCorrector:
    """Contextual 1/2/3-gram and orthographic spell corrector for Vietnamese OCR."""

    def __init__(self, dictionary_dir: str | Path | None = None) -> None:
        self._sym_1gram: Any = None
        self._sym_2gram: Any = None
        self._sym_3gram: Any = None
        if dictionary_dir is not None:
            self.load_symspell_dictionaries(dictionary_dir)

    def load_symspell_dictionaries(
        self, dictionary_dir: str | Path, separator: str = "$"
    ) -> bool:
        """Load optional SymSpell 1/2/3-gram dictionaries if available on disk."""
        folder = Path(dictionary_dir)
        f1 = folder / "frequency_vi_test.txt"
        f2 = folder / "dic_2_gram_test.txt"
        f3 = folder / "dic_3_gram_test.txt"
        if not (f1.is_file() and f2.is_file() and f3.is_file()):
            return False
        try:
            import importlib

            symspell_mod = importlib.import_module("symspellpy")
            sym_cls = symspell_mod.SymSpell
        except (ImportError, AttributeError):
            return False
        opts = {
            "max_dictionary_edit_distance": 2,
            "prefix_length": 7,
            "count_threshold": 1,
        }
        s1, s2, s3 = sym_cls(**opts), sym_cls(**opts), sym_cls(**opts)
        s1.load_dictionary(str(f1), 0, 1, separator=separator)
        s2.load_dictionary(str(f2), 0, 1, separator=separator)
        s3.load_dictionary(str(f3), 0, 1, separator=separator)
        self._sym_1gram, self._sym_2gram, self._sym_3gram = s1, s2, s3
        return True

    def fix_spelling(self, text: str) -> str:
        """Correct Vietnamese OCR diacritic and contextual N-gram errors per line."""
        if not isinstance(text, str):
            raise TypeError("text phải là chuỗi văn bản.")
        if not text.strip():
            return text
        normalized = unicodedata.normalize("NFC", text)
        lines = normalized.split("\n")
        return "\n".join(self._fix_line(line) for line in lines)

    def _fix_line(self, line: str) -> str:
        matches = list(_WORD_TOKEN_RE.finditer(line))
        if not matches:
            return line
        words = [m.group(0) for m in matches]
        elig = [
            is_valid_token(w) and not (idx > 0 and w[0].isupper() and w[1:].islower())
            for idx, w in enumerate(words)
        ]
        # 1. Single-word orthographic fixes
        for i, word in enumerate(words):
            if not elig[i]:
                continue
            replacement = _ORTHOGRAPHIC_FIXES.get(word.lower())
            if replacement is not None:
                words[i] = _match_case(word, replacement)
        # 2. Contextual 3-gram fixes
        self._apply_trigrams(words, elig, matches, line)
        # 3. Contextual 2-gram fixes
        self._apply_bigrams(words, elig, matches, line)
        # 4. Capitals that line recognisers tend to drop
        self._restore_capitals(words, matches, line)
        return self._reassemble(line, matches, words)

    @staticmethod
    def _restore_capitals(
        words: list[str], matches: list[re.Match[str]], line: str
    ) -> None:
        """Re-capitalise sentence starts and surnames read as lower case.

        Line recognisers often confuse S/s, C/c and similar capitals, giving
        "ngành nghề. số lao động" or "nguyễn Văn An".
        """
        for i in range(1, len(words)):
            word = words[i]
            if not word.islower():
                continue
            between = line[matches[i - 1].end() : matches[i].start()]
            gap = between.strip()
            if (
                between[-1:].isspace()
                and gap.endswith(_SENTENCE_END)
                and not gap.endswith(_CONTINUATION)
                and not (gap == "." and len(words[i - 1]) <= 2)
            ):
                words[i] = word[0].upper() + word[1:]
        for i in range(len(words) - 1):
            word, following = words[i], words[i + 1]
            if (
                word.islower()
                and word in _DISTINCT_SURNAMES
                and following[:1].isupper()
                and line[matches[i].end() : matches[i + 1].start()] == " "
            ):
                words[i] = word[0].upper() + word[1:]

    @staticmethod
    def _adjacent(line: str, m1: re.Match[str], m2: re.Match[str]) -> bool:
        """Only apply n-gram replacements when no punctuation separates the tokens."""
        between = line[m1.end() : m2.start()]
        return between.strip() == ""

    def _apply_trigrams(
        self,
        words: list[str],
        elig: list[bool],
        matches: list[re.Match[str]],
        line: str,
    ) -> None:
        for i in range(len(words) - 2):
            if not (elig[i] and elig[i + 1] and elig[i + 2]):
                continue
            if not (
                self._adjacent(line, matches[i], matches[i + 1])
                and self._adjacent(line, matches[i + 1], matches[i + 2])
            ):
                continue
            key = (words[i].lower(), words[i + 1].lower(), words[i + 2].lower())
            fixed = _TRIGRAM_FIXES.get(key)
            if fixed is not None:
                words[i] = _match_case(words[i], fixed[0])
                words[i + 1] = _match_case(words[i + 1], fixed[1])
                words[i + 2] = _match_case(words[i + 2], fixed[2])

    def _apply_bigrams(
        self,
        words: list[str],
        elig: list[bool],
        matches: list[re.Match[str]],
        line: str,
    ) -> None:
        for i in range(len(words) - 1):
            if not (elig[i] and elig[i + 1]):
                continue
            if not self._adjacent(line, matches[i], matches[i + 1]):
                continue
            key = (words[i].lower(), words[i + 1].lower())
            fixed = _BIGRAM_FIXES.get(key)
            if fixed is not None:
                words[i] = _match_case(words[i], fixed[0])
                words[i + 1] = _match_case(words[i + 1], fixed[1])

    @staticmethod
    def _reassemble(line: str, matches: list[re.Match[str]], words: list[str]) -> str:
        parts: list[str] = []
        cursor = 0
        for match, replacement in zip(matches, words, strict=True):
            parts.append(line[cursor : match.start()])
            parts.append(replacement)
            cursor = match.end()
        parts.append(line[cursor:])
        return "".join(parts)
