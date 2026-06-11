"""Rich terminal CLI for the PaliMind email module.

Implements all Phase 1 commands under `pm email`:
  add, accounts, sync, list, unread, read, search, compose, reply

Registered as a Typer sub-app and mounted in core/cli/commands.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

import typer
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from core.cli.ui import console, print_error, print_header, print_info, print_success
from core.email.exceptions import EmailError

app = typer.Typer(
    name="email",
    help="Local-first AI email assistant — fetch, search, compose, and reply.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_date(ts: float) -> str:
    """Format a Unix timestamp as a human-friendly relative time."""
    if not ts:
        return "—"
    now = time.time()
    diff = now - ts
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)}m"
    if diff < 86400:
        return f"{int(diff // 3600)}h"
    if diff < 7 * 86400:
        return f"{int(diff // 86400)}d"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%b %d")


def _fmt_date_full(ts: float) -> str:
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / 1024 ** 2:.1f} MB"


def _priority_stars(priority: int) -> str:
    return "★" * priority + "☆" * (5 - priority)


def _open_editor(initial_text: str = "") -> str:
    """Open $EDITOR and return the text the user wrote."""
    editor = os.environ.get("EDITOR", "nano")
    with tempfile.NamedTemporaryFile(
        suffix=".txt", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(initial_text)
        tmp_path = tmp.name
    try:
        subprocess.run([editor, tmp_path], check=True)
        with open(tmp_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print_error(f"Editor '{editor}' not found. Set $EDITOR.")
        return initial_text
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _prompt_confirmation(draft_body: str, label: str = "Send this email?") -> str:
    """Show a draft and prompt user: y/n/e(dit). Returns final body or empty on cancel."""
    console.print(Rule(style="dim"))
    console.print(draft_body)
    console.print(Rule(style="dim"))
    console.print(f"\n[bold]{label}[/bold] [dim]\\[y/N/e(dit)][/dim]: ", end="")
    try:
        choice = input().strip().lower()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return ""
    if choice == "y":
        return draft_body
    if choice == "e":
        return _open_editor(draft_body)
    return ""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("add")
def add_account(
    label: str = typer.Option(..., "--label", "-l", help="Friendly account name"),
    email_addr: str = typer.Option(..., "--email", "-e", help="Email address"),
    imap_host: str = typer.Option(..., "--imap-host", help="IMAP server hostname"),
    imap_port: int = typer.Option(993, "--imap-port", help="IMAP port"),
    smtp_host: str = typer.Option(..., "--smtp-host", help="SMTP server hostname"),
    smtp_port: int = typer.Option(587, "--smtp-port", help="SMTP port"),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Login username (default: email address)"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password (prompted if omitted)", hide_input=True),
    no_ssl: bool = typer.Option(False, "--no-ssl", help="Use STARTTLS instead of SSL"),
    no_test: bool = typer.Option(False, "--no-test", help="Skip connection test"),
):
    """Add a new IMAP/SMTP email account with encrypted credential storage."""
    from core.email.api import add_account as _add

    print_header(f"Adding Email Account: {label}")

    if not password:
        try:
            import getpass
            password = getpass.getpass(f"Password for {email_addr}: ")
        except (KeyboardInterrupt, EOFError):
            print_error("Aborted.")
            raise typer.Exit(1)

    use_ssl = not no_ssl

    if not no_test:
        print_info(f"Testing IMAP connection to {imap_host}:{imap_port}...")

    try:
        acc = _add(
            label=label,
            email_address=email_addr,
            imap_host=imap_host,
            imap_port=imap_port,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            test_connection=not no_test,
        )
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not no_test:
        print_success("IMAP connection successful")
        print_success("SMTP connection successful")
    print_success(f'Account "{acc.label}" saved (credentials encrypted)')


@app.command("accounts")
def list_accounts():
    """List all configured email accounts with last-sync information."""
    from core.email.api import list_accounts as _list

    print_header("Email Accounts")
    try:
        accounts = _list()
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not accounts:
        print_info("No email accounts configured. Run 'pm email add' to add one.")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Label", style="bold")
    table.add_column("Email", style="cyan")
    table.add_column("IMAP Host")
    table.add_column("Last Synced", justify="right")

    for i, acc in enumerate(accounts, 1):
        last_sync = (
            _fmt_date(acc.last_sync_at) if acc.last_sync_at else "[dim]Never[/dim]"
        )
        table.add_row(str(i), acc.label, acc.email_address, acc.imap_host, last_sync)

    console.print(table)


@app.command("sync")
def sync(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Account label (default: all)"),
    folder: str = typer.Option("INBOX", "--folder", "-f", help="IMAP folder to sync"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max emails to fetch per sync"),
    full: bool = typer.Option(False, "--full", help="Full re-sync (ignore last UID)"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Skip AI processing"),
):
    """Incrementally fetch new emails from IMAP. Optionally run AI analysis."""
    from core.email.api import list_accounts as _list_accs
    from core.email.api import sync_account as _sync

    print_header("Syncing Email")

    try:
        accounts = _list_accs()
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    if not accounts:
        print_info("No accounts configured. Run 'pm email add' first.")
        return

    targets = [a for a in accounts if not account or a.label == account]
    if not targets:
        print_error(f'Account "{account}" not found. Run "pm email accounts" to see available accounts.')
        raise typer.Exit(1)

    for acc in targets:
        print_info(f'Syncing "{acc.label}" — {folder}')

        fetch_task = None
        ai_task = None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=False,
        ) as progress:

            def on_progress(phase: str, current: int, total: int) -> None:
                nonlocal fetch_task, ai_task
                if phase == "fetch":
                    if fetch_task is None:
                        fetch_task = progress.add_task("Fetching new emails…", total=total or 1)
                    progress.update(fetch_task, completed=current, total=total or 1)
                elif phase == "ai":
                    if ai_task is None:
                        ai_task = progress.add_task("Running AI analysis…", total=total or 1)
                    progress.update(ai_task, completed=current, total=total or 1)

            try:
                result = _sync(
                    acc.label,
                    folder=folder,
                    limit=limit,
                    full_resync=full,
                    run_ai=not no_ai,
                    progress_callback=on_progress,
                )
            except EmailError as exc:
                print_error(str(exc))
                continue

        attachments_note = ""
        print_success(
            f"Synced [bold]{result.stored}[/bold] new email(s) "
            f"({result.duplicates} duplicates, {result.parse_errors} errors)"
        )
        if result.ai_processed and not no_ai:
            print_info(f"AI processed: {result.ai_processed} email(s)")


@app.command("list")
def list_emails(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Filter by account"),
    folder: Optional[str] = typer.Option(None, "--folder", "-f", help="IMAP folder"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of emails to show"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    sort: str = typer.Option("date", "--sort", "-s", help="Sort by: date, priority, sender"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    after: Optional[str] = typer.Option(None, "--after", help="Emails after date (YYYY-MM-DD)"),
    before: Optional[str] = typer.Option(None, "--before", help="Emails before date (YYYY-MM-DD)"),
):
    """List emails from the local store with filters and sorting."""
    from core.email.api import list_emails as _list

    try:
        emails = _list(
            account_label=account,
            folder=folder,
            limit=limit,
            offset=offset,
            sort=sort,
            tag=tag,
            after_str=after,
            before_str=before,
        )
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    title = folder or "INBOX"
    if account:
        title = f"{title} — {account}"
    print_header(f"{title} ({len(emails)} emails)")

    if not emails:
        print_info("No emails found. Run 'pm email sync' to fetch emails.")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", justify="right", style="dim", width=5)
    table.add_column("●", width=2)
    table.add_column("From", max_width=20, no_wrap=True)
    table.add_column("Subject", max_width=35, no_wrap=True)
    table.add_column("Summary", max_width=40, no_wrap=True)
    table.add_column("Date", justify="right", width=8)

    for em in emails:
        unread_dot = "[bold cyan]●[/bold cyan]" if not em.is_read else " "
        sender_display = em.sender_name or em.sender
        if len(sender_display) > 20:
            sender_display = sender_display[:18] + "…"
        subject_display = em.subject or "(no subject)"
        summary_display = (em.summary[:37] + "…") if len(em.summary) > 40 else em.summary
        table.add_row(
            str(em.id),
            unread_dot,
            sender_display,
            subject_display,
            summary_display or "[dim]—[/dim]",
            _fmt_date(em.date),
        )

    console.print(table)
    console.print("[dim]● = unread   Use 'pm email read <ID>' to open[/dim]")


@app.command("unread")
def unread(
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Filter by account"),
    folder: str = typer.Option("INBOX", "--folder", "-f", help="IMAP folder"),
    count_only: bool = typer.Option(False, "--count", "-c", help="Show count only"),
):
    """Show unread emails or just the count."""
    from core.email.api import unread_emails as _unread

    try:
        result = _unread(account_label=account, folder=folder)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    total = result["total"]
    by_account: dict = result["by_account"]
    emails = result["emails"]

    if count_only:
        print_info(f"{total} unread email(s) across {len(by_account)} account(s)")
        for label, cnt in by_account.items():
            if cnt:
                console.print(f"  [cyan]{label}[/cyan]: {cnt} unread")
        return

    print_header(f"Unread Emails ({total})")
    if not emails:
        print_info("No unread emails.")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", justify="right", style="dim", width=5)
    table.add_column("From", max_width=22)
    table.add_column("Subject", max_width=36)
    table.add_column("Summary", max_width=40)
    table.add_column("Date", justify="right", width=8)

    for em in emails:
        sender_display = em.sender_name or em.sender
        table.add_row(
            str(em.id),
            sender_display[:22],
            em.subject[:36],
            (em.summary[:37] + "…") if len(em.summary) > 40 else em.summary or "[dim]—[/dim]",
            _fmt_date(em.date),
        )
    console.print(table)


@app.command("read")
def read_email(
    email_id: int = typer.Argument(..., help="Email ID from 'pm email list'"),
    show_html: bool = typer.Option(False, "--html", help="Show raw HTML body"),
    show_headers: bool = typer.Option(False, "--headers", help="Show full headers"),
    thread: bool = typer.Option(False, "--thread", help="Show full thread"),
):
    """Display the full content of a specific email."""
    from core.email.api import get_email as _get
    from core.email.store import get_emails

    try:
        em = _get(email_id)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    # Build header panel
    tags_display = ", ".join(em.tag_list) if em.tag_list else "—"
    priority_display = f"{_priority_stars(em.priority)} ({em.priority}/5)" if em.priority else "—"
    spam_display = f"{em.spam_score}/100" if em.spam_score else "—"

    header_lines = [
        f"[bold]From:[/bold]    {em.sender_name} <{em.sender}>" if em.sender_name else f"[bold]From:[/bold]    {em.sender}",
        f"[bold]To:[/bold]      {em.recipients}",
        f"[bold]Date:[/bold]    {_fmt_date_full(em.date)}",
        f"[bold]Subject:[/bold] {em.subject}",
        f"[bold]Tags:[/bold]    {tags_display}",
        f"[bold]Priority:[/bold] {priority_display}",
    ]
    if em.spam_score > 30:
        header_lines.append(f"[bold yellow]Spam Score:[/bold yellow] {spam_display}")
    if em.attachments:
        att_list = ", ".join(
            f"{a.filename} ({_fmt_size(a.size_bytes)})" for a in em.attachments
        )
        header_lines.append(f"[bold]Attachments:[/bold] {att_list}")
    if show_headers:
        header_lines.append(f"[bold]Message-ID:[/bold] {em.message_id}")
        if em.in_reply_to:
            header_lines.append(f"[bold]In-Reply-To:[/bold] {em.in_reply_to}")

    console.print(Panel(
        "\n".join(header_lines),
        title=f"[bold cyan]Email #{em.id}[/bold cyan]",
        border_style="cyan",
    ))

    if em.summary:
        console.print()
        console.print(Panel(
            em.summary,
            title="[bold yellow]AI Summary[/bold yellow]",
            border_style="yellow",
        ))

    console.print()
    console.print(Rule(style="dim"))

    body = em.body_html if show_html else em.body_text
    if not body:
        body = "[dim](no body)[/dim]"
    console.print(body)
    console.print(Rule(style="dim"))
    console.print(f"[dim]Reply with: pm email reply {em.id} --ai-draft \"your intent\"[/dim]")


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Filter by account"),
    folder: Optional[str] = typer.Option(None, "--folder", "-f", help="Filter by folder"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    after: Optional[str] = typer.Option(None, "--after", help="Emails after date (YYYY-MM-DD)"),
    before: Optional[str] = typer.Option(None, "--before", help="Emails before date (YYYY-MM-DD)"),
):
    """Full-text keyword search across subject, body, and sender (BM25 ranked)."""
    from core.email.api import search_emails as _search

    try:
        results = _search(
            query,
            account_label=account,
            folder=folder,
            limit=limit,
            after_str=after,
            before_str=before,
        )
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    print_header(f'Search Results: "{query}" ({len(results)} matches)')
    if not results:
        print_info("No matching emails found.")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", justify="right", style="dim", width=5)
    table.add_column("Score", justify="right", width=7)
    table.add_column("From", max_width=20)
    table.add_column("Subject", max_width=30)
    table.add_column("Snippet", max_width=40)
    table.add_column("Date", justify="right", width=8)

    for r in results:
        unread_mark = "" if r.is_read else "[cyan]●[/cyan] "
        table.add_row(
            str(r.email_id),
            f"{r.score:.1f}",
            r.sender[:20],
            unread_mark + r.subject[:30],
            r.snippet[:40],
            _fmt_date(r.date),
        )
    console.print(table)


@app.command("compose")
def compose(
    account: str = typer.Option(..., "--account", "-a", help="Account to send from"),
    to: str = typer.Option(..., "--to", help="Recipient email address(es), comma-separated"),
    subject: str = typer.Option(..., "--subject", "-s", help="Email subject"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Email body (opens $EDITOR if omitted)"),
    cc: Optional[str] = typer.Option(None, "--cc", help="CC recipients (comma-separated)"),
    ai_draft: Optional[str] = typer.Option(None, "--ai-draft", help="AI drafting intent"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Compose and send a new email, with optional AI-assisted drafting."""
    from core.email.api import ai_draft_compose, compose_email

    print_header("Composing Email")

    to_addrs = [a.strip() for a in to.split(",") if a.strip()]
    cc_addrs = [a.strip() for a in (cc or "").split(",") if a.strip()]

    final_body = body or ""

    if ai_draft:
        print_info("Generating AI draft…")
        draft = ai_draft_compose(ai_draft, ", ".join(to_addrs))
        if draft:
            final_body = draft
        else:
            print_info("AI draft unavailable (Ollama may be offline). Falling back to manual.")

    if not final_body:
        final_body = _open_editor()

    if not final_body.strip():
        print_error("Aborted — no body provided.")
        raise typer.Exit(1)

    # Show preview
    console.print(f"\n[bold]To:[/bold]      {', '.join(to_addrs)}")
    if cc_addrs:
        console.print(f"[bold]Cc:[/bold]      {', '.join(cc_addrs)}")
    console.print(f"[bold]Subject:[/bold] {subject}")

    if not yes and not dry_run:
        final_body = _prompt_confirmation(final_body, "Send this email?")
        if not final_body:
            print_info("Cancelled.")
            return

    if dry_run:
        console.print(Rule(style="dim"))
        console.print(final_body)
        console.print(Rule(style="dim"))
        print_info("[dry-run] Email not sent.")
        return

    try:
        result = compose_email(
            account_label=account,
            to_addresses=to_addrs,
            subject=subject,
            body=final_body,
            cc=cc_addrs or None,
        )
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    print_success(f"Email sent via {result.smtp_host}")


