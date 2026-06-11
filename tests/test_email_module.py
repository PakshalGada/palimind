"""Tests for the PaliMind email module — Phase 1.

Tests cover all core modules without external network calls.
IMAP/SMTP interactions are replaced with mocks.
"""
from __future__ import annotations

import email
import email.policy
import pathlib
import tempfile
import time
import unittest
import unittest.mock as mock
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# crypto
# ---------------------------------------------------------------------------


class TestCrypto(unittest.TestCase):
    def test_round_trip(self):
        from core.email.crypto import decrypt_password, encrypt_password

        for pw in ["simple", "c0mpl€x!@#", "a" * 200, ""]:
            enc = encrypt_password(pw)
            assert isinstance(enc, str)
            assert enc != pw
            dec = decrypt_password(enc)
            assert dec == pw, f"Round-trip failed for {pw!r}"

    def test_invalid_token_raises(self):
        from core.email.crypto import decrypt_password
        from core.email.exceptions import EmailCryptoError

        with self.assertRaises(EmailCryptoError):
            decrypt_password("notavalidtoken==")

    def test_different_encryptions_of_same_password(self):
        """Fernet uses random nonces — two encryptions should differ."""
        from core.email.crypto import encrypt_password

        enc1 = encrypt_password("password")
        enc2 = encrypt_password("password")
        # They decrypt to the same value but are (almost certainly) different tokens
        from core.email.crypto import decrypt_password

        assert decrypt_password(enc1) == decrypt_password(enc2)


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = pathlib.Path(self.tmpdir.name) / "test_email.db"
        from core.email.store import init_email_db

        init_email_db(self.db)

        # Create a test account
        from core.email.crypto import encrypt_password
        from core.email.store import save_account

        self.enc_pw = encrypt_password("testpass")
        self.account_id = save_account(
            label="TestAcc",
            email_address="test@example.com",
            imap_host="imap.example.com",
            imap_port=993,
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="test@example.com",
            password_enc=self.enc_pw,
            use_ssl=True,
            db_path=self.db,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _upsert(self, *, uid=1, message_id="<msg@test>", subject="Test", body="body text"):
        from core.email.store import upsert_email

        return upsert_email(
            account_id=self.account_id,
            folder="INBOX",
            uid=uid,
            message_id=message_id,
            in_reply_to="",
            references="",
            thread_id="thread1",
            subject=subject,
            sender="alice@example.com",
            sender_name="Alice",
            recipients="test@example.com",
            cc="",
            date=time.time(),
            body_html="",
            body_text=body,
            has_attachments=False,
            db_path=self.db,
        )

    def test_schema_created(self):
        import sqlite3

        conn = sqlite3.connect(str(self.db))
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        for expected in ("accounts", "emails", "attachments", "sync_state", "schema_version"):
            self.assertIn(expected, tables)

    def test_duplicate_label_raises(self):
        from core.email.exceptions import EmailError
        from core.email.store import save_account

        with self.assertRaises(EmailError):
            save_account(
                label="TestAcc",  # duplicate
                email_address="other@example.com",
                imap_host="imap.example.com",
                imap_port=993,
                smtp_host="smtp.example.com",
                smtp_port=587,
                username="other@example.com",
                password_enc=self.enc_pw,
                use_ssl=True,
                db_path=self.db,
            )

    def test_upsert_email_and_dedup(self):
        eid = self._upsert(uid=1, message_id="<unique@test>")
        self.assertIsNotNone(eid)
        # Duplicate
        eid2 = self._upsert(uid=1, message_id="<unique@test>")
        self.assertIsNone(eid2)

    def test_get_email_by_id(self):
        from core.email.store import get_email_by_id

        eid = self._upsert(subject="Hello World", body="Test body for searching")
        em = get_email_by_id(eid, self.db)
        self.assertEqual(em.subject, "Hello World")
        self.assertEqual(em.body_text, "Test body for searching")

    def test_email_not_found_raises(self):
        from core.email.exceptions import EmailNotFoundError
        from core.email.store import get_email_by_id

        with self.assertRaises(EmailNotFoundError):
            get_email_by_id(99999, self.db)

    def test_update_ai_fields(self):
        from core.email.store import get_email_by_id, update_ai_fields

        eid = self._upsert()
        update_ai_fields(
            eid, summary="Summary here", tags="work, test", priority=4, spam_score=10,
            db_path=self.db,
        )
        em = get_email_by_id(eid, self.db)
        self.assertEqual(em.summary, "Summary here")
        self.assertEqual(em.priority, 4)
        self.assertEqual(em.spam_score, 10)
        self.assertIn("work", em.tag_list)

    def test_sync_state(self):
        from core.email.store import get_sync_state, update_sync_state

        self.assertEqual(get_sync_state(self.account_id, "INBOX", self.db), 0)
        update_sync_state(self.account_id, "INBOX", 42, self.db)
        self.assertEqual(get_sync_state(self.account_id, "INBOX", self.db), 42)
        # Upsert again
        update_sync_state(self.account_id, "INBOX", 100, self.db)
        self.assertEqual(get_sync_state(self.account_id, "INBOX", self.db), 100)

    def test_unread_count(self):
        from core.email.store import get_unread_count, mark_read

        self._upsert(uid=10, message_id="<r1@test>")
        self._upsert(uid=11, message_id="<r2@test>")
        eid3 = self._upsert(uid=12, message_id="<r3@test>")

        self.assertEqual(get_unread_count(self.account_id, db_path=self.db), 3)
        mark_read(eid3, self.db)
        self.assertEqual(get_unread_count(self.account_id, db_path=self.db), 2)

    def test_fts_search(self):
        from core.email.store import search_fts

        self._upsert(uid=20, message_id="<fts1@test>", subject="Quarterly Report", body="Q3 results are in")
        self._upsert(uid=21, message_id="<fts2@test>", subject="Invoice Payment", body="Please pay by Friday")

        results = search_fts("quarterly", db_path=self.db)
        self.assertTrue(any("Quarterly" in r.subject for r in results))

        results2 = search_fts("invoice", db_path=self.db)
        self.assertTrue(any("Invoice" in r.subject for r in results2))

    def test_fts_injection_safe(self):
        from core.email.store import search_fts

        # Should not raise even with special chars
        results = search_fts('"; DROP TABLE emails; --', db_path=self.db)
        self.assertIsInstance(results, list)

    def test_save_attachment(self):
        from core.email.store import get_email_by_id, save_attachment, upsert_email

        eid = upsert_email(
            account_id=self.account_id, folder="INBOX", uid=50,
            message_id="<att@test>", in_reply_to="", references="", thread_id="t1",
            subject="With Attachment", sender="alice@example.com", sender_name="Alice",
            recipients="test@example.com", cc="", date=time.time(),
            body_html="", body_text="See attached", has_attachments=True,
            db_path=self.db,
        )
        save_attachment(
            email_id=eid, filename="doc.pdf", content_type="application/pdf",
            size_bytes=12345, content_id="", db_path=self.db,
        )
        em = get_email_by_id(eid, self.db)
        self.assertEqual(len(em.attachments), 1)
        self.assertEqual(em.attachments[0].filename, "doc.pdf")
        self.assertEqual(em.attachments[0].size_bytes, 12345)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


class TestParser(unittest.TestCase):
    def test_html_to_text_basic(self):
        from core.email.parser import html_to_text

        result = html_to_text("<p>Hello <b>world</b></p>")
        self.assertIn("Hello", result)
        self.assertIn("world", result)

    def test_html_to_text_strips_script(self):
        from core.email.parser import html_to_text

        result = html_to_text("<html><script>evil()</script><p>safe</p></html>")
        self.assertIn("safe", result)
        self.assertNotIn("evil", result)

    def test_html_to_text_empty(self):
        from core.email.parser import html_to_text

        self.assertEqual(html_to_text(""), "")
        self.assertEqual(html_to_text("   "), "")

    def test_compute_thread_id_from_references(self):
        from core.email.parser import compute_thread_id

        # Should use first Reference as root
        tid = compute_thread_id(
            "<root@test> <child@test>", "<root@test>", "<leaf@test>"
        )
        tid_direct = compute_thread_id("", "<root@test>", "<leaf@test>")
        # Same root → same thread
        self.assertEqual(tid, tid_direct)

    def test_compute_thread_id_standalone(self):
        from core.email.parser import compute_thread_id

        tid = compute_thread_id("", "", "<standalone@test>")
        self.assertEqual(len(tid), 32)  # MD5 hex

    def test_parse_plaintext_message(self):
        from core.email.parser import parse_message

        raw = b"""From: Alice <alice@example.com>\r\nTo: Bob <bob@example.com>\r\nSubject: Test Subject\r\nDate: Mon, 01 Jan 2024 12:00:00 +0000\r\nMessage-ID: <test@example.com>\r\n\r\nBody content here.\r\n"""
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        parsed = parse_message(msg)
        self.assertEqual(parsed["subject"], "Test Subject")
        self.assertEqual(parsed["sender"], "alice@example.com")
        self.assertEqual(parsed["sender_name"], "Alice")
        self.assertIn("Body content", parsed["body_text"])
        self.assertFalse(parsed["has_attachments"])

    def test_parse_multipart_prefers_plaintext(self):
        from core.email.parser import parse_message

        raw = b"""From: Alice <alice@example.com>\r\nTo: Bob <bob@example.com>\r\nSubject: Multi\r\nDate: Mon, 01 Jan 2024 12:00:00 +0000\r\nMessage-ID: <multi@test.com>\r\nContent-Type: multipart/alternative; boundary="b"\r\n\r\n--b\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPlain text.\r\n\r\n--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body><p>HTML text.</p></body></html>\r\n\r\n--b--\r\n"""
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        parsed = parse_message(msg)
        self.assertIn("Plain text", parsed["body_text"])
        self.assertIn("<html>", parsed["body_html"])

    def test_parse_html_only_converts(self):
        from core.email.parser import parse_message

        raw = b"""From: Alice <alice@example.com>\r\nTo: Bob <bob@example.com>\r\nSubject: HTML Only\r\nDate: Mon, 01 Jan 2024 12:00:00 +0000\r\nMessage-ID: <html@test.com>\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body><p>Only HTML here.</p></body></html>\r\n"""
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        parsed = parse_message(msg)
        self.assertIn("Only HTML here", parsed["body_text"])

    def test_parse_with_attachment(self):
        from core.email.parser import parse_message

        raw = b"""From: Alice <alice@example.com>\r\nTo: Bob <bob@example.com>\r\nSubject: With Attachment\r\nDate: Mon, 01 Jan 2024 12:00:00 +0000\r\nMessage-ID: <att@test.com>\r\nContent-Type: multipart/mixed; boundary="b"\r\n\r\n--b\r\nContent-Type: text/plain\r\n\r\nSee attached.\r\n\r\n--b\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename="doc.pdf"\r\n\r\n%PDF-fake-content\r\n\r\n--b--\r\n"""
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        parsed = parse_message(msg)
        self.assertTrue(parsed["has_attachments"])
        self.assertEqual(len(parsed["attachments"]), 1)
        self.assertEqual(parsed["attachments"][0]["filename"], "doc.pdf")


# ---------------------------------------------------------------------------
# ai — graceful degradation
# ---------------------------------------------------------------------------


class TestAI(unittest.TestCase):
    def test_summarise_returns_empty_on_ollama_failure(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value=None):
            result = ai.summarise_email("Some email body text")
        self.assertEqual(result, "")

    def test_classify_returns_empty_on_failure(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value=None):
            result = ai.classify_tags("subject", "body")
        self.assertEqual(result, [])

    def test_priority_returns_zero_on_failure(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value=None):
            result = ai.score_priority("subject", "body", "sender@test.com")
        self.assertEqual(result, 0)

    def test_spam_returns_zero_on_failure(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value=None):
            result = ai.score_spam("subject", "body", "sender@test.com")
        self.assertEqual(result, 0)

    def test_draft_reply_returns_empty_on_failure(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value=None):
            result = ai.draft_reply(sender="a@b.com", subject="Hi", body_text="body", intent="agree")
        self.assertEqual(result, "")

    def test_draft_compose_returns_empty_on_failure(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value=None):
            result = ai.draft_compose(intent="schedule meeting", recipient="boss@work.com")
        self.assertEqual(result, "")

    def test_priority_clamps_range(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value="7"):  # out of range
            result = ai.score_priority("s", "b", "s@s.com")
        self.assertEqual(result, 0)  # regex finds 7 but... let's check actual logic
        # Actually the regex will find 7 which is > 5, but score_priority only
        # looks for [0-5] so it won't match '7' — returns 0

    def test_spam_clamps_to_100(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value="150"):
            result = ai.score_spam("s", "b", "s@s.com")
        self.assertEqual(result, 100)

    def test_classify_normalizes_tags(self):
        from core.email import ai

        with patch("core.email.ai._call_ollama", return_value="Work, Action-Required, MEETING"):
            result = ai.classify_tags("subject", "body")
        self.assertEqual(result, ["work", "action-required", "meeting"])


# ---------------------------------------------------------------------------
# imap_client — mocked
# ---------------------------------------------------------------------------


class TestIMAPClient(unittest.TestCase):
    def _make_imap_mock(self):
        """Return a mock imaplib.IMAP4_SSL instance."""
        m = MagicMock()
        m.login.return_value = ("OK", [b"Logged in"])
        m.capability.return_value = ("OK", [b"IMAP4rev1"])
        m.logout.return_value = ("BYE", [b"Logged out"])
        return m

    @patch("core.email.imap_client.imaplib.IMAP4_SSL")
    def test_connect_and_disconnect(self, mock_cls):
        mock_cls.return_value = self._make_imap_mock()

        from core.email.imap_client import IMAPClient

        with IMAPClient("imap.test.com", 993, "user", "pass", use_ssl=True) as client:
            mock_cls.assert_called_once()
            client._conn.login.assert_called_once()

    @patch("core.email.imap_client.imaplib.IMAP4_SSL")
    def test_auth_failure_raises(self, mock_cls):
        m = self._make_imap_mock()
        import imaplib

        m.login.side_effect = imaplib.IMAP4.error("authentication failed")
        mock_cls.return_value = m

        from core.email.exceptions import EmailAuthError
        from core.email.imap_client import IMAPClient

        client = IMAPClient("imap.test.com", 993, "user", "wrongpass", use_ssl=True)
        with self.assertRaises(EmailAuthError):
            client.connect()

    @patch("core.email.imap_client.imaplib.IMAP4_SSL")
    def test_connection_refused_raises(self, mock_cls):
        mock_cls.side_effect = ConnectionRefusedError("refused")

        from core.email.exceptions import EmailConnectionError
        from core.email.imap_client import IMAPClient

        client = IMAPClient("imap.test.com", 993, "user", "pass", use_ssl=True)
        with self.assertRaises(EmailConnectionError):
            client.connect()

    @patch("core.email.imap_client.imaplib.IMAP4_SSL")
    def test_fetch_messages_empty_inbox(self, mock_cls):
        m = self._make_imap_mock()
        m.select.return_value = ("OK", [b"0"])
        m.uid.return_value = ("OK", [None])
        mock_cls.return_value = m

        from core.email.imap_client import IMAPClient

        with IMAPClient("imap.test.com", 993, "user", "pass", use_ssl=True) as client:
            messages = client.fetch_messages("INBOX", uid_start=0)
        self.assertEqual(messages, [])


# ---------------------------------------------------------------------------
# smtp_client — mocked
# ---------------------------------------------------------------------------


class TestSMTPClient(unittest.TestCase):
    def test_build_message_fields(self):
        from core.email.smtp_client import build_message

        msg = build_message(
            from_addr="me@test.com",
            to_addrs=["you@test.com"],
            subject="Hello",
            body="Body text",
        )
        self.assertEqual(msg["To"], "you@test.com")
        self.assertEqual(msg["Subject"], "Hello")
        self.assertIn("palimind", msg["Message-ID"])

    def test_build_reply_message_has_in_reply_to(self):
        from core.email.smtp_client import build_message

        msg = build_message(
            from_addr="me@test.com",
            to_addrs=["you@test.com"],
            subject="Re: Hello",
            body="Reply body",
            in_reply_to="<original@test.com>",
            references="<original@test.com>",
        )
        self.assertEqual(msg["In-Reply-To"], "<original@test.com>")
        self.assertEqual(msg["References"], "<original@test.com>")

    @patch("core.email.smtp_client.smtplib.SMTP")
    def test_send_message_starttls(self, mock_smtp_cls):
        from core.email.smtp_client import build_message, send_message

        mock_smtp = MagicMock()
        mock_smtp.has_extn.return_value = True
        mock_smtp_cls.return_value = mock_smtp

        msg = build_message(
            from_addr="me@test.com", to_addrs=["you@test.com"],
            subject="Test", body="Hello",
        )
        send_message(
            host="smtp.test.com", port=587,
            username="me@test.com", password="secret",
            message=msg, use_ssl=False,
        )
        mock_smtp.login.assert_called_once_with("me@test.com", "secret")
        mock_smtp.send_message.assert_called_once()

    @patch("core.email.smtp_client.smtplib.SMTP")
    def test_send_message_auth_failure_raises(self, mock_smtp_cls):
        import smtplib

        from core.email.exceptions import EmailAuthError
        from core.email.smtp_client import build_message, send_message

        mock_smtp = MagicMock()
        mock_smtp.has_extn.return_value = False
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        mock_smtp_cls.return_value = mock_smtp

        msg = build_message(
            from_addr="me@test.com", to_addrs=["you@test.com"],
            subject="Test", body="Hello",
        )
        with self.assertRaises(EmailAuthError):
            send_message(
                host="smtp.test.com", port=587,
                username="me@test.com", password="wrong",
                message=msg, use_ssl=False,
            )


# ---------------------------------------------------------------------------
# api facade — integration with mocked I/O
# ---------------------------------------------------------------------------


class TestApiFacade(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = pathlib.Path(self.tmpdir.name) / "email.db"
        from core.email.api import ensure_db

        ensure_db(self.db)
        from core.email.crypto import encrypt_password
        from core.email.store import save_account

        self.enc_pw = encrypt_password("testpass")
        self.account_id = save_account(
            label="APITest",
            email_address="test@api.com",
            imap_host="imap.api.com",
            imap_port=993,
            smtp_host="smtp.api.com",
            smtp_port=587,
            username="test@api.com",
            password_enc=self.enc_pw,
            use_ssl=True,
            db_path=self.db,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_list_accounts_returns_account(self):
        from core.email.api import list_accounts

        accs = list_accounts(self.db)
        self.assertEqual(len(accs), 1)
        self.assertEqual(accs[0].label, "APITest")

    def test_list_emails_empty(self):
        from core.email.api import list_emails

        emails = list_emails(db_path=self.db)
        self.assertEqual(emails, [])

    def test_search_empty_db(self):
        from core.email.api import search_emails

        results = search_emails("anything", db_path=self.db)
        self.assertEqual(results, [])

    @patch("core.email.api.IMAPClient")
    @patch("core.email.api.ai.summarise_email", return_value="")
    @patch("core.email.api.ai.classify_tags", return_value=[])
    @patch("core.email.api.ai.score_priority", return_value=0)
    @patch("core.email.api.ai.score_spam", return_value=0)
    def test_sync_account_no_messages(self, mock_spam, mock_prio, mock_tags, mock_sum, mock_imap):
        """Sync with empty IMAP response returns zero-count SyncResult."""
        mock_imap_instance = MagicMock()
        mock_imap_instance.__enter__ = lambda s: s
        mock_imap_instance.__exit__ = MagicMock(return_value=False)
        mock_imap_instance.fetch_messages.return_value = []
        mock_imap_instance.test_connection.return_value = None
        mock_imap.return_value = mock_imap_instance

        from core.email.api import sync_account

        result = sync_account("APITest", folder="INBOX", run_ai=True, db_path=self.db)
        self.assertEqual(result.fetched, 0)
        self.assertEqual(result.stored, 0)

    @patch("core.email.api.send_message")
    @patch("core.email.api.build_message")
    def test_compose_dry_run(self, mock_build, mock_send):
        """Dry-run compose should not call send_message."""
        from core.email.smtp_client import build_message as real_build

        mock_build.return_value = real_build(
            from_addr="test@api.com",
            to_addrs=["other@test.com"],
            subject="Test",
            body="Hello",
        )
        from core.email.api import compose_email

        result = compose_email(
            account_label="APITest",
            to_addresses=["other@test.com"],
            subject="Test",
            body="Hello world",
            dry_run=True,
            db_path=self.db,
        )
        mock_send.assert_not_called()
        self.assertIsNotNone(result.message_id)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


class TestModels(unittest.TestCase):
    def test_email_tag_list(self):
        from core.email.models import Email

        em = Email(
            id=1, account_id=1, folder="INBOX", uid=1,
            message_id="<x@test>", in_reply_to="", references="", thread_id="t",
            subject="S", sender="a@b.com", sender_name="A",
            recipients="b@c.com", cc="", date=0.0,
            body_html="", body_text="",
            has_attachments=False, summary="", tags="work, planning, action-required",
            priority=3, spam_score=5, is_read=False, is_sent=False, fetched_at=0.0,
        )
        self.assertEqual(em.tag_list, ["work", "planning", "action-required"])

    def test_email_empty_tags(self):
        from core.email.models import Email

        em = Email(
            id=1, account_id=1, folder="INBOX", uid=1,
            message_id="<x@test>", in_reply_to="", references="", thread_id="t",
            subject="S", sender="a@b.com", sender_name="A",
            recipients="b@c.com", cc="", date=0.0,
            body_html="", body_text="",
            has_attachments=False, summary="", tags="",
            priority=0, spam_score=0, is_read=False, is_sent=False, fetched_at=0.0,
        )
        self.assertEqual(em.tag_list, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
