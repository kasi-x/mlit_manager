import asyncio
import time
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Final
from typing import Protocol
from urllib.parse import unquote
from urllib.parse import urlparse

import httpx
import structlog
from rich import get_console
from rich.progress import DownloadColumn
from rich.progress import Progress
from rich.progress import TaskID
from rich.progress import TimeRemainingColumn
from rich.progress import TransferSpeedColumn

from src.base_class import FileFormat

type PathLike = Path | str
type Headers = dict[str, str]

DEFAULT_USER_AGENT: Final[str] = "for Signate Competion user kasix"
DEFAULT_ENCODING: Final[str] = "utf-8"
TEMP_SUFFIX: Final[str] = ".tmp"
DEFAULT_FILENAME: Final[str] = "downloaded_file"

# configure_logger()
logger = structlog.get_logger().bind(module="downloader")


class DownloaderError(Exception):
    """ダウンローダーの基本例外."""


class FileExistsError(DownloaderError):
    """ファイルが既に存在する場合の例外."""


class DownloadError(DownloaderError):
    """ダウンロード中のエラー."""


class ProgressProtocol(Protocol):
    def create_progress(self) -> Progress: ...
    def create_task(self, progress: Progress, total: int) -> TaskID: ...
    def update(self, progress: Progress, task_id: TaskID, advance: int) -> None: ...


