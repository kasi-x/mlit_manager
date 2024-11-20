import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import structlog
from bs4 import BeautifulSoup
from bs4 import Tag

from src.base_class import FileFormat
from src.data_filter import DatasetCollection
from src.utils.downloader import Downloader

logger = structlog.get_logger().bind(module="mlit")


@dataclass
class CatalogItem:
    """国土数値情報カタログの項目を表すクラス."""

    BASE_URL = "https://nlftp.mlit.go.jp/ksj/"
    relative_url: str
    title: str
    url: str = field(init=False)

    def __post_init__(self):
        self.url = urljoin(self.BASE_URL, self.relative_url)

    @property
    def html_name(self) -> str:
        return self.url.split("/")[-1]

    def save_html(self, target_path: Path) -> None:
        """HTMLをダウンロードして保存."""
        if target_path.exists():
            logger.info("Catalog already exists", target_path=str(target_path))
            return

        target_path.parent.mkdir(parents=True, exist_ok=True)
        Downloader().download(self.url, target_path, FileFormat.HTML)

    def _parse_table(self, table: Tag, html_path: Path) -> DatasetCollection:
        """テーブルからデータを抽出."""
        headers = self._get_headers(table)
        rows_data = []

        for row in table.find_all("tr"):
            if row_data := self._parse_row(row, headers):
                rows_data.append(row_data)

        return DatasetCollection.from_dicts(rows_data, html_path)

    def parse_html(self, html_path: Path) -> DatasetCollection:
        """HTMLを解析して地理データセット情報を抽出."""
        try:
            html_content = html_path.read_text()
        except (FileNotFoundError, OSError) as e:
            msg = f"HTMLファイルの読み込みに失敗: {e}"
            raise type(e)(msg)

        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.select_one("main div table.mb30.responsive-table")
        if not table:
            msg = "地理データテーブルが見つかりませんでした"
            raise ValueError(msg)

        return self._parse_table(table, html_path)

    def _get_headers(self, table: Tag) -> list[str]:
        """テーブルヘッダーを取得."""
        header_row = table.find("tr")
        if not header_row:
            msg = "テーブルヘッダーが見つかりません"
            raise ValueError(msg)
        return [th.text.strip() for th in header_row.find_all("th")]  # pyright: ignore [reportAttributeAccessIssue]

    def _parse_row(self, row: Tag, headers: list[str]) -> dict[str, Any]:
        """行データを解析."""
        if row.find("th"):
            return {}

        cells = row.find_all("td")
        row_data = {}

        for header, cell in zip(headers, cells, strict=False):
            if header == "ダウンロード":
                continue
            row_data[header] = cell.text.strip()
            if header == "region" and cell.get("id"):
                row_data["region_id"] = cell["id"]

        file_path = self._extract_file_path(cells)
        if file_path:
            row_data["file_path"] = file_path
            return row_data
        return {}

    def _extract_file_path(self, cells: list[Tag]) -> str:
        """セルからファイルパスを抽出."""
        for cell in cells:
            if (link := cell.find("a")) and (onclick := link.get("onclick")):  # pyright: ignore [reportAttributeAccessIssue]
                if (args := re.findall(r"\'([^\']+)\'", onclick)) and len(args) >= 3:  # pyright: ignore
                    return args[2]
        return ""


class CatalogManager:
    """カタログの管理を行うクラス."""

    def __init__(self, html_content: str) -> None:
        self.catalogs: list[CatalogItem] = self._parse_catalogs(html_content)

    def _parse_catalogs(self, html_content: str) -> list[CatalogItem]:
        """HTMLからカタログ一覧を抽出."""
        pattern = r'<li class="collection-item">\s*<a href="([^"]+)">\s*(.+?)\s*</a>'
        return [CatalogItem(*match) for match in re.findall(pattern, html_content)]

    def download_catalogs(self, output_dir: Path, download_all: bool = True) -> None:
        """カタログをダウンロード."""
        target_catalogs = self.catalogs if download_all else self._select_catalogs()

        for catalog in target_catalogs:
            catalog_path = output_dir / catalog.title / catalog.html_name
            catalog.save_html(catalog_path)

            if catalog.title == "都市計画決定情報（ポリゴン）":
                logger.info("都市計画決定情報（ポリゴン）はスキップします")
                continue

            info_path = output_dir / catalog.title / "file_info.json"
            if not info_path.exists():
                dataset = catalog.parse_html(catalog_path)
                dataset.save(info_path)

    def _select_catalogs(self) -> list[CatalogItem]:
        """ダウンロード対象のカタログを選択（カスタマイズ可能）."""
        return self.catalogs
