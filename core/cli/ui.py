from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.markdown import Markdown

console = Console()

def print_header(title: str):
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", border_style="cyan"))

def print_success(message: str):
    console.print(f"[bold green]✓[/bold green] {message}")

def print_error(message: str):
    console.print(f"[bold red]✗[/bold red] {message}")

def print_info(message: str):
    console.print(f"[bold blue]i[/bold blue] {message}")

def create_progress():
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    )

def create_spinner():
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    )
