"""Phase 2 CLI commands for the PaliMind email module.

All new commands are registered on the existing `app` Typer instance
from core/email/cli.py so Phase 1 commands are never touched.
"""
from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from core.cli.ui import console, print_error, print_header, print_info, print_success
from core.email.cli import app, _fmt_date, _fmt_date_full, _prompt_confirmation, _open_editor
from core.email.exceptions import EmailError


# ---------------------------------------------------------------------------
# pm email watch
# ---------------------------------------------------------------------------

@app.command("watch")
def watch(
    interval: int = typer.Option(300, "--interval", "-i", help="Poll interval in seconds"),
    folder: str = typer.Option("INBOX", "--folder", "-f", help="IMAP folder to poll"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max emails per sync"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Skip AI processing"),
    no_notify: bool = typer.Option(False, "--no-notify", help="Disable desktop notifications"),
):
    """Continuously poll all accounts for new emails. Press Ctrl+C to stop."""
    from core.email.api_p2 import watch_accounts

    print_header("Email Watch Mode")
    print_info(f"Polling every {interval}s — press Ctrl+C to stop")
    console.print()

    cycle = [0]

    def on_new_email(label: str, eid: int, subject: str, sender: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        console.print(
            f"[dim]{ts}[/dim] [bold cyan]●[/bold cyan] "
            f"[bold]{label}[/bold] #{eid} "
            f"[cyan]{sender[:25]}[/cyan] — {subject[:40]}"
        )

    def on_cycle(label: str, stored: int) -> None:
        cycle[0] += 1
        ts = datetime.now().strftime("%H:%M:%S")
        if stored:
            console.print(
                f"[dim]{ts}[/dim] [green]✓[/green] {label}: {stored} new email(s)"
            )
        else:
            console.print(f"[dim]{ts} ✓ {label}: no new emails[/dim]")

    try:
        watch_accounts(
            interval=interval,
            folder=folder,
            limit=limit,
            run_ai=not no_ai,
            notify=not no_notify,
            on_new_email=on_new_email,
            on_cycle_complete=on_cycle,
        )
    except KeyboardInterrupt:
        console.print()
        print_info("Watch mode stopped.")
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# pm email ask
# ---------------------------------------------------------------------------

@app.command("ask")
def ask(
    question: str = typer.Argument(..., help='Natural language question about your emails'),
    limit: int = typer.Option(20, "--limit", "-n", help="Max emails to search"),
    no_refs: bool = typer.Option(False, "--no-refs", help="Hide email references"),
):
    """Ask a natural language question about your inbox."""
    from core.email.api_p2 import ask_email_question

    print_header(f'Email Assistant: "{question}"')

    try:
        answer, refs = ask_email_question(question, limit=limit)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    console.print(Panel(answer, title="[bold yellow]Answer[/bold yellow]", border_style="yellow"))

    if refs and not no_refs:
        console.print()
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table.add_column("#", width=5, justify="right")
        table.add_column("From", max_width=25)
        table.add_column("Subject", max_width=40)
        table.add_column("Date", width=10, justify="right")
        for r in refs[:8]:
            table.add_row(
                str(r["id"]),
                r.get("sender_name") or r["sender"],
                r["subject"],
                _fmt_date(r["date"]),
            )
        console.print(table)
        console.print("[dim]Use 'pm email read <ID>' to open any email.[/dim]")


# ---------------------------------------------------------------------------
# pm email needs-reply
# ---------------------------------------------------------------------------

@app.command("needs-reply")
def needs_reply(
    scan: bool = typer.Option(False, "--scan", "-s", help="Re-scan emails before listing"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max emails to show"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Heuristics only (no AI)"),
):
    """Show emails that likely require your reply."""
    from core.email.api_p2 import get_needs_reply_emails, scan_needs_reply

    print_header("Emails Needing Reply")

    if scan:
        print_info("Scanning emails…")
        try:
            flagged = scan_needs_reply(limit=limit, run_ai=not no_ai)
            print_info(f"Flagged {flagged} email(s) as needing reply.")
        except EmailError as exc:
            print_error(str(exc))
            raise typer.Exit(1)

    try:
        emails = get_needs_reply_emails()
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not emails:
        print_info("No emails flagged as needing reply. Run with --scan to analyse your inbox.")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", width=5, justify="right", style="dim")
    table.add_column("Conf", width=5, justify="right")
    table.add_column("From", max_width=22)
    table.add_column("Subject", max_width=35)
    table.add_column("Reason", max_width=30)
    table.add_column("Date", width=8, justify="right")

    for e in emails[:limit]:
        conf = e.get("reply_confidence", 0)
        conf_color = "red" if conf >= 75 else "yellow" if conf >= 50 else "dim"
        table.add_row(
            str(e["id"]),
            f"[{conf_color}]{conf}%[/{conf_color}]",
            (e.get("sender_name") or e["sender"])[:22],
            e["subject"][:35],
            e.get("reply_reason", "")[:30],
            _fmt_date(e["date"]),
        )
    console.print(table)
    console.print(f"\n[dim]Total: {len(emails)} email(s) need a reply.[/dim]")
    console.print("[dim]Reply with: pm email reply <ID> --ai-draft \"your intent\"[/dim]")


# ---------------------------------------------------------------------------
# pm email today
# ---------------------------------------------------------------------------

@app.command("today")
def today(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Filter by account"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Skip AI summary"),
):
    """Daily inbox digest: unread, priority, meetings, finance, reminders."""
    from core.email.api_p2 import get_today_summary

    print_header("Today's Inbox")

    try:
        data = get_today_summary(account_label=account, run_ai=not no_ai)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    # AI summary
    if data.get("ai_summary"):
        console.print(Panel(
            data["ai_summary"],
            title="[bold yellow]AI Summary[/bold yellow]",
            border_style="yellow",
        ))
        console.print()

    # Stats overview
    stats_table = Table(box=box.SIMPLE, show_header=False)
    stats_table.add_column("Category", style="bold", width=22)
    stats_table.add_column("Count", justify="right", width=6)

    categories = [
        ("📬 Total today", len(data["all"])),
        ("● Unread", len(data["unread"])),
        ("⚡ High priority", len(data["high_priority"])),
        ("↩ Needs reply", len(data["needs_reply"])),
        ("📅 Meetings", len(data["meetings"])),
        ("💰 Finance", len(data["finance"])),
        ("📰 Newsletters", len(data["newsletters"])),
        ("🚨 Spam/Suspicious", len(data["spam"])),
        ("⏰ Due reminders", len(data["due_reminders"])),
    ]
    for label, count in categories:
        color = "bold red" if (label.startswith("⚡") or label.startswith("↩")) and count > 0 else ""
        stats_table.add_row(label, f"[{color}]{count}[/{color}]" if color else str(count))
    console.print(stats_table)

    # Due reminders
    if data["due_reminders"]:
        console.print()
        console.print(Rule("[bold red]⏰ Due Reminders[/bold red]", style="red"))
        for r in data["due_reminders"]:
            console.print(f"  [red]•[/red] [bold]#{r['email_id']}[/bold] {r['note']}")
            console.print(f"    [dim]{r.get('sender_name') or r['sender']} — {r['subject'][:50]}[/dim]")

    # High priority emails
    if data["high_priority"]:
        console.print()
        console.print(Rule("[bold yellow]⚡ High Priority[/bold yellow]", style="yellow"))
        _print_email_mini_table(data["high_priority"][:5])

    # Needs reply
    if data["needs_reply"]:
        console.print()
        console.print(Rule("[bold cyan]↩ Needs Reply[/bold cyan]", style="cyan"))
        _print_email_mini_table(data["needs_reply"][:5])

    # Finance
    if data["finance"]:
        console.print()
        console.print(Rule("[bold green]💰 Finance[/bold green]", style="green"))
        _print_email_mini_table(data["finance"][:3])


