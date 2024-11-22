import sys
from typing import Any

import fire
import structlog

from src.scrayper import ConfigurationError
from src.scrayper import DownloadError
from src.scrayper import ScraypingConfig
from src.scrayper import ScraypingManager
from src.utils.downloader import Downloader
from src.utils.logger_config import configure_logger
from src.web_catalog import CatalogItem
from src.web_process import CatalogProcessor

logger = structlog.get_logger(__name__)

BASE_URL = "https://nlftp.mlit.go.jp/ksj/"
SKIP_CATALOG_TITLE = "都市計画決定情報（ポリゴン）"


class CLIManager:
    """Manages CLI interface and configuration."""

    @staticmethod
    def get_cli_args() -> dict[str, Any]:
        """Get CLI arguments."""

        def cli_interface(
            data_dir: str | None = None,
            mode: str = "actual",
            download_all: bool = False,
            latest_year_only: bool = True,
            prefer_formats: list[str] | str | None = None,
            target_catalogs: list[str] | None = None,
            target_years: list[str] | None = None,
        ) -> dict[str, Any]:
            if prefer_formats is None:
                prefer_formats = ["geojson", "shapefile"]
            return {
                "data_dir": data_dir,
                "mode": mode,
                "download_all": download_all,
                "latest_year_only": latest_year_only,
                "prefer_formats": prefer_formats,
                "target_catalogs": target_catalogs,
                "target_years": target_years,
            }

        return fire.Fire(cli_interface)

    @staticmethod
    def create_config() -> ScraypingConfig:
        """Create configuration from CLI args."""
        is_jupyter = "ipykernel" in sys.modules
        args = {} if is_jupyter else CLIManager.get_cli_args()
        return ScraypingConfig.from_dict(args)


def main() -> None:
    """Main entry point."""
    try:
        configure_logger(10)
        config = CLIManager.create_config()
        logger.info("Configuration loaded", config=vars(config))

        downloader = Downloader()
        sc_manager = ScraypingManager(config, downloader)

        # Setup and initial download
        sc_manager.setup_directories()
        sc_manager.process_catalog_top()

        # Catalog processing
        catalog_manager = sc_manager.initialize_catalog_manager()
        extras = {
            "500mメッシュ別将来推計人口（H30国政局推計）（CSV形式版）": "https://nlftp.mlit.go.jp/ksj/old/datalist/old_KsjTmplt-m1kh30.html",
            "500mメッシュ別将来推計人口（H29国政局推計）（CSV形式版）": "/ksj/old/datalist/gmlold_KsjTmplt-suikei140704.html",
            # "商業統計4次メッシュ": "/ksj/gmlold/datalist/gmlold_KsjTmplt-S02.html",
            # "商業統計3次メッシュ": "/ksj/gmlold/datalist/gmlold_KsjTmplt-S01.html",
            # "工業統計メッシュ": "ksj/gmlold/datalist/gmlold_KsjTmplt-S03.html",
            # "農業センサスメッシュ": "ksj/gmlold/datalist/gmlold_KsjTmplt-S04.html",
        }  # pyright: ignore [reportUndefinedVariable]
        extra_catalogs = [CatalogItem(relative_url, title) for title, relative_url in extras.items()]
        catalog_manager.add_extra_catalogs(extra_catalogs)
        catalog_manager.download_catalogs(sc_manager.paths["catalogs"])

        catalog_processor = CatalogProcessor(catalog_manager, sc_manager.paths, config)
        catalog_processor.process_catalog_files()

        logger.info("Processing completed", summary=sc_manager.result.to_dict().get("summary", {}))

    except (DownloadError, ConfigurationError) as e:
        logger.exception(str(e))
        sys.exit(1)
    except Exception:
        logger.exception("Unexpected error occurred")
        sys.exit(1)


if __name__ == "__main__":
    main()
