"""Phase 2 CLI commands — Part 2: newsletters, spam, stats.

Appended to the same Typer app via cli_p2.py import chain.
Import this module AFTER cli_p2.py to register all commands.
"""
from __future__ import annotations

from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from core.cli.ui import console, print_error, print_header, print_info, print_success
from core.email.cli import app, _fmt_date, _fmt_size
from core.email.exceptions import EmailError


# ---------------------------------------------------------------------------
# pm email newsletters
# ---------------------------------------------------------------------------

@app.command("newsletters")
def newsletters(
    scan: bool = typer.Option(False, "--scan", "-s", help="Scan inbox for newsletters first"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max newsletters to show"),
):
    """Show emails detected as newsletters or marketing mailings."""
    from core.email.api_p2 import get_newsletters, scan_newsletters

    print_header("Newsletters")

    if scan:
        print_info("Scanning for newsletters…")
        try:
            marked = scan_newsletters(limit=200)
            print_info(f"Marked {marked} email(s) as newsletters.")
        except EmailError as exc:
            print_error(str(exc))
            raise typer.Exit(1)

    try:
        items = get_newsletters()
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not items:
        print_info("No newsletters detected. Run with --scan to analyse your inbox.")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", width=5, justify="right", style="dim")
    table.add_column("Conf", width=5, justify="right")
    table.add_column("From", max_width=28)
    table.add_column("Subject", max_width=45)
    table.add_column("Date", width=8, justify="right")
    table.add_column("●", width=2)

    for item in items[:limit]:
        conf = item.get("newsletter_conf", 0)
        unread = "[cyan]●[/cyan]" if not item.get("is_read") else " "
        table.add_row(
            str(item["id"]),
            f"{conf}%",
            (item.get("sender_name") or item["sender"])[:28],
            item["subject"][:45],
            _fmt_date(item["date"]),
            unread,
        )
    console.print(table)
    console.print(f"[dim]{len(items)} newsletter(s) detected. Use 'pm email read <ID>' to view.[/dim]")


# ---------------------------------------------------------------------------
# pm email spam  (dashboard)
# ---------------------------------------------------------------------------

_spam_app = typer.Typer(name="spam", help="Spam management — detect, review, whitelist, blacklist.")


@app.command("spam")
def spam_dashboard():
    """Show the spam dashboard: counts, top senders, recent detections."""
    from core.email.api_p2 import get_spam_dashboard, get_spam_list

    print_header("Spam Dashboard")

    try:
        stats = get_spam_dashboard()
        recent = get_spam_list(limit=5)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    # Stats panel
    info_lines = [
        f"[bold red]Spam:[/bold red]           {stats['spam_count']}",
        f"[bold yellow]Suspicious:[/bold yellow]     {stats['suspicious_count']}",
        f"[bold cyan]Unreviewed:[/bold cyan]     {stats['unreviewed_count']}",
    ]
    console.print(Panel("\n".join(info_lines), title="[bold]Spam Statistics[/bold]", border_style="red"))

    # Top spam senders
    if stats["top_spam_senders"]:
        console.print()
        console.print("[bold]Top Spam Senders[/bold]")
        for sender, count in stats["top_spam_senders"]:
            console.print(f"  [red]•[/red] {sender} [dim]({count})[/dim]")

    # Recent detections
    if recent:
        console.print()
        console.print("[bold]Recent Detections[/bold]")
        t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", expand=True)
        t.add_column("#", width=5, justify="right")
        t.add_column("Status", width=10)
        t.add_column("Conf", width=5, justify="right")
        t.add_column("From", max_width=25)
        t.add_column("Subject", max_width=35)
        for item in recent:
            status = item.get("spam_status", "safe")
            color = "red" if status == "spam" else "yellow"
            t.add_row(
                str(item["id"]),
                f"[{color}]{status}[/{color}]",
                str(item.get("spam_confidence", 0)) + "%",
                (item.get("sender_name") or item["sender"])[:25],
                item["subject"][:35],
            )
        console.print(t)

    console.print()
    console.print("[dim]Commands: pm email spam list | pm email spam review | pm email spam whitelist/blacklist <addr>[/dim]")


@app.command("spam-list")
def spam_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter: spam, suspicious"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
):
    """List spam and suspicious emails."""
    from core.email.api_p2 import get_spam_list

    print_header(f"Spam List{' — ' + status if status else ''}")
    try:
        items = get_spam_list(status=status)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not items:
        print_info("No spam/suspicious emails found.")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", width=5, justify="right", style="dim")
    table.add_column("Status", width=10)
    table.add_column("Conf", width=5, justify="right")
    table.add_column("From", max_width=25)
    table.add_column("Subject", max_width=35)
    table.add_column("Reason", max_width=25)
    table.add_column("Date", width=8, justify="right")

    for item in items[:limit]:
        s = item.get("spam_status", "safe")
        color = "red" if s == "spam" else "yellow"
        table.add_row(
            str(item["id"]),
            f"[{color}]{s}[/{color}]",
            str(item.get("spam_confidence", 0)) + "%",
            (item.get("sender_name") or item["sender"])[:25],
            item["subject"][:35],
            item.get("spam_reason", "")[:25],
            _fmt_date(item["date"]),
        )
    console.print(table)
    console.print(f"[dim]{len(items)} email(s) detected.[/dim]")