class ProgressManager:
    def __init__(self) -> None:
        self._console = get_console()

    def create_progress(self) -> Progress:
        return Progress(
            *Progress.get_default_columns(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=self._console,
        )

    def create_task(self, progress: Progress, total: int) -> TaskID:
        return progress.add_task(
            description="[cyan]ダウンロード中...",
            total=total,
            visible=total > 0,
        )

    def update(self, progress: Progress, task_id: TaskID, advance: int) -> None:
        progress.update(task_id, advance=advance)


class FileHandler:
    @staticmethod
    def ensure_directory(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_save_path(url: str, base_path: PathLike) -> Path:
        base_path = Path(base_path)
        if base_path.is_dir():
            filename = unquote(Path(urlparse(url).path).name) or DEFAULT_FILENAME
            return base_path / filename
        return base_path

    @staticmethod
    async def read_file_async(path: PathLike, encoding: str = DEFAULT_ENCODING) -> str:
        log = logger.bind(path=str(path), encoding=encoding)
        try:
            path = Path(path)
            return await asyncio.to_thread(path.read_text, encoding=encoding)
        except FileNotFoundError as e:
            log.exception("file_not_found", error=str(e))
            msg = f"ファイルが見つかりません: {path}"
            raise DownloaderError(msg) from e
        except Exception as e:
            log.exception("file_read_error", error=str(e))
            msg = f"ファイル読み込みエラー: {e}"
            raise DownloaderError(msg) from e


@dataclass
class DownloadConfig:
    """ダウンロードの設定を保持するクラス."""

    chunk_size: int = 8192
    retry_count: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0
    encoding: str = "utf-8"
    user_agent: str = "CityGML Downloader/1.0"
    mock: bool = False
    data_dir: Path | None = None
    download_all: bool = False
    latest_year_only: bool = True
    prefer_formats: list[FileFormat] | FileFormat = field(
        default_factory=lambda: [FileFormat.GEOJSON, FileFormat.SHAPEFILE],
    )
    target_catalogs: list[str] | None = None
    target_years: list[str] | None = None
    target_formats: list[FileFormat] | None = None

    @classmethod
    def from_dict(cls, args: dict[str, Any]) -> "DownloadConfig":
        prefer_format_value = args.get("prefer_format", ["geojson", "shapefile"])
        if isinstance(prefer_format_value, str):
            prefer_format_value = [prefer_format_value]
        prefer_formats = [FileFormat(fmt) if isinstance(fmt, str) else fmt for fmt in prefer_format_value]
        return cls(
            data_dir=Path(args["data_dir"]) if "data_dir" in args else None,
            download_all=args.get("download_all", False),
            latest_year_only=args.get("latest_year_only", True),
            prefer_formats=prefer_formats,
            target_catalogs=args.get("target_catalogs"),
            target_years=args.get("target_years"),
            target_formats=[FileFormat(f) for f in args.get("target_formats", [])]
            if args.get("target_formats")
            else None,
            mock=args.get("mock", False),
        )


class DownloadRecord:
    """ダウンロード記録を保持するクラス."""

    def __init__(self):
        self.downloads: list[dict[str, Any]] = []
        self.processed_files: list[dict[str, Any]] = []
        self.skipped_items: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []

    def add_download(self, url: str, path: Path, file_type: FileFormat) -> None:
        self.downloads.append(
            {"url": url, "path": str(path), "type": str(file_type), "timestamp": datetime.now().isoformat()},
        )

    def add_processed_file(self, action: str, input_path: Path, output_path: Path) -> None:
        self.processed_files.append(
            {
                "action": action,
                "input": str(input_path),
                "output": str(output_path),
                "timestamp": datetime.now().isoformat(),
            },
        )

    def add_skipped_item(self, item_type: str, item_id: str, reason: str) -> None:
        self.skipped_items.append(
            {"type": item_type, "id": item_id, "reason": reason, "timestamp": datetime.now().isoformat()},
        )

    def add_error(self, error_type: str, message: str, details: dict[str, Any]) -> None:
        self.errors.append(
            {"type": error_type, "message": message, "details": details, "timestamp": datetime.now().isoformat()},
        )


class Downloader:
    """ダウンロードを処理するクラス."""

    def __init__(
        self,
        config: DownloadConfig | None = None,
        progress_manager: ProgressProtocol | None = None,
    ) -> None:
        self.config = config or DownloadConfig()
        self.progress_manager = progress_manager or ProgressManager()
        self.file_handler = FileHandler()
        self.record = DownloadRecord()
        self.log = logger.bind(
            chunk_size=self.config.chunk_size,
            retry_count=self.config.retry_count,
            timeout=self.config.timeout,
            mock=self.config.mock,
        )

    def download(
        self,
        url: str,
        save_path: PathLike,
        file_type: FileFormat = FileFormat.BINARY,
    ) -> None:
        log = self.log.bind(url=url, save_path=str(save_path), file_type=file_type.name)

        save_path = self.file_handler.get_save_path(url, save_path)

        if self.config.mock:
            if save_path.exists() and not self.config.download_all:
                log.warning("file_exists")
                self.record.add_skipped_item("file", str(save_path), "File already exists")
                return
            self.record.add_download(url, Path(save_path), file_type)
            log.info("mock_download_recorded")
            return

        if save_path.exists() and not self.config.download_all:
            log.warning("file_exists")
            self.record.add_skipped_item("file", str(save_path), "File already exists")
            return

        self.file_handler.ensure_directory(save_path)
        temp_path = save_path.with_suffix(save_path.suffix + ".tmp")

        for attempt in range(self.config.retry_count):
            try:
                self._perform_download(url, save_path, temp_path, file_type)
                self.record.add_download(url, save_path, file_type)
                log.info("download_completed")
                return
            except httpx.HTTPError as e:
                self._handle_download_error(e, temp_path, url, attempt)
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink()
                log.exception("unexpected_error", error=str(e))
                self.record.add_error("unexpected", str(e), {"url": url, "path": str(save_path)})
                raise

    def get_download_record(self) -> dict[str, Any]:
        """ダウンロード記録を取得."""
        return {
            "downloads": self.record.downloads,
            "processed_files": self.record.processed_files,
            "skipped_items": self.record.skipped_items,
            "errors": self.record.errors,
            "configuration": {
                "mock": self.config.mock,
                "download_all": self.config.download_all,
                "latest_year_only": self.config.latest_year_only,
                "prefer_format": str(self.config.prefer_format),
            },
        }

    def _perform_download(
        self,
        url: str,
        save_path: Path,
        temp_path: Path,
        file_type: FileFormat,
    ) -> None:
        log = self.log.bind(
            url=url,
            save_path=str(save_path),
            temp_path=str(temp_path),
            file_type=file_type.name,
        )

        with httpx.Client(timeout=self.config.timeout) as client:
            if file_type == FileFormat.HTML:
                log.debug("downloading_html")
                self._download_html(client, url, save_path)
            else:
                log.debug("downloading_binary")
                self._download_binary(client, url, temp_path)
                temp_path.rename(save_path)

    def _download_html(
        self,
        client: httpx.Client,
        url: str,
        save_path: Path,
    ) -> None:
        response = client.get(url, headers=self.headers)
        response.raise_for_status()
        save_path.write_text(response.text, encoding=self.config.encoding)

    def _download_binary(
        self,
        client: httpx.Client,
        url: str,
        temp_path: Path,
    ) -> None:
        with client.stream("GET", url, headers=self.headers) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))

            with self.progress_manager.create_progress() as progress:
                task_id = self.progress_manager.create_task(progress, total_size)
                with temp_path.open("wb") as f:
                    for chunk in response.iter_bytes(self.config.chunk_size):
                        f.write(chunk)
                        self.progress_manager.update(progress, task_id, len(chunk))

    def _handle_download_error(
        self,
        error: httpx.HTTPError,
        temp_path: Path,
        url: str,
        attempt: int,
    ) -> None:
        log = self.log.bind(
            url=url,
            attempt=attempt + 1,
            max_attempts=self.config.retry_count,
            error=str(error),
        )

        if temp_path.exists():
            temp_path.unlink()

        if attempt == self.config.retry_count - 1:
            log.error("download_failed_all_retries")
            msg = f"HTTPエラー: {error}, URL: {url}"
            raise DownloadError(msg)

        retry_delay = self.config.retry_delay * (attempt + 1)
        log.warning("retry_download", retry_delay=retry_delay)
        time.sleep(retry_delay)

    @property
    def headers(self) -> Headers:
        return {"User-Agent": self.config.user_agent}
