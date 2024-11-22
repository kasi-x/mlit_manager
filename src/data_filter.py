import json
import sys
from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import Self
from urllib.parse import urljoin

import structlog

from src.base_class import FileFormat
from src.base_class import RegionManager
from src.base_class import RegionType
from src.utils.downloader import Downloader
from src.utils.jp_year_converter import JapaneseCalendarConverter

logger = structlog.get_logger(__name__)

jp_converter = JapaneseCalendarConverter()


@dataclass
class GeographicDataset:
    """地理データセットを表現するデータクラス."""

    category: str
    filename: str
    file_size: str
    region: str
    year: int | None
    geodetic_system: str
    file_url: str
    detail_url: str
    local_html: str
    download_path: str
    _format: FileFormat = field(init=False)
    _region_type: RegionType = field(init=False)

    BASE_URL: ClassVar[str] = "https://nlftp.mlit.go.jp/ksj/gml/data/"

    def __post_init__(self):
        self._format = FileFormat.detect_from_filename(self.filename)
        self._region_type = RegionManager.get_region_type(self.region)

    @property
    def format(self) -> FileFormat:
        return self._format

    @property
    def region_type(self) -> RegionType:
        return self._region_type

    @staticmethod
    def read_year(data: dict[str, Any]) -> int | None:
        """年度データの読み取り."""
        for key in ["年度", "年"]:
            if value := data.get(key):
                value = value.split("(")[0].split("（")[0].strip()
                year_i = jp_converter.to_western_year(value)
                if not year_i:
                    try:
                        year_i = int(value.split("年")[0])
                    except ValueError:
                        msg = f"年度情報の変換に失敗: {value}"
                        logger.warning(msg, data=data)
                        return None
                return year_i
        msg = "年度情報が見つかりません"
        raise ValueError(msg)

    @staticmethod
    def read_area(data: dict[str, Any]) -> str:
        """地域データの読み取り."""
        for key in ["地域", "メッシュ番号"]:
            if value := data.get(key):
                return value.split("(")[0].split("（")[0].strip()
        msg = "地域情報が見つかりません"
        raise ValueError(msg)

    @classmethod
    def from_dict(cls, data: dict[str, Any], local_html_path: Path) -> Self:
        """辞書からGeographicDatasetインスタンスを生成."""
        try:
            return cls(
                category=local_html_path.parent.name,
                filename=data["ファイル名"],
                file_size=data["ファイル容量"],
                region=cls.read_area(data),
                year=cls.read_year(data),
                geodetic_system=data.get("測地系", data["説明"]),
                file_url=urljoin(cls.BASE_URL, data["file_path"]),
                local_html=str(local_html_path),
                detail_url="https://nlftp.mlit.go.jp/ksj/gml/datalist/" + local_html_path.name,
                download_path=str(
                    local_html_path.parent.parent.parent
                    / "raw_data"
                    / local_html_path.parent.name
                    / data["ファイル名"],
                ),
            )
        except KeyError as e:
            msg = f"必須キーが存在しません: {e}"
            logger.exception(msg, data=data, local_html_path=local_html_path)
            raise ValueError(msg) from e

    def download(self) -> None:
        """ファイルのダウンロード."""
        downloader = Downloader()
        path = Path(self.download_path)
        if path.exists():
            logger.info("ファイルが既に存在します", path=str(path))
            return None
        return downloader.download(self.file_url, path, FileFormat.BINARY)


