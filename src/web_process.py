import json
from dataclasses import dataclass
from pathlib import Path

import structlog

from src.data_filter import DatasetCollection
from src.scrayper import ScraypingConfig
from src.scrayper import ScraypingManager
from src.web_catalog import CatalogItem
from src.web_catalog import CatalogManager

logger = structlog.get_logger().bind(module="mlit")


@dataclass
class ProcessingResult:
    """Result of catalog processing."""

    processed_catalogs: list[str]
    skipped_catalogs: list[str]
    errors: list[str]


class CatalogProcessor:
    """Handles catalog data processing and file creation."""

    def __init__(self, manager: CatalogManager, paths: dict[str, Path], config: ScraypingConfig) -> None:
        self.manager = manager
        self.paths = paths
        self.config = config

    def process_catalog_files(self) -> None:
        """Process all catalog files."""
        if not self.config.is_dry_run:
            self.create_raw_catalog_info()
            self.create_reduce_target_json()
            self.download_target_data()

    def create_raw_catalog_info(self) -> None:
        """Create raw catalog information JSON files."""
        for catalog in self.manager.catalogs:
            if catalog.title == ScraypingManager.SKIP_CATALOG_TITLE:
                logger.info("Skipping polygon data catalog")
                continue

            info_path = self.paths["catalogs"] / catalog.title / "file_info.json"
            info_path.parent.mkdir(parents=True, exist_ok=True)

            self._process_catalog_info(catalog, info_path)

    def create_reduce_target_json(self) -> None:
        """Create reduced target JSON files."""
        for catalog in self.manager.catalogs:
            if catalog.title == ScraypingManager.SKIP_CATALOG_TITLE:
                logger.info("Skipping polygon data catalog")
                continue

            self._process_reduced_info(catalog)

    def download_target_data(self) -> None:
        """Download target data files."""
        for catalog in self.manager.catalogs:
            if catalog.title == ScraypingManager.SKIP_CATALOG_TITLE:
                logger.info("Skipping polygon data catalog")
                continue

            reduced_path = self.paths["catalogs"] / catalog.title / "reduced_file_info.json"
            try:
                collection = DatasetCollection.load(reduced_path)

                logger.info(
                    "Starting download",
                    catalog_title=catalog.title,
                    total_items=len(collection.items),
                )

                collection.download()
                logger.info("Download completed", catalog_title=catalog.title)

            except Exception as e:
                logger.exception(
                    "Download error occurred",
                    error=str(e),
                    catalog_title=catalog.title,
                )
                raise

    def _process_catalog_info(self, catalog: CatalogItem, info_path: Path) -> None:
        """Process individual catalog information."""
        existing_collection = self._load_existing_collection(info_path)

        if existing_collection:
            logger.info(
                "Loaded existing data",
                catalog_title=catalog.title,
                items=len(existing_collection.items),
                info_path=info_path,
            )
            return
        try:
            html_path = self.paths["catalogs"] / catalog.title / catalog.html_name
            new_collection = catalog.parse_html(html_path)
            new_collection.save(info_path)

        except Exception as e:
            logger.exception(
                "Error processing catalog data",
                error=str(e),
                catalog_title=catalog.title,
                info_path=info_path,
            )
            raise

    def _process_reduced_info(self, catalog: CatalogItem) -> None:
        """Process reduced information for a catalog."""
        file_info_path = self.paths["catalogs"] / catalog.title / "file_info.json"
        reduced_path = self.paths["catalogs"] / catalog.title / "reduced_file_info.json"
        reduced_path.parent.mkdir(parents=True, exist_ok=True)
        if reduced_path.exists():
            logger.info("Skip generating reduced_file_info", catalog_title=catalog.title)
            return

        try:
            raw_collection = DatasetCollection.load(file_info_path)

            new_reduced = raw_collection.reduce_data(
                self.config.latest_year_only,
                self.config.prefer_formats,
            )
            new_reduced.save(reduced_path)

            logger.info(
                "Saved reduced data",
                catalog_title=catalog.title,
                total_items=len(new_reduced.items),
            )

        except Exception as e:
            logger.exception(
                "Error processing reduced data",
                error=str(e),
                catalog_title=catalog.title,
            )
            raise

    @staticmethod
    def _load_existing_collection(path: Path) -> DatasetCollection | None:
        """Load existing dataset collection if available."""
        if not path.exists():
            return None

        try:
            collection = DatasetCollection.load(path)
            logger.info(
                "Loaded existing data",
                path=str(path),
                items=len(collection.items),
            )
            return collection
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "Failed to load existing data",
                error=str(e),
                path=str(path),
            )
            return None