def _print_email_mini_table(emails: list[dict]) -> None:
    t = Table(box=box.SIMPLE, show_header=False, expand=True)
    t.add_column("#", width=5, style="dim", justify="right")
    t.add_column("From", max_width=22)
    t.add_column("Subject", max_width=45)
    t.add_column("Date", width=8, justify="right")
    for e in emails:
        t.add_row(
            str(e.get("id", "")),
            (e.get("sender_name") or e.get("sender", ""))[:22],
            e.get("subject", "")[:45],
            _fmt_date(e.get("date", 0)),
        )
    console.print(t)


# ---------------------------------------------------------------------------
# pm email contacts
# ---------------------------------------------------------------------------

@app.command("contacts")
def contacts(
    rebuild: bool = typer.Option(False, "--rebuild", "-r", help="Rebuild contact stats cache"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of contacts to show"),
):
    """Show contact analytics: top senders, reply stats, and recent activity."""
    from core.email.api_p2 import get_contacts

    print_header("Contact Analytics")

    try:
        contact_list = get_contacts(rebuild=rebuild, limit=limit)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not contact_list:
        print_info("No contact data yet. Run 'pm email sync' and then 'pm email contacts --rebuild'.")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", width=3, justify="right", style="dim")
    table.add_column("Contact", max_width=28)
    table.add_column("Received", width=8, justify="right")
    table.add_column("Sent", width=6, justify="right")
    table.add_column("Replied", width=7, justify="right")
    table.add_column("Last Contact", width=12, justify="right")

    for i, c in enumerate(contact_list, 1):
        name = c.get("sender_name") or c["sender"]
        last = max(
            c.get("last_received") or 0,
            c.get("last_sent") or 0,
        )
        table.add_row(
            str(i),
            name[:28],
            str(c["emails_received"]),
            str(c.get("emails_sent", 0)),
            str(c.get("replied_count", 0)),
            _fmt_date(last),
        )
    console.print(table)
    console.print(f"[dim]Showing top {len(contact_list)} contacts by total email volume.[/dim]")


# ---------------------------------------------------------------------------
# pm email remind / reminders
# ---------------------------------------------------------------------------

@app.command("remind")
def remind(
    email_id: int = typer.Argument(..., help="Email ID to set a reminder for"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Reminder note (auto-generated if omitted)"),
    due: Optional[str] = typer.Option(None, "--due", "-d", help="Due date: YYYY-MM-DD, 'tomorrow', 'next week'"),
):
    """Set a reminder for an email."""
    from core.email.api_p2 import create_reminder

    try:
        r = create_reminder(email_id=email_id, note=note, due_str=due)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    print_success(f"Reminder #{r['id']} created for email #{email_id}")
    console.print(f"  [bold]Note:[/bold]  {r['note']}")
    if r.get("due_at"):
        console.print(f"  [bold]Due:[/bold]   {_fmt_date_full(r['due_at'])}")
    else:
        console.print("  [dim]No due date set.[/dim]")


@app.command("reminders")
def list_reminders(
    all_done: bool = typer.Option(False, "--all", help="Include completed reminders"),
    dismiss: Optional[int] = typer.Option(None, "--dismiss", "-d", help="Dismiss reminder by ID"),
):
    """List and manage email reminders."""
    from core.email.api_p2 import dismiss_reminder, list_reminders as _list

    if dismiss is not None:
        try:
            dismiss_reminder(dismiss)
            print_success(f"Reminder #{dismiss} dismissed.")
        except EmailError as exc:
            print_error(str(exc))
            raise typer.Exit(1)
        return

    print_header("Email Reminders")
    try:
        reminders = _list(include_done=all_done)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not reminders:
        print_info("No active reminders. Use 'pm email remind <ID>' to create one.")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", width=5, justify="right", style="dim")
    table.add_column("Email", width=5, justify="right")
    table.add_column("Note", max_width=40)
    table.add_column("Due", width=14)
    table.add_column("Status", width=8)
    table.add_column("Subject", max_width=25)

    for r in reminders:
        status = "[dim]done[/dim]" if r["is_done"] else "[bold green]active[/bold green]"
        due = _fmt_date_full(r["due_at"]) if r.get("due_at") else "[dim]—[/dim]"
        table.add_row(
            str(r["id"]),
            str(r["email_id"]),
            r["note"][:40],
            due,
            status,
            r.get("subject", "")[:25],
        )
    console.print(table)
    console.print("[dim]Dismiss: pm email reminders --dismiss <ID>[/dim]")
