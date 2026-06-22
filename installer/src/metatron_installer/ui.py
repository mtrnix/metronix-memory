from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def header(text: str) -> None:
    console.print(Panel.fit(text, style="magenta"))


def success(text: str) -> None:
    console.print(f"[green]✓[/green] {text}")


def error(text: str) -> None:
    console.print(f"[red]✗[/red] {text}")


def info(text: str) -> None:
    console.print(f"[cyan]→[/cyan] {text}")


def warning(text: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {text}")


def status_table(rows: list[tuple[str, str]]) -> None:
    table = Table("Service", "Status")
    for name, state in rows:
        table.add_row(name, state)
    console.print(table)
