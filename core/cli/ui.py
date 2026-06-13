from pathlib import Path
from rich.console import Console
from rich.rule import Rule
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich import box

# Console with no width argument
console = Console()

THEMES = {
    "teal":   {"rich": "bright_cyan",    "hex": "#2dd4a0"},
    "purple": {"rich": "bright_magenta", "hex": "#a78bfa"},
    "amber":  {"rich": "bright_yellow",  "hex": "#f59e0b"},
    "blue":   {"rich": "bright_blue",    "hex": "#60a5fa"},
    "coral":  {"rich": "bright_red",     "hex": "#f97316"},
}

def get_theme(config: dict) -> dict:
    name = config.get("theme", "teal")
    return THEMES.get(name, THEMES["teal"])

def get_version() -> str:
    try:
        from core import __version__
        return __version__
    except ImportError:
        return "2.0.0"

def print_startup_banner(config: dict = None):
    if config is None: config = {}
    theme = get_theme(config)
    color = theme["rich"]
    version = get_version()
    # Simple ASCII wordmark
    banner = f"""[bold {color}]
██████╗  █████╗ ██╗     ██╗███╗   ███╗██╗███╗   ██╗██████╗
██╔══██╗██╔══██╗██║     ██║████╗ ████║██║████╗  ██║██╔══██╗
██████╔╝███████║██║     ██║██╔████╔██║██║██╔██╗ ██║██║  ██║
██╔═══╝ ██╔══██║██║     ██║██║╚██╔╝██║██║██║╚██╗██║██║  ██║
██║     ██║  ██║███████╗██║██║ ╚═╝ ██║██║██║ ╚████║██████╔╝
╚═╝     ╚═╝  ╚═╝╚══════╝╚═╝╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═════╝
[/bold {color}]
[dim]Private • Local-First • AI Workspace[/dim]
[dim]Version {version}[/dim]
"""
    console.print(banner, highlight=False)
    console.print(Rule(style="dim"))
    console.print()

def print_header(title: str, config: dict = None):
    if config is None: config = {}
    theme = get_theme(config)
    console.print(Rule(title, style=theme["rich"]))
    console.print()

def print_success(message: str):
    console.print(f"[bold green]✓[/bold green] {message}")

def print_error(message: str):
    console.print(f"[bold red]✗[/bold red] {message}")

def print_info(message: str):
    console.print(f"[bold blue]ℹ[/bold blue] {message}")

def print_warning(message: str):
    console.print(f"[bold yellow]⚠[/bold yellow] {message}")

def create_progress():
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True
    )

def create_spinner(description: str = ""):
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    )

def print_sources(sources: list[str], config: dict = None):
    if config is None: config = {}
    theme = get_theme(config)
    color = theme["rich"]
    console.print("\n[dim]Referenced Files[/dim]")
    for source in sources:
        basename = Path(source).name
        console.print(f"  [{color}]▸[/{color}] {basename}")
    console.print()

def print_summary_table(rows: list[tuple[str, str]]):
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Label", style="bold")
    table.add_column("Value")
    for label, value in rows:
        table.add_row(label, str(value))
    console.print(table)

def print_chat_user_prefix():
    console.print("[bold cyan]❯ You[/bold cyan]   ", end="")

def print_chat_ai_prefix(config: dict = None):
    if config is None: config = {}
    theme = get_theme(config)
    color = theme["rich"]
    console.print(f"[bold {color}]◆ Palimind[/bold {color}]   ", end="")

def print_footer(message: str, config: dict = None):
    if config is None: config = {}
    theme = get_theme(config)
    console.print()
    console.print(Rule(style="dim"))
    console.print(f"[dim italic center]{message}[/dim italic center]", justify="center")
    console.print(Rule(style="dim"))
    console.print()
