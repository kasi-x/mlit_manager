import re
from enum import Enum
from typing import Optional


class JapaneseEra(str, Enum):
    """日本の元号."""

    REIWA = "令和"  # 2019-
    HEISEI = "平成"  # 1989-2019
    SHOWA = "昭和"  # 1926-1989
    TAISHO = "大正"  # 1912-1926
    MEIJI = "明治"  # 1868-1912

    @classmethod
    def find_era(cls, text: str) -> Optional["JapaneseEra"]:
        """文字列から元号を検出."""
        for era in cls:
            if era.value in text:
                return era
        return None


class JapaneseCalendarConverter:
    """和暦と西暦の変換を行うクラス."""

    ERA_START_YEAR = {
        JapaneseEra.REIWA: 2019,
        JapaneseEra.HEISEI: 1989,
        JapaneseEra.SHOWA: 1926,
        JapaneseEra.TAISHO: 1912,
        JapaneseEra.MEIJI: 1868,
    }

    ZENKAKU_DIGITS = "０１２３４５６７８９"
    HANKAKU_DIGITS = "0123456789"
    TRANS_TABLE = str.maketrans(ZENKAKU_DIGITS, HANKAKU_DIGITS)

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """テキストを正規化（全角数字を半角に変換）."""
        text = text.translate(cls.TRANS_TABLE)
        text = text.replace("　", " ").replace("年", "年")
        return text

    @classmethod
    def to_western_year(cls, japanese_year: str) -> int | None:
        """和暦を西暦に変換.

        Args:
            japanese_year: 和暦の文字列 (例: "平成20年", "令和元年", "平成２０年")

        Returns:
            西暦の年数。変換できない場合はNone
        """
        # テキストの正規化
        japanese_year = cls.normalize_text(japanese_year)

        era = JapaneseEra.find_era(japanese_year)
        if not era:
            return None

        # 元年と漢数字の1年、一年も対応
        year_pattern = r"(\d+|元|一|1)年"
        year_match = re.search(year_pattern, japanese_year)
        if not year_match:
            return None

        year_text = year_match.group(1)
        # 元年、一年、1年の場合は1に変換
        era_year = 1 if year_text in ["元", "一", "1"] else int(year_text)

        return cls.ERA_START_YEAR[era] + era_year - 1


if __name__ == "__main__":
    test_years = [
        "平成20年",  # 半角数字
        "平成２０年",  # 全角数字
        "令和元年",  # 元年
        "令和一年",  # 漢数字
        "令和1年",  # 半角数字
        "昭和64年",
        "昭和６４年",  # 全角数字
        "大正3年",
        "大正３年",  # 全角数字
        "明治45年",
        "明治４５年",  # 全角数字
        "明治４５年度",  # 全角数字
    ]

    print("基本的な年の変換:")
    for japanese_year in test_years:
        western_year = JapaneseCalendarConverter.to_western_year(japanese_year)
        print(f"{japanese_year} -> {western_year}年")
