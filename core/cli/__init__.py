import typer

from .add import add
from .ask import ask
from .init_cmd import init

app = typer.Typer(add_completion=False, help="pm — palimind local RAG")
app.command()(init)
app.command()(ask)
app.command()(add)