@dataclass
class DatasetCollection:
    """地理データセットのコレクション."""

    items: list[GeographicDataset] = field(default_factory=list)

    def download(self):
        for dataset in self.items:
            if not Path(dataset.download_path).exists():
                Path(dataset.download_path).parent.mkdir(parents=True, exist_ok=True)
                dataset.download()

    def filter(self, predicate: Callable[[GeographicDataset], bool]) -> "DatasetCollection":
        """条件に合致するデータセットを抽出."""
        return DatasetCollection(items=[item for item in self.items if predicate(item)])

    def filter_by_format(self, format: FileFormat) -> "DatasetCollection":
        """指定された形式のデータセットを抽出."""
        return self.filter(lambda x: x.format == format)

    def filter_by_region_type(self, region_type: RegionType) -> "DatasetCollection":
        """指定された地域種類のデータセットを抽出."""
        return self.filter(lambda x: x.region_type == region_type)

    def get_by_year(self, year: str) -> "DatasetCollection":
        """指定された年度のデータセットを抽出."""
        return self.filter(lambda x: x.year == year)

    def reduce_data(
        self,
        latest_only: bool = False,
        prefer_formats: list[FileFormat] | FileFormat | None = None,
    ) -> "DatasetCollection":
        """データセットを最適化して返す."""
        if prefer_formats is None:
            prefer_formats = [FileFormat.GEOJSON, FileFormat.SHAPEFILE]
        if not self.items:
            return DatasetCollection()

        # 年度でグループ化
        year_groups = self.group_by_year()

        # 最新年度の抽出
        if latest_only:
            if "前のデータ" in self.items[0].category or "H29国政局推計" in self.items[0].category:
                return DatasetCollection(items=[])

            year_groups = self._get_latest_year_group(year_groups)

        selected_items = []
        for year_items in year_groups.values():
            best_items = self._select_best_datasets(DatasetCollection(items=year_items), prefer_formats)
            selected_items.extend(best_items)

        return DatasetCollection(items=selected_items)

    def _select_best_datasets(
        self,
        collection: "DatasetCollection",
        prefer_formats: list[FileFormat] | FileFormat | None,
    ) -> list[GeographicDataset]:
        """最適なデータセットを選択."""
        without_seibikyoku = collection.filter(lambda x: x.region_type != RegionType.INFRASTRUCTURE)
        filtered = without_seibikyoku if without_seibikyoku.items else collection

        # 全国データの確認
        nationwide = filtered.filter_by_region_type(RegionType.NATIONWIDE)
        if nationwide.items:
            filtered = nationwide

        if prefer_formats and filtered.items:
            for prefer_format in [prefer_formats] if isinstance(prefer_formats, FileFormat) else prefer_formats:
                format_filtered = filtered.filter_by_format(prefer_format)
                if format_filtered.items:
                    filtered = format_filtered
                    break

        # 地域の整理
        if not nationwide.items:
            filtered = self._organize_by_region(filtered)

        return filtered.items

    @staticmethod
    def _organize_by_region(collection: "DatasetCollection") -> "DatasetCollection":
        """地域ごとにデータセットを整理.
        Remove duplicates with the same region on different levels.
        """
        if not collection.items:
            return collection

        region_groups: dict[str, list[GeographicDataset]] = defaultdict(list)
        unclassified: list[GeographicDataset] = []

        for item in collection.items:
            if region := RegionManager.get_region(item.region):
                region_groups[region].append(item)
            else:
                unclassified.append(item)

        organized: list[GeographicDataset] = []
        for region, group in region_groups.items():
            region_level = [d for d in group if d.region == region]
            organized.extend(region_level if region_level else group)
        organized.extend(unclassified)

        return DatasetCollection(items=organized)

    def group_by_year(self) -> dict[int | str, list[GeographicDataset]]:
        """年度でデータセットをグループ化."""
        groups: dict[int | str, list[GeographicDataset]] = defaultdict(list)
        for item in self.items:
            if not item.year:
                groups["no_year"].append(item)
                logger.warning("年度情報なし", dataset=item)
                continue
            groups[item.year].append(item)
        return dict(groups)

    @staticmethod
    def _get_latest_year_group(
        year_groups: dict[int | str, list[GeographicDataset]],
    ) -> dict[int | str, list[GeographicDataset]]:
        """最新年度のグループを取得."""
        try:
            if "no_year" in year_groups:
                msg = "年度情報なしのデータが存在します"
                raise ValueError(msg)

            latest_year: int = max(year_groups.keys())  # pyright: ignore [reportAssignmentType]
            logger.info("最新年度を抽出", year=f"{latest_year}年")
            return {latest_year: year_groups[latest_year]}

        except ValueError as e:
            logger.warning("最新年度の特定に失敗", error=str(e))
            return year_groups

    @classmethod
    def from_dicts(cls, data_list: list[dict[str, Any]], local_html_path: Path) -> "DatasetCollection":
        """辞書のリストからデータセットコレクションを生成."""
        items = []
        errors = []

        for i, data in enumerate(data_list):
            try:
                dataset = GeographicDataset.from_dict(data, local_html_path)
                items.append(dataset)
            except ValueError as e:
                errors.append(f"インデックス {i} でエラー: {e}")

        if errors:
            raise ValueError("\n".join(errors))

        return cls(items=items)

    def merge_with_existing(self, existing_items: list[dict]) -> list[GeographicDataset]:
        """既存のデータと新しいデータをマージします."""
        # 既存のデータをGeographicDatasetオブジェクトに変換
        existing_datasets = []
        for geo_data in existing_items:
            _ = geo_data.pop("_format", None)  # Auto added by the class
            _ = geo_data.pop("_region_type", None)  # Auto added by the class
            dataset = GeographicDataset(**geo_data)
            existing_datasets.append(dataset)

        def get_dataset_key(dataset: GeographicDataset) -> tuple:
            """データセットを一意に識別するキーを生成."""
            return (
                dataset.category,  # カテゴリ
                dataset.filename,  # ファイル名
                dataset.region,  # 地域
                dataset.year,  # 年度
                dataset.geodetic_system,  # 測地系
                str(dataset.format),  # ファイルフォーマット
                str(dataset.region_type),  # 地域タイプ
            )

        # 既存のデータセットのキーを記録
        existing_keys = {get_dataset_key(dataset) for dataset in existing_datasets}

        # 新しいデータを追加（重複を避ける）
        merged_datasets = existing_datasets.copy()
        for new_dataset in self.items:
            new_key = get_dataset_key(new_dataset)
            if new_key not in existing_keys:
                merged_datasets.append(new_dataset)
                existing_keys.add(new_key)
            else:
                logger.debug(
                    "重複データセットをスキップ",
                    category=new_dataset.category,
                    filename=new_dataset.filename,
                    region=new_dataset.region,
                    year=new_dataset.year,
                )

        return merged_datasets

    def save(self, file_path: Path) -> None:
        """データセットコレクションをJSONファイルとして保存する."""
        file_path.parent.mkdir(parents=True, exist_ok=True)

        existing_data = []
        if file_path.exists():
            try:
                with file_path.open("r", encoding="utf-8") as f:
                    existing_data = json.load(f)
                logger.info(
                    "既存のデータファイルを読み込みました",
                    file_path=str(file_path),
                    existing_records=len(existing_data),
                )
            except json.JSONDecodeError as e:
                logger.warning("既存のJSONファイルの読み込みに失敗しました", error=str(e), file_path=str(file_path))
                existing_data = []

        try:
            current_data = []
            for dataset in self.items:
                data_dict = asdict(dataset)
                # format と region_type を文字列に変換
                data_dict["_format"] = str(dataset.format)
                data_dict["_region_type"] = str(dataset.region_type)
                current_data.append(data_dict)

            merged_datasets = self.merge_with_existing(existing_data)

            serializable_data = []
            for dataset in merged_datasets:
                data_dict = asdict(dataset)
                data_dict["_format"] = str(dataset.format)
                data_dict["_region_type"] = str(dataset.region_type)
                serializable_data.append(data_dict)

            with file_path.open("w", encoding="utf-8") as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)

            logger.info(
                "データを保存しました",
                file_path=str(file_path),
                total_records=len(serializable_data),
                new_records=len(serializable_data) - len(existing_data),
            )

        except TypeError as e:
            logger.exception("JSONシリアライズエラー", error=str(e), file_path=str(file_path))
            for i, item in enumerate(serializable_data):
                try:
                    json.dumps(item)
                except TypeError as e:
                    logger.exception("データシリアライズエラー", index=i, error=str(e), data=item)
            raise
        except Exception as e:
            logger.exception("ファイル保存エラー", error=str(e), file_path=str(file_path))
            raise

    @classmethod
    def load(cls, file_path: Path) -> "DatasetCollection":
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            items = []

            for geo_data in data:
                _ = geo_data.pop("_format", None)
                _ = geo_data.pop("_region_type", None)
                dataset = GeographicDataset(**geo_data)
                items.append(dataset)

            return cls(items)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[GeographicDataset]:
        return iter(self.items)

    def __getitem__(self, index: int) -> GeographicDataset:
        return self.items[index]