@app.command("spam-review")
def spam_review(limit: int = typer.Option(10, "--limit", "-n", help="Max to review")):
    """Interactively review borderline suspicious emails."""
    from core.email.api_p2 import get_spam_for_review, mark_spam_reviewed

    print_header("Spam Review")
    try:
        items = get_spam_for_review()
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not items:
        print_success("No emails pending review.")
        return

    print_info(f"{len(items)} email(s) need review. For each, press [s]pam, [o]k, or [skip].")
    console.print()

    reviewed = 0
    for item in items[:limit]:
        console.print(Rule(style="dim"))
        console.print(f"[bold]#{item['id']}[/bold] [cyan]{item.get('sender_name') or item['sender']}[/cyan]")
        console.print(f"  Subject:    {item['subject']}")
        console.print(f"  Confidence: {item.get('spam_confidence', 0)}% — {item.get('spam_reason', '')}")
        console.print(f"  Date:       {_fmt_date(item['date'])}")
        console.print()
        console.print("  [bold][s][/bold]=spam  [bold][o][/bold]=ok/safe  [bold][Enter][/bold]=skip: ", end="")

        try:
            choice = input().strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            break

        if choice == "s":
            mark_spam_reviewed(item["id"], is_spam=True)
            print_info(f"  Marked #{item['id']} as spam.")
            reviewed += 1
        elif choice == "o":
            mark_spam_reviewed(item["id"], is_spam=False)
            print_success(f"  Marked #{item['id']} as safe.")
            reviewed += 1
        else:
            console.print(f"  [dim]Skipped #{item['id']}.[/dim]")

    console.print(Rule(style="dim"))
    print_success(f"Reviewed {reviewed} email(s).")


@app.command("spam-whitelist")
def spam_whitelist(
    sender: str = typer.Argument(..., help="Sender email address to whitelist"),
):
    """Add a sender to the spam whitelist (always safe)."""
    from core.email.api_p2 import add_spam_whitelist

    try:
        add_spam_whitelist(sender)
        print_success(f"{sender} added to whitelist.")
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("spam-blacklist")
def spam_blacklist(
    sender: str = typer.Argument(..., help="Sender email address to blacklist"),
):
    """Add a sender to the spam blacklist (always flagged)."""
    from core.email.api_p2 import add_spam_blacklist

    try:
        add_spam_blacklist(sender)
        print_success(f"{sender} added to blacklist.")
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# pm email stats  (enhanced)
# ---------------------------------------------------------------------------

@app.command("stats")
def stats():
    """Show enhanced email statistics (Phase 1 + Phase 2 combined)."""
    from core.email.api_p2 import get_enhanced_stats

    print_header("Email Statistics")
    try:
        s = get_enhanced_stats()
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    # Main stats table
    t = Table(box=box.ROUNDED, show_header=False, expand=False)
    t.add_column("Metric", style="bold", width=28)
    t.add_column("Value", justify="right", width=14)

    t.add_row("Total Emails", str(s["total"]))
    t.add_row("Unread", f"[bold cyan]{s['unread']}[/bold cyan]")
    t.add_row("Sent", str(s["sent"]))
    t.add_row("With Attachments", str(s["has_attachments"]))
    t.add_row("", "")
    t.add_row("Needs Reply", f"[bold yellow]{s['needs_reply_count']}[/bold yellow]")
    t.add_row("Active Reminders", str(s["reminder_count"]))
    t.add_row("Newsletters", str(s["newsletter_count"]))
    t.add_row("", "")
    t.add_row("Spam Detected", f"[red]{s['spam_count']}[/red]")
    t.add_row("Suspicious", f"[yellow]{s['suspicious_count']}[/yellow]")
    t.add_row("", "")
    t.add_row("Storage Used", _fmt_size(s["storage_bytes"]))
    last_sync = _fmt_date(s["last_sync_at"]) if s.get("last_sync_at") else "[dim]Never[/dim]"
    t.add_row("Last Sync", last_sync)

    console.print(t)

    if s["top_contacts"]:
        console.print()
        console.print("[bold]Top Contacts[/bold]")
        for sender, name, total in s["top_contacts"]:
            label = name or sender
            console.print(f"  [cyan]{label[:30]}[/cyan]  [dim]{total} email(s)[/dim]")