@app.command("reply")
def reply(
    email_id: int = typer.Argument(..., help="Email ID to reply to"),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Reply body"),
    ai_draft: Optional[str] = typer.Option(None, "--ai-draft", help="AI drafting intent"),
    reply_all: bool = typer.Option(False, "--reply-all", help="Reply to all recipients"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Reply to an email, with optional AI-assisted drafting."""
    from core.email.api import ai_draft_reply
    from core.email.api import reply_to_email as _reply
    from core.email.store import get_email_by_id

    print_header(f"Replying to Email #{email_id}")

    try:
        original = get_email_by_id(email_id)
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    console.print(f'[dim]Original: "{original.subject}" from {original.sender}[/dim]')

    final_body = body or ""

    if ai_draft:
        print_info("Generating AI draft…")
        draft = ai_draft_reply(email_id, ai_draft)
        if draft:
            final_body = draft
        else:
            print_info("AI draft unavailable. Falling back to manual.")

    if not final_body:
        final_body = _open_editor()

    if not final_body.strip():
        print_error("Aborted — no reply body provided.")
        raise typer.Exit(1)

    subject_display = (
        original.subject if original.subject.startswith("Re:")
        else f"Re: {original.subject}"
    )
    console.print(f"\n[bold]Subject:[/bold] {subject_display}")

    if not yes and not dry_run:
        final_body = _prompt_confirmation(final_body, "Send this reply?")
        if not final_body:
            print_info("Cancelled.")
            return

    if dry_run:
        console.print(Rule(style="dim"))
        console.print(final_body)
        console.print(Rule(style="dim"))
        print_info("[dry-run] Reply not sent.")
        return

    try:
        result = _reply(
            email_id,
            body=final_body,
            reply_all=reply_all,
        )
    except EmailError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    print_success(f"Reply sent via {result.smtp_host}")
