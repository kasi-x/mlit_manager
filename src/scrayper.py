import os
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

from src.base_class import FileFormat
from src.utils.downloader import Downloader
from src.web_catalog import CatalogItem
from src.web_catalog import CatalogManager

logger = structlog.get_logger().bind(module="scrayper")


class DownloadError(Exception):
    """ダウンロード関連のエラー."""


class ConfigurationError(Exception):
    """設定関連のエラー."""


class DownloadMode(str, Enum):
    """ダウンロードモードを表す列挙型."""

    ACTUAL = "actual"
    DRY_RUN = "dry_run"


@dataclass
class ScraypingConfig:
    """ダウンロードの設定を保持するクラス."""

    data_dir: Path
    mode: DownloadMode = DownloadMode.ACTUAL
    download_all: bool = False
    latest_year_only: bool = True
    prefer_formats: list[FileFormat] | FileFormat = field(
        default_factory=lambda: [FileFormat.GEOJSON, FileFormat.SHAPEFILE],
    )
    target_catalogs: list[str] | None = None
    target_years: list[str] | None = None
    chunk_size: int = 8192
    retry_count: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0
    encoding: str = "utf-8"
    user_agent: str = "CityGML Downloader/1.0"

    @property
    def is_dry_run(self) -> bool:
        return self.mode == DownloadMode.DRY_RUN

    @classmethod
    def from_dict(cls, args: dict[str, Any]) -> "ScraypingConfig":
        """辞書から設定を生成."""
        data_dir = args.get("data_dir")
        if not data_dir:
            data_dir = cls._get_external_data_dir()

        prefer_formats = args.get("prefer_format", ["geojson", "shapefile"])
        try:
            # condition check if str
            if isinstance(prefer_formats, str):
                prefer_formats = FileFormat(prefer_formats)
            else:
                prefer_formats = [FileFormat(format_str) for format_str in prefer_formats]
        except ValueError:
            prefer_formats = FileFormat.OTHER

        return cls(
            data_dir=Path(data_dir),
            mode=DownloadMode(args.get("mode", "actual")),
            download_all=args.get("download_all", False),
            latest_year_only=args.get("latest_year_only", True),
            prefer_formats=prefer_formats,
            target_catalogs=args.get("target_catalogs"),
            target_years=args.get("target_years"),
        )

    @staticmethod
    def _get_external_data_dir() -> Path:
        data_external_path = os.environ.get("DATA_DIR")
        if not data_external_path:
            msg = "DATA_ environment variable is not set"
            raise ConfigurationError(msg)
        return Path(data_external_path)


class ScraypingResult:
    """ダウンロード結果を保持するクラス."""

    def __init__(self):
        self.downloads: list[dict[str, Any]] = []
        self.directories_to_create: list[str] = []
        self.files_to_process: list[dict[str, Any]] = []
        self.skipped_items: list[dict[str, Any]] = []

    def add_directory(self, directory: Path) -> None:
        """作成するディレクトリを追加."""
        self.directories_to_create.append(str(directory))

    def add_download(
        self,
        download_type: str,
        url: str,
        path: Path,
        file_type: str,
    ) -> None:
        """ダウンロード情報を追加."""
        self.downloads.append(
            {
                "type": download_type,
                "url": url,
                "path": str(path),
                "file_type": file_type,
            },
        )

    def add_file_to_process(
        self,
        action: str,
        input_path: Path,
        output_path: Path,
        catalog: str,
    ) -> None:
        """処理するファイル情報を追加."""
        self.files_to_process.append(
            {
                "action": action,
                "input": str(input_path),
                "output": str(output_path),
                "catalog": catalog,
            },
        )

    def add_skipped_item(self, item_type: str, title: str, reason: str) -> None:
        """スキップしたアイテムを追加."""
        self.skipped_items.append({"type": item_type, "title": title, "reason": reason})

    def to_dict(self) -> dict[str, Any]:
        """結果を辞書形式で取得."""
        return {
            "downloads": self.downloads,
            "directories_to_create": self.directories_to_create,
            "files_to_process": self.files_to_process,
            "skipped_items": self.skipped_items,
            "summary": self._create_summary(),
        }

    def _create_summary(self) -> dict[str, int]:
        """サマリー情報を生成."""
        return {
            "total_downloads": len(self.downloads),
            "total_directories": len(self.directories_to_create),
            "total_files_to_process": len(self.files_to_process),
            "total_skipped": len(self.skipped_items),
        }


class ScraypingManager:
    """Manages all download operations and catalog processing."""

    BASE_URL = "https://nlftp.mlit.go.jp/ksj/"
    SKIP_CATALOG_TITLE = "都市計画決定情報（ポリゴン）"

    def __init__(self, config: ScraypingConfig, downloader: Downloader) -> None:
        self.config = config
        self.downloader = downloader
        self.paths = self._setup_paths(config.data_dir)
        self.result = ScraypingResult()

    @staticmethod
    def _setup_paths(data_dir: Path) -> dict[str, Path]:
        """Set up path information."""
        return {
            "catalogs": data_dir / "catalogs",
            "catalog_top": data_dir / "catalog_top" / "index.html",
            "data_dir": data_dir / "raw_data",
        }

    def setup_directories(self) -> None:
        """Create necessary directories."""
        self.result.add_directory(self.paths["catalogs"])
        self.result.add_directory(self.paths["catalog_top"])

    def process_catalog_top(self) -> None:
        """Process catalog top page."""
        if not self.paths["catalog_top"].exists():
            if self.config.is_dry_run:
                self.result.add_download(
                    "catalog_top",
                    self.BASE_URL,
                    self.paths["catalog_top"],
                    "html",
                )
            else:
                self.paths["catalog_top"].parent.mkdir(parents=True, exist_ok=True)
                self.downloader.download(self.BASE_URL, self.paths["catalog_top"], FileFormat.HTML)

    def initialize_catalog_manager(self) -> CatalogManager:
        """Initialize catalog manager."""
        if self.config.is_dry_run:
            return self._get_sample_catalog_manager()
        return CatalogManager(self.paths["catalog_top"].read_text())

    @staticmethod
    def _get_sample_catalog_manager() -> CatalogManager:
        """Generate sample catalog manager."""
        sample_catalogs = [
            CatalogItem("/ksj/gml/datalist/KsjTmplt-N03-v3_0.html", "行政区域データ"),
            CatalogItem("/ksj/gml/datalist/KsjTmplt-P12-v2_2.html", ScraypingManager.SKIP_CATALOG_TITLE),
            CatalogItem("/ksj/gml/datalist/KsjTmplt-A16-v2_3.html", "水系データ"),
        ]
        # TODO
        return CatalogManager(sample_catalogs)  # pyright: ignore [reportArgumentType]
