from enum import Enum


class FileFormat(Enum):
    """地理データのファイルフォーマット."""

    GEOJSON = "geojson"
    SHAPEFILE = "shapefile"
    OTHER = "other"
    BINARY = "binary"
    GML = "gml"
    HTML = "html"
    UNKNOWN_ZIP = "unknown_zip"

    @classmethod
    def detect_from_filename(cls, filename: str) -> "FileFormat":
        """ファイル名から形式を判定."""
        if filename.lower().endswith(("_geojson.zip", ".geojson")):
            return cls.GEOJSON
        if filename.lower().endswith(("_shp.zip", ".shp")):
            return cls.SHAPEFILE
        if filename.lower().endswith(("_gml.zip", ".gml")):
            return cls.GML
        if filename.lower().endswith(".zip"):
            return cls.UNKNOWN_ZIP
        return cls.OTHER


class RegionType(Enum):
    """地域の種類を表す列挙型."""

    NATIONWIDE = "全国"
    REGIONAL = "地方"
    PREFECTURAL = "都道府県"
    INFRASTRUCTURE = "整備局"
    MESH = "メッシュ"
    UNKNOWN = "不明"


class RegionManager:
    """地域情報を管理するクラス."""

    REGION_MAP = {
        "北海道地方": ["北海道"],
        "東北地方": ["青森", "岩手", "宮城", "秋田", "山形", "福島"],
        "関東地方": ["茨城", "栃木", "群馬", "埼玉", "千葉", "東京", "神奈川"],
        "甲信越・北陸地方": ["新潟", "富山", "石川", "福井", "山梨", "長野"],
        "東海地方": ["岐阜", "静岡", "愛知", "三重"],
        "近畿地方": ["滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山"],
        "中国地方": ["鳥取", "島根", "岡山", "広島", "山口"],
        "四国地方": ["徳島", "香川", "愛媛", "高知"],
        "九州地方": ["福岡", "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島"],
        "沖縄地方": ["沖縄"],
    }

    _prefecture_to_region: dict[str, str] = {
        prefecture: region for region, prefectures in REGION_MAP.items() for prefecture in prefectures
    }

    @classmethod
    def get_region_type(cls, area_name: str) -> RegionType:
        """地域名から種類を判定."""
        if area_name == "全国":
            return RegionType.NATIONWIDE
        if area_name in cls.REGION_MAP:
            return RegionType.REGIONAL
        if area_name in cls._prefecture_to_region:
            return RegionType.PREFECTURAL
        if area_name.endswith("局"):
            return RegionType.INFRASTRUCTURE
        if "メッシュ" in area_name:
            return RegionType.MESH
        return RegionType.UNKNOWN

    @classmethod
    def get_region(cls, area_name: str) -> str | None:
        """地域名から地方名を取得."""
        if area_name in cls.REGION_MAP:
            return area_name
        return cls._prefecture_to_region.get(area_name)
