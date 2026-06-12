"""
FastAPI router for the PaliMind Email Module.
Mounted at /api/email/ in api_server.py.
All endpoints delegate to core.email.api and core.email.api_p2 — never duplicates logic.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/email", tags=["email"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Correct DB path — must match store.py (_EMAIL_DB_PATH)
_EMAIL_DB_PATH = Path.home() / ".palimind" / "email.db"


def _db() -> Path:
    """Return the global email DB path."""
    return _EMAIL_DB_PATH


# Initialise DB schema once at import time (idempotent — safe to repeat).
# This avoids running all DDL statements on every request (was causing 7-second delays).
try:
    from core.email.api import ensure_db as _ensure_db
    _ensure_db(_EMAIL_DB_PATH)
except Exception:
    pass  # DB will be initialised lazily on first actual use


def _ok(**kw):
    return {"status": "ok", **kw}


def _err(msg: str, code: int = 400):
    return JSONResponse(status_code=code, content={"error": msg})




# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@router.get("/accounts")
async def list_accounts():
    try:
        from core.email.api import list_accounts as _list
        accounts = await asyncio.to_thread(_list, _db())
        return {"accounts": [
            {
                "id": a.id,
                "label": a.label,
                "email": a.email_address,
                "imap_host": a.imap_host,
                "smtp_host": a.smtp_host,
                "use_ssl": a.use_ssl,
            }
            for a in accounts
        ]}
    except Exception as exc:
        return {"accounts": [], "warning": str(exc)}


@router.post("/accounts")
async def add_account(req: Request):
    try:
        data = await req.json()
        from core.email.api import add_account as _add
        account = await asyncio.to_thread(
            _add,
            label=data["label"],
            email_address=data["email_address"],
            imap_host=data["imap_host"],
            imap_port=int(data.get("imap_port", 993)),
            smtp_host=data["smtp_host"],
            smtp_port=int(data.get("smtp_port", 465)),
            username=data.get("username"),
            password=data["password"],
            use_ssl=bool(data.get("use_ssl", True)),
            test_connection=bool(data.get("test_connection", False)),
            db_path=_db(),
        )
        return _ok(account={"id": account.id, "label": account.label, "email": account.email_address})
    except Exception as exc:
        return _err(str(exc))


@router.delete("/accounts/{label}")
async def delete_account(label: str, purge_emails: bool = True):
    """Delete an account by label and optionally purge all its emails."""
    try:
        from core.email.api import delete_account as _delete
        await asyncio.to_thread(_delete, label, purge_emails=purge_emails, db_path=_db())
        return _ok(label=label, purge_emails=purge_emails)
    except Exception as exc:
        return _err(str(exc))



@router.post("/sync")
async def sync_account(req: Request):
    try:
        data = await req.json()
        label = data.get("account_label")
        if not label:
            return _err("account_label required")
        from core.email.api import sync_account as _sync
        result = await asyncio.to_thread(
            _sync,
            label,
            folder=data.get("folder", "INBOX"),
            limit=int(data.get("limit", 50)),
            full_resync=bool(data.get("full_resync", False)),
            run_ai=bool(data.get("run_ai", True)),
            db_path=_db(),
        )
        return _ok(
            account=result.account_label,
            folder=result.folder,
            fetched=result.fetched,
            stored=result.stored,
            duplicates=result.duplicates,
            parse_errors=result.parse_errors,
            ai_processed=result.ai_processed,
        )
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Folders (virtual — derived from DB data)
# ---------------------------------------------------------------------------

@router.get("/folders")
async def get_folders():
    try:

        import sqlite3
        db = _db()
        con = sqlite3.connect(str(db))
        cur = con.cursor()

        counts = {}
        try:
            cur.execute("SELECT COUNT(*) FROM emails WHERE is_read=0 AND is_sent=0")
            counts["inbox"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM emails WHERE is_read=0 AND is_sent=0")
            counts["unread"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM emails WHERE is_sent=1")
            counts["sent"] = cur.fetchone()[0]
        except Exception:
            pass

        try:
            cur.execute("""
                SELECT COUNT(*) FROM emails e
                JOIN email_p2_meta m ON e.id = m.email_id
                WHERE m.needs_reply=1 AND e.is_sent=0
            """)
            counts["needs_reply"] = cur.fetchone()[0]
        except Exception:
            counts["needs_reply"] = 0

        try:
            cur.execute("""
                SELECT COUNT(*) FROM emails e
                JOIN email_p2_meta m ON e.id = m.email_id
                WHERE m.is_newsletter=1
            """)
            counts["newsletters"] = cur.fetchone()[0]
        except Exception:
            counts["newsletters"] = 0

        try:
            cur.execute("""
                SELECT COUNT(*) FROM emails e
                JOIN email_p2_meta m ON e.id = m.email_id
                WHERE m.spam_status IN ('spam','suspicious')
            """)
            counts["spam"] = cur.fetchone()[0]
        except Exception:
            counts["spam"] = 0

        # Today
        import time
        today_start = time.time() - 86400
        try:
            cur.execute("SELECT COUNT(*) FROM emails WHERE date >= ? AND is_sent=0", (today_start,))
            counts["today"] = cur.fetchone()[0]
        except Exception:
            counts["today"] = 0

        con.close()

        folders = [
            {"id": "inbox",       "label": "Inbox",        "count": counts.get("inbox", 0)},
            {"id": "unread",      "label": "Unread",       "count": counts.get("unread", 0)},
            {"id": "needs_reply", "label": "Needs Reply",  "count": counts.get("needs_reply", 0)},
            {"id": "today",       "label": "Today",        "count": counts.get("today", 0)},
            {"id": "sent",        "label": "Sent",         "count": counts.get("sent", 0)},
            {"id": "drafts",      "label": "Drafts",       "count": 0},
            {"id": "spam",        "label": "Spam",         "count": counts.get("spam", 0)},
            {"id": "newsletters", "label": "Newsletters",  "count": counts.get("newsletters", 0)},
            {"id": "archive",     "label": "Archive",      "count": 0},
        ]
        return {"folders": folders}
    except Exception as exc:
        return {"folders": [], "warning": str(exc)}


# ---------------------------------------------------------------------------
# Email list
# ---------------------------------------------------------------------------

def _serialise_email(em) -> dict:
    import time
    return {
        "id": em.id,
        "account_id": em.account_id,
        "folder": em.folder,
        "subject": em.subject or "(no subject)",
        "sender": em.sender or "",
        "sender_name": em.sender_name or em.sender or "",
        "recipients": em.recipients or "",
        "date": em.date or 0,
        "summary": em.summary or "",
        "tags": em.tags or "",
        "priority": em.priority or 0,
        "spam_score": em.spam_score or 0,
        "is_read": bool(em.is_read),
        "is_sent": bool(em.is_sent),
        "has_attachments": bool(em.has_attachments),
        "body_preview": (em.body_text or "")[:200],
    }


@router.get("/list")
async def list_emails(
    account_label: Optional[str] = None,
    folder: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "date",
    unread_only: bool = False,
    tag: Optional[str] = None,
):
    try:
        from core.email.api import list_emails as _list, ensure_db

        # Translate virtual folder IDs to real filters
        unread_flag = unread_only
        real_folder = None
        if folder == "inbox":
            real_folder = None
        elif folder == "unread":
            unread_flag = True
        elif folder == "sent":
            real_folder = "Sent"
        elif folder == "needs_reply":
            # handled separately below
            real_folder = None
        elif folder == "today":
            real_folder = None
        else:
            real_folder = folder

        # ensure_db already called at module load

        if folder == "needs_reply":
            from core.email.api_p2 import get_needs_reply_emails
            rows = await asyncio.to_thread(get_needs_reply_emails, _db())
            result = [_serialise_email(r) if hasattr(r, "subject") else r for r in rows]
            return {"emails": result, "total": len(result)}

        if folder == "spam":
            from core.email.api_p2 import get_spam_list
            rows = await asyncio.to_thread(get_spam_list, None, limit, _db())
            result = [_serialise_email(r) if hasattr(r, "subject") else r for r in rows]
            return {"emails": result, "total": len(result)}

        if folder == "newsletters":
            from core.email.api_p2 import get_newsletters
            rows = await asyncio.to_thread(get_newsletters, _db())
            result = [_serialise_email(r) if hasattr(r, "subject") else r for r in rows]
            return {"emails": result[:limit], "total": len(result)}


        emails = await asyncio.to_thread(
            _list,
            account_label=account_label,
            folder=real_folder,
            limit=limit,
            offset=offset,
            sort=sort,
            tag=tag,
            unread_only=unread_flag,
            db_path=_db(),
        )

        # For today filter, add time filtering
        if folder == "today":
            import time
            cutoff = time.time() - 86400
            emails = [e for e in emails if e.date and e.date >= cutoff]

        return {"emails": [_serialise_email(e) for e in emails], "total": len(emails)}
    except Exception as exc:
        return {"emails": [], "total": 0, "warning": str(exc)}


# ---------------------------------------------------------------------------
# Read single email
# ---------------------------------------------------------------------------

@router.get("/read/{email_id}")
async def read_email(email_id: int):
    try:
        from core.email.api import get_email
        em = await asyncio.to_thread(get_email, email_id, _db())

        # Fetch attachments
        import sqlite3
        con = sqlite3.connect(str(_db()))
        cur = con.cursor()
        attachments = []
        try:
            cur.execute(
                "SELECT filename, content_type, size_bytes FROM email_attachments WHERE email_id=?",
                (email_id,)
            )
            attachments = [{"filename": r[0], "content_type": r[1], "size_bytes": r[2]} for r in cur.fetchall()]
        except Exception:
            pass

        # Fetch p2 meta
        p2 = {}
        try:
            cur.execute(
                """SELECT needs_reply, reply_confidence, reply_reason,
                          is_newsletter, newsletter_conf,
                          spam_status, spam_confidence, spam_reason, spam_reviewed
                   FROM email_p2_meta WHERE email_id=?""",
                (email_id,)
            )
            row = cur.fetchone()
            if row:
                p2 = {
                    "needs_reply": bool(row[0]),
                    "reply_confidence": row[1],
                    "reply_reason": row[2],
                    "is_newsletter": bool(row[3]),
                    "newsletter_conf": row[4],
                    "spam_status": row[5],
                    "spam_confidence": row[6],
                    "spam_reason": row[7],
                    "spam_reviewed": bool(row[8]) if row[8] is not None else False,
                }
        except Exception:
            pass
        con.close()

        return {
            **_serialise_email(em),
            "body_text": em.body_text or "",
            "body_html": em.body_html or "",
            "cc": em.cc or "",
            "in_reply_to": em.in_reply_to or "",
            "thread_id": em.thread_id or "",
            "attachments": attachments,
            "p2_meta": p2,
        }
    except Exception as exc:
        return _err(str(exc), 404)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_emails(q: str, limit: int = 20, folder: Optional[str] = None):
    try:
        from core.email.api import search_emails as _search
        results = await asyncio.to_thread(
            _search, q, folder=folder, limit=limit, db_path=_db()
        )
        return {"results": [
            {
                "email_id": r.email_id,
                "subject": r.subject,
                "sender": r.sender,
                "date": r.date,
                "snippet": r.snippet,
                "rank": r.rank,
            }
            for r in results
        ]}
    except Exception as exc:
        return {"results": [], "warning": str(exc)}


# ---------------------------------------------------------------------------
# Natural language ask
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask_inbox(req: Request):
    try:
        data = await req.json()
        question = data.get("question", "").strip()
        if not question:
            return _err("question required")
        from core.email.api_p2 import ask_email_question
        answer, refs = await asyncio.to_thread(ask_email_question, question, 20, _db())
        return {"answer": answer, "citations": refs}
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Compose / Reply
# ---------------------------------------------------------------------------

@router.post("/compose")
async def compose_email(req: Request):
    try:
        data = await req.json()
        account_label = data.get("account_label")
        if not account_label:
            return _err("account_label required")
        from core.email.api import compose_email as _compose
        result = await asyncio.to_thread(
            _compose,
            account_label=account_label,
            to_addresses=data.get("to", []),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            cc=data.get("cc"),
            dry_run=bool(data.get("dry_run", False)),
            db_path=_db(),
        )
        return _ok(message_id=result.message_id, recipient=result.recipient)
    except Exception as exc:
        return _err(str(exc))


@router.post("/reply")
async def reply_to_email(req: Request):
    try:
        data = await req.json()
        email_id = data.get("email_id")
        if not email_id:
            return _err("email_id required")
        from core.email.api import reply_to_email as _reply
        result = await asyncio.to_thread(
            _reply,
            int(email_id),
            body=data.get("body", ""),
            reply_all=bool(data.get("reply_all", False)),
            dry_run=bool(data.get("dry_run", False)),
            db_path=_db(),
        )
        return _ok(message_id=result.message_id, recipient=result.recipient)
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# AI draft helpers
# ---------------------------------------------------------------------------

@router.post("/ai/draft")
async def ai_draft(req: Request):
    try:
        data = await req.json()
        email_id = data.get("email_id")
        intent = data.get("intent", "")
        recipient = data.get("recipient", "")

        if email_id:
            from core.email.api_p2 import draft_reply_styled
            draft = await asyncio.to_thread(draft_reply_styled, int(email_id), intent, _db())
        else:
            from core.email.api_p2 import draft_compose_styled
            draft = await asyncio.to_thread(draft_compose_styled, intent, recipient, _db())
        return {"draft": draft}
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Mark read / unread / archive / delete
# ---------------------------------------------------------------------------

@router.post("/mark_read")
async def mark_read(req: Request):
    try:
        data = await req.json()
        eid = int(data["email_id"])
        from core.email import store
        await asyncio.to_thread(store.mark_read, eid, _db())
        return _ok()
    except Exception as exc:
        return _err(str(exc))


@router.post("/mark_unread")
async def mark_unread(req: Request):
    try:
        data = await req.json()
        eid = int(data["email_id"])
        import sqlite3
        con = sqlite3.connect(str(_db()))
        con.execute("UPDATE emails SET is_read=0 WHERE id=?", (eid,))
        con.commit()
        con.close()
        return _ok()
    except Exception as exc:
        return _err(str(exc))


@router.post("/delete")
async def delete_email(req: Request):
    try:
        data = await req.json()
        eid = int(data["email_id"])
        import sqlite3
        con = sqlite3.connect(str(_db()))
        con.execute("DELETE FROM emails WHERE id=?", (eid,))
        con.commit()
        con.close()
        return _ok()
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

@router.get("/reminders")
async def list_reminders(include_done: bool = False):
    try:
        from core.email.api_p2 import list_reminders as _list
        reminders = await asyncio.to_thread(_list, include_done, _db())
        return {"reminders": reminders}
    except Exception as exc:
        return {"reminders": [], "warning": str(exc)}


@router.post("/reminders")
async def create_reminder(req: Request):
    try:
        data = await req.json()
        from core.email.api_p2 import create_reminder as _create
        result = await asyncio.to_thread(
            _create,
            email_id=int(data["email_id"]),
            note=data.get("note"),
            due_str=data.get("due"),
            auto_note=bool(data.get("auto_note", True)),
            db_path=_db(),
        )
        return _ok(**result)
    except Exception as exc:
        return _err(str(exc))


@router.post("/reminders/dismiss")
async def dismiss_reminder(req: Request):
    try:
        data = await req.json()
        from core.email.api_p2 import dismiss_reminder as _dismiss
        await asyncio.to_thread(_dismiss, int(data["reminder_id"]), _db())
        return _ok()
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@router.get("/contacts")
async def get_contacts(rebuild: bool = False, limit: int = 50):
    try:
        from core.email.api_p2 import get_contacts as _get
        contacts = await asyncio.to_thread(_get, rebuild, limit, _db())
        return {"contacts": contacts}
    except Exception as exc:
        return {"contacts": [], "warning": str(exc)}


# ---------------------------------------------------------------------------
# Spam
# ---------------------------------------------------------------------------

@router.get("/spam")
async def get_spam(status: Optional[str] = None, limit: int = 50):
    try:
        from core.email.api_p2 import get_spam_list
        items = await asyncio.to_thread(get_spam_list, status, limit, _db())
        return {"spam": items}
    except Exception as exc:
        return {"spam": [], "warning": str(exc)}


@router.post("/spam/scan")
async def scan_spam():
    try:
        from core.email.api_p2 import scan_spam as _scan
        count = await asyncio.to_thread(_scan, 100, _db())
        return _ok(flagged=count)
    except Exception as exc:
        return _err(str(exc))


@router.post("/spam/whitelist")
async def whitelist_sender(req: Request):
    try:
        data = await req.json()
        from core.email.api_p2 import add_spam_whitelist
        await asyncio.to_thread(add_spam_whitelist, data["sender"], _db())
        return _ok()
    except Exception as exc:
        return _err(str(exc))


@router.post("/spam/blacklist")
async def blacklist_sender(req: Request):
    try:
        data = await req.json()
        from core.email.api_p2 import add_spam_blacklist
        await asyncio.to_thread(add_spam_blacklist, data["sender"], _db())
        return _ok()
    except Exception as exc:
        return _err(str(exc))


@router.post("/spam/review")
async def review_spam(req: Request):
    try:
        data = await req.json()
        from core.email.api_p2 import mark_spam_reviewed
        await asyncio.to_thread(mark_spam_reviewed, int(data["email_id"]), bool(data.get("is_spam", False)), _db())
        return _ok()
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Newsletters
# ---------------------------------------------------------------------------

@router.get("/newsletters")
async def get_newsletters():
    try:
        from core.email.api_p2 import get_newsletters as _get
        items = await asyncio.to_thread(_get, _db())
        return {"newsletters": items}
    except Exception as exc:
        return {"newsletters": [], "warning": str(exc)}


@router.post("/newsletters/scan")
async def scan_newsletters():
    try:
        from core.email.api_p2 import scan_newsletters as _scan
        count = await asyncio.to_thread(_scan, 100, _db())
        return _ok(marked=count)
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Today dashboard
# ---------------------------------------------------------------------------

@router.get("/today")
async def get_today(account_label: Optional[str] = None, run_ai: bool = False):
    try:
        from core.email.api_p2 import get_today_summary
        data = await asyncio.to_thread(get_today_summary, account_label, run_ai, _db())
        return data
    except Exception as exc:
        return {"warning": str(exc), "all": [], "unread": [], "ai_summary": ""}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_stats():
    try:
        from core.email.api_p2 import get_enhanced_stats
        stats = await asyncio.to_thread(get_enhanced_stats, _db())
        return stats
    except Exception as exc:
        return {"warning": str(exc)}


# ---------------------------------------------------------------------------
# Phase 2 scan endpoints (called from UI AI Action buttons)
# ---------------------------------------------------------------------------

@router.post("/p2/scan-reply")
async def scan_needs_reply_endpoint():
    """Scan inbox for emails that need a reply. Called by the UI 'Scan Needs-Reply' button."""
    try:
        from core.email.api_p2 import scan_needs_reply as _scan
        count = await asyncio.to_thread(_scan, 100, True, _db())
        return _ok(flagged=count)
    except Exception as exc:
        return _err(str(exc))


@router.get("/spam/dashboard")
async def spam_dashboard():
    """Return the spam statistics dashboard (counts + top senders)."""
    try:
        from core.email.api_p2 import get_spam_dashboard
        data = await asyncio.to_thread(get_spam_dashboard, _db())
        return data
    except Exception as exc:
        return {"warning": str(exc)}

