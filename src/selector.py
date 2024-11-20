from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Optional

from rich.box import ROUNDED
from rich.console import Console
from rich.emoji import Emoji
from rich.layout import Layout
from rich.panel import Panel
from rich.prompt import Prompt
from rich.style import Style
from rich.table import Table
from rich.text import Text


@dataclass
class DataStatus:
    """データの保持状況を管理するクラス."""

    name: bool = False
    catalog: bool = False
    selector: bool = False
    metadata: bool = False
    raw_data: bool = False

    def any_data_exists(self) -> bool:
        """いずれかのデータが存在するかチェック."""
        return any([self.name, self.catalog, self.selector, self.metadata, self.raw_data])


class CatalogSelector:
    """カタログ選択システム."""

    def __init__(self, catalog_names: list[str], data_status: dict[str, DataStatus]) -> None:
        self.catalog_names = catalog_names
        self.data_status = data_status
        self.console = Console()

    def create_header(self, title: str) -> Panel:
        """ヘッダーパネルを作成."""
        return Panel(Text(title, justify="center", style="bold blue"), box=ROUNDED, style="blue")

    def get_status_symbol(self, status: bool) -> str:
        """状態に応じたシンボルを返す."""
        return "✓" if status else "✗"

    def get_status_style(self, status: bool) -> str:
        """状態に応じたスタイルを返す."""
        return "bold green" if status else "bold red"

    def create_catalog_table(self) -> Table:
        """拡張されたカタログ一覧テーブルを作成."""
        table = Table(
            box=ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            pad_edge=False,
            title="利用可能なカタログ一覧",
            title_style="bold cyan",
            show_edge=True,
        )

        # カラムの定義
        table.add_column("No.", justify="right", style="cyan", width=6)
        table.add_column("カタログ名", style="green", width=30)
        table.add_column("名前", justify="center", style="yellow", width=8)
        table.add_column("カタログ", justify="center", style="yellow", width=8)
        table.add_column("セレクター", justify="center", style="yellow", width=10)
        table.add_column("管理情報", justify="center", style="yellow", width=10)
        table.add_column("生データ", justify="center", style="yellow", width=8)
        table.add_column("選択方法", style="yellow", width=20)

        # データの追加
        for idx, name in enumerate(self.catalog_names, start=1):
            status = self.data_status.get(name, DataStatus())
            table.add_row(
                str(idx),
                name,
                Text(self.get_status_symbol(status.name), style=self.get_status_style(status.name)),
                Text(self.get_status_symbol(status.catalog), style=self.get_status_style(status.catalog)),
                Text(self.get_status_symbol(status.selector), style=self.get_status_style(status.selector)),
                Text(self.get_status_symbol(status.metadata), style=self.get_status_style(status.metadata)),
                Text(self.get_status_symbol(status.raw_data), style=self.get_status_style(status.raw_data)),
                "↓ 番号を入力" if idx == 1 else "",
            )

        return table

    def create_result_table(self, selected_indices: list[int]) -> Table:
        """選択結果テーブルを作成."""
        table = Table(
            box=ROUNDED,
            show_header=True,
            header_style="bold magenta",
            border_style="magenta",
            pad_edge=False,
            title="選択されたカタログ",
            title_style="bold magenta",
        )

        table.add_column("インデックス", justify="right", style="cyan", width=12)
        table.add_column("カタログ名", style="green", width=30)
        table.add_column("ローカルデータ状況", style="yellow")

        for idx in selected_indices:
            name = self.catalog_names[idx]
            status = self.data_status.get(name, DataStatus())
            status_text = []

            if status.any_data_exists():
                if status.name:
                    status_text.append("名前")
                if status.catalog:
                    status_text.append("カタログ")
                if status.selector:
                    status_text.append("セレクター")
                if status.metadata:
                    status_text.append("管理情報")
                if status.raw_data:
                    status_text.append("生データ")
                status_str = f"[green]保持: {', '.join(status_text)}[/green]"
            else:
                status_str = "[red]データなし[/red]"

            table.add_row(str(idx), name, status_str)

        return table

    def create_help_panel(self) -> Panel:
        """ヘルプパネルを作成."""
        help_text = Text.assemble(
            ("使い方:\n", "bold yellow"),
            ("• 単一選択: ", "bold cyan"),
            ("数字を入力 (例: 3)\n", "white"),
            ("• 複数選択: ", "bold cyan"),
            ("カンマ区切りで入力 (例: 1,3,4)\n", "white"),
            ("• キャンセル: ", "bold cyan"),
            ("'q' または 'quit' を入力\n", "white"),
            ("\n凡例:\n", "bold yellow"),
            ("✓ ", "bold green"),
            ("存在するデータ\n", "white"),
            ("✗ ", "bold red"),
            ("存在しないデータ", "white"),
        )
        return Panel(help_text, title="ヘルプ", border_style="yellow", box=ROUNDED, padding=(1, 2))

    def select_target_data(self) -> list[int] | None:
        """対話的にデータを選択するUI."""
        self.console.print(self.create_header("カタログ選択システム"))
        self.console.print()
        self.console.print(self.create_catalog_table())
        self.console.print(self.create_help_panel())

        while True:
            selection = Prompt.ask("\nカタログ番号を入力してください", default="", show_default=False)

            if selection.lower() in ["q", "quit"]:
                self.console.print("[yellow]選択をキャンセルしました[/yellow]")
                return None

            try:
                selected_numbers = [int(num.strip()) - 1 for num in selection.split(",")]

                if all(0 <= num < len(self.catalog_names) for num in selected_numbers):
                    selected_indices = sorted(set(selected_numbers))
                    self.console.print(self.create_result_table(selected_indices))

                    confirm = Prompt.ask("\n選択を確定しますか?", choices=["y", "n"], default="y")
                    if confirm.lower() == "y":
                        return selected_indices

                    self.console.print("[yellow]選択をやり直します[/yellow]")
                    self.console.print()
                    self.console.print(self.create_catalog_table())
                    self.console.print(self.create_help_panel())
                else:
                    self.console.print(f"[red]エラー: 1から{len(self.catalog_names)}までの数字を入力してください[/red]")
            except ValueError:
                self.console.print("[red]エラー: 正しい形式で入力してください (例: 1,2,4)[/red]")


if __name__ == "__main__":
    sample_catalogs = [
        "データセットA: 顧客情報",
        "データセットB: 売上データ",
        "データセットC: 商品マスタ",
        "データセットD: 在庫情報",
        "データセットE: アクセスログ",
    ]

    sample_data_status = {
        "データセットA: 顧客情報": DataStatus(name=True, catalog=True, selector=False, metadata=True, raw_data=False),
        "データセットB: 売上データ": DataStatus(name=True, catalog=True, selector=True, metadata=True, raw_data=True),
        "データセットC: 商品マスタ": DataStatus(
            name=False, catalog=False, selector=False, metadata=False, raw_data=False
        ),
        "データセットD: 在庫情報": DataStatus(name=True, catalog=False, selector=False, metadata=False, raw_data=False),
        "データセットE: アクセスログ": DataStatus(
            name=True, catalog=True, selector=True, metadata=False, raw_data=False
        ),
    }

    selector = CatalogSelector(sample_catalogs, sample_data_status)
    selected_indices = selector.select_target_data()

    if selected_indices is not None:
        console = Console()
        console.print("\n[green]処理を続行します...[/green]")
        console.print(f"選択されたインデックス: {selected_indices}")
