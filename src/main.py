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
            prefer_format: str = "geojson",
            target_catalogs: list[str] | None = None,
            target_years: list[str] | None = None,
        ) -> dict[str, Any]:
            return {
                "data_dir": data_dir,
                "mode": mode,
                "download_all": download_all,
                "latest_year_only": latest_year_only,
                "prefer_format": prefer_format,
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
        configure_logger()
        config = CLIManager.create_config()
        logger.info("Configuration loaded", config=vars(config))

        downloader = Downloader()
        manager = ScraypingManager(config, downloader)

        # Setup and initial download
        manager.setup_directories()
        manager.process_catalog_top()

        # Catalog processing
        catalog_manager = manager.initialize_catalog_manager()
        catalog_manager.download_catalogs(manager.paths["catalogs"])

        processor = CatalogProcessor(catalog_manager, manager.paths, config)
        processor.process_catalog_files()

        logger.info("Processing completed", summary=manager.result.to_dict().get("summary", {}))

    except (DownloadError, ConfigurationError) as e:
        logger.exception(str(e))
        sys.exit(1)
    except Exception:
        logger.exception("Unexpected error occurred")
        sys.exit(1)


if __name__ == "__main__":
    main()
