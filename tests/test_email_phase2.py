"""Tests for PaliMind Email Module — Phase 2."""
from __future__ import annotations
import pathlib, tempfile, time, unittest
from unittest.mock import patch, MagicMock


def _make_db():
    td = tempfile.TemporaryDirectory()
    db = pathlib.Path(td.name) / "email.db"
    from core.email.store import init_email_db
    init_email_db(db)
    from core.email.store_p2 import apply_p2_migrations
    apply_p2_migrations(db)
    from core.email.crypto import encrypt_password
    from core.email.store import save_account
    aid = save_account(label="T", email_address="t@t.com",
        imap_host="imap.t.com", imap_port=993, smtp_host="smtp.t.com",
        smtp_port=587, username="t@t.com", password_enc=encrypt_password("p"),
        use_ssl=True, db_path=db)
    return td, db, aid


def _ins(db, aid, *, uid=1, mid="<m@t>", subj="Sub", body="body", sender="a@b.com"):
    from core.email.store import upsert_email
    return upsert_email(account_id=aid, folder="INBOX", uid=uid,
        message_id=mid, in_reply_to="", references="", thread_id="th",
        subject=subj, sender=sender, sender_name="A", recipients="t@t.com",
        cc="", date=time.time(), body_html="", body_text=body,
        has_attachments=False, db_path=db)


class TestP2Migrations(unittest.TestCase):
    def test_tables_created(self):
        td, db, _ = _make_db()
        import sqlite3
        conn = sqlite3.connect(str(db))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close(); td.cleanup()
        for t in ("email_p2_meta", "reminders", "spam_prefs", "contact_stats_cache"):
            self.assertIn(t, tables)

    def test_idempotent(self):
        td, db, _ = _make_db()
        from core.email.store_p2 import apply_p2_migrations
        apply_p2_migrations(db)  # second call must not raise
        td.cleanup()


class TestP2Meta(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()
        self.eid = _ins(self.db, self.aid, uid=1, mid="<p2@t>")

    def tearDown(self): self.td.cleanup()

    def test_upsert_and_get(self):
        from core.email.store_p2 import upsert_p2_meta, get_p2_meta
        upsert_p2_meta(self.eid, needs_reply=True, reply_confidence=80,
            reply_reason="has question", db_path=self.db)
        m = get_p2_meta(self.eid, self.db)
        self.assertTrue(m["needs_reply"])
        self.assertEqual(m["reply_confidence"], 80)

    def test_spam_status(self):
        from core.email.store_p2 import upsert_p2_meta, get_p2_meta
        upsert_p2_meta(self.eid, spam_status="spam", spam_confidence=90,
            spam_reason="phishing", db_path=self.db)
        m = get_p2_meta(self.eid, self.db)
        self.assertEqual(m["spam_status"], "spam")

    def test_newsletter_flag(self):
        from core.email.store_p2 import upsert_p2_meta, get_newsletters
        upsert_p2_meta(self.eid, is_newsletter=True, newsletter_conf=95, db_path=self.db)
        nls = get_newsletters(db_path=self.db)
        self.assertTrue(any(n["id"] == self.eid for n in nls))

    def test_needs_reply_list(self):
        from core.email.store_p2 import upsert_p2_meta, get_emails_needing_reply
        upsert_p2_meta(self.eid, needs_reply=True, reply_confidence=70, db_path=self.db)
        items = get_emails_needing_reply(db_path=self.db)
        self.assertTrue(any(i["id"] == self.eid for i in items))


class TestReminders(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()
        self.eid = _ins(self.db, self.aid, uid=2, mid="<r@t>")

    def tearDown(self): self.td.cleanup()

    def test_create_and_list(self):
        from core.email.store_p2 import create_reminder, get_reminders
        rid = create_reminder(self.eid, note="Follow up", db_path=self.db)
        self.assertIsNotNone(rid)
        rs = get_reminders(db_path=self.db)
        self.assertTrue(any(r["id"] == rid for r in rs))

    def test_dismiss(self):
        from core.email.store_p2 import create_reminder, dismiss_reminder, get_reminders
        rid = create_reminder(self.eid, note="test", db_path=self.db)
        dismiss_reminder(rid, self.db)
        active = get_reminders(include_done=False, db_path=self.db)
        self.assertFalse(any(r["id"] == rid for r in active))

    def test_with_due_date(self):
        from core.email.store_p2 import create_reminder, get_reminders
        due = time.time() + 86400
        rid = create_reminder(self.eid, note="due tmrw", due_at=due, db_path=self.db)
        rs = get_reminders(db_path=self.db)
        r = next(r for r in rs if r["id"] == rid)
        self.assertAlmostEqual(r["due_at"], due, delta=1)


class TestSpamPrefs(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()

    def tearDown(self): self.td.cleanup()

    def test_whitelist(self):
        from core.email.store_p2 import add_spam_pref, get_spam_pref
        add_spam_pref("safe@good.com", "whitelist", self.db)
        self.assertEqual(get_spam_pref("safe@good.com", self.db), "whitelist")

    def test_blacklist(self):
        from core.email.store_p2 import add_spam_pref, get_spam_pref
        add_spam_pref("bad@spam.com", "blacklist", self.db)
        self.assertEqual(get_spam_pref("bad@spam.com", self.db), "blacklist")

    def test_upsert_changes_type(self):
        from core.email.store_p2 import add_spam_pref, get_spam_pref
        add_spam_pref("x@y.com", "whitelist", self.db)
        add_spam_pref("x@y.com", "blacklist", self.db)
        self.assertEqual(get_spam_pref("x@y.com", self.db), "blacklist")

    def test_unknown_sender_returns_none(self):
        from core.email.store_p2 import get_spam_pref
        self.assertIsNone(get_spam_pref("nobody@nowhere.com", self.db))

    def test_invalid_type_raises(self):
        from core.email.store_p2 import add_spam_pref
        with self.assertRaises(ValueError):
            add_spam_pref("x@y.com", "invalid", self.db)

    def test_get_all(self):
        from core.email.store_p2 import add_spam_pref, get_all_spam_prefs
        add_spam_pref("a@a.com", "whitelist", self.db)
        add_spam_pref("b@b.com", "blacklist", self.db)
        prefs = get_all_spam_prefs(self.db)
        self.assertEqual(len(prefs), 2)


class TestSpamClassification(unittest.TestCase):
    def test_heuristic_phishing(self):
        from core.email.ai_p2 import _heuristic_spam_score
        score, signals = _heuristic_spam_score(
            "Verify your account now!", "hack@suspicious.xyz",
            "Click here to confirm your identity or your account will be suspended.")
        self.assertGreater(score, 30)
        self.assertTrue(len(signals) > 0)

    def test_whitelist_overrides_to_safe(self):
        from core.email.ai_p2 import compute_enhanced_spam_score
        with patch("core.email.ai_p2.ai_score_spam", return_value=90):
            status, conf, reason = compute_enhanced_spam_score(
                "WINNER!", "spam@evil.com", "You won!", sender_pref="whitelist")
        self.assertEqual(status, "safe")

    def test_blacklist_overrides_to_spam(self):
        from core.email.ai_p2 import compute_enhanced_spam_score
        status, conf, _ = compute_enhanced_spam_score(
            "Hello", "friend@good.com", "Nice email", sender_pref="blacklist")
        self.assertEqual(status, "spam")
        self.assertEqual(conf, 100)

    def test_ai_spam_integration(self):
        from core.email.ai_p2 import compute_enhanced_spam_score
        with patch("core.email.ai_p2.ai_score_spam", return_value=80):
            status, conf, _ = compute_enhanced_spam_score(
                "Big prize", "x@spam.top", "You won a million dollars!")
        self.assertEqual(status, "spam")

    def test_clean_email_is_safe(self):
        from core.email.ai_p2 import compute_enhanced_spam_score
        with patch("core.email.ai_p2.ai_score_spam", return_value=5):
            status, _, _ = compute_enhanced_spam_score(
                "Q3 report attached", "boss@company.com", "Please review the report.")
        self.assertEqual(status, "safe")


class TestNewsletterDetection(unittest.TestCase):
    def test_list_unsubscribe_header(self):
        from core.email.ai_p2 import detect_newsletter
        is_nl, conf = detect_newsletter("Weekly digest", "news@co.com", "body",
            list_unsubscribe="<mailto:unsub@co.com>")
        self.assertTrue(is_nl)
        self.assertGreaterEqual(conf, 90)

    def test_unsubscribe_keyword(self):
        from core.email.ai_p2 import _heuristic_newsletter_confidence
        conf = _heuristic_newsletter_confidence(
            "Weekly Newsletter", "news@co.com",
            "Click here to unsubscribe from this mailing list.")
        self.assertGreaterEqual(conf, 60)

    def test_normal_email(self):
        from core.email.ai_p2 import _heuristic_newsletter_confidence
        conf = _heuristic_newsletter_confidence(
            "Quick question", "colleague@work.com",
            "Hey, can we sync tomorrow at 2pm?")
        self.assertLess(conf, 40)


class TestNeedsReplyHeuristics(unittest.TestCase):
    def test_question_mark(self):
        from core.email.ai_p2 import _heuristic_needs_reply
        needs, conf, reason = _heuristic_needs_reply(
            "Checking in", "Can you confirm the meeting?")
        self.assertTrue(needs)
        self.assertGreater(conf, 0)

    def test_please_reply(self):
        from core.email.ai_p2 import _heuristic_needs_reply
        needs, conf, _ = _heuristic_needs_reply(
            "Action required", "Please reply by end of day.")
        self.assertTrue(needs)

    def test_plain_statement(self):
        from core.email.ai_p2 import _heuristic_needs_reply
        needs, conf, _ = _heuristic_needs_reply(
            "FYI", "The meeting notes are attached for your reference.")
        self.assertFalse(needs)

    def test_ai_failure_falls_back_to_heuristic(self):
        from core.email.ai_p2 import detect_needs_reply
        with patch("core.email.ai_p2._call_ollama", return_value=None):
            needs, conf, reason = detect_needs_reply(
                "Interview scheduled", "recruiter@co.com", "Please confirm your availability.")
        self.assertIsInstance(needs, bool)
        self.assertIsInstance(conf, int)


class TestContactStats(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()
        for i in range(5):
            _ins(self.db, self.aid, uid=i+10, mid=f"<c{i}@t>",
                 sender="alice@example.com", subj=f"Mail {i}")

    def tearDown(self): self.td.cleanup()

    def test_rebuild_and_query(self):
        from core.email.store_p2 import rebuild_contact_stats, get_contact_stats
        rebuild_contact_stats(self.db)
        stats = get_contact_stats(db_path=self.db)
        senders = [s["sender"] for s in stats]
        self.assertIn("alice@example.com", senders)

    def test_most_frequent_top(self):
        from core.email.store_p2 import rebuild_contact_stats, get_contact_stats
        rebuild_contact_stats(self.db)
        stats = get_contact_stats(db_path=self.db)
        self.assertTrue(stats[0]["emails_received"] >= 1)


class TestEnhancedStats(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()
        eid = _ins(self.db, self.aid, uid=1, mid="<s1@t>")
        from core.email.store_p2 import upsert_p2_meta
        upsert_p2_meta(eid, spam_status="spam", spam_confidence=85, db_path=self.db)

    def tearDown(self): self.td.cleanup()

    def test_stats_keys(self):
        from core.email.store_p2 import get_email_stats
        s = get_email_stats(self.db)
        for key in ("total", "unread", "sent", "spam_count", "suspicious_count",
                    "newsletter_count", "needs_reply_count", "reminder_count",
                    "storage_bytes", "last_sync_at", "top_contacts"):
            self.assertIn(key, s)

    def test_spam_count_correct(self):
        from core.email.store_p2 import get_email_stats
        s = get_email_stats(self.db)
        self.assertEqual(s["spam_count"], 1)


class TestAskQuestion(unittest.TestCase):
    def test_no_emails_returns_fallback(self):
        from core.email.ai_p2 import answer_email_question
        with patch("core.email.ai_p2._call_ollama", return_value=None):
            ans = answer_email_question("Who emailed me?", "")
        self.assertIn("No relevant", ans)

    def test_with_context_calls_ollama(self):
        from core.email.ai_p2 import answer_email_question
        with patch("core.email.ai_p2._call_ollama", return_value="Alice emailed you."):
            ans = answer_email_question("Who emailed me?", "[#1] From: Alice | Subject: Hi")
        self.assertEqual(ans, "Alice emailed you.")

    def test_keyword_extraction(self):
        from core.email.api_p2 import _extract_search_keywords
        kw = _extract_search_keywords("Which recruiter emailed me last week?")
        self.assertIn("recruiter", kw)
        self.assertNotIn("which", kw)
        self.assertNotIn("me", kw)


class TestStyleDrafting(unittest.TestCase):
    def test_no_samples_falls_back(self):
        from core.email.ai_p2 import draft_with_style
        with patch("core.email.ai_p2._call_ollama", return_value=None):
            result = draft_with_style("schedule meeting", "boss@co.com", "")
        self.assertEqual(result, "")

    def test_returns_draft_on_success(self):
        from core.email.ai_p2 import draft_with_style
        with patch("core.email.ai_p2._call_ollama", return_value="Hi,\n\nLet's meet.\n\nBest"):
            result = draft_with_style("schedule meeting", "boss@co.com", "Past email sample")
        self.assertIn("meet", result)


class TestTodayInbox(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()
        _ins(self.db, self.aid, uid=5, mid="<t5@t>",
             subj="Meeting tomorrow", body="Let's meet at 10am")

    def tearDown(self): self.td.cleanup()

    def test_today_returns_structure(self):
        from core.email.store_p2 import get_today_emails
        data = get_today_emails(db_path=self.db)
        for key in ("all", "unread", "high_priority", "needs_reply",
                    "meetings", "finance", "newsletters", "spam", "due_reminders"):
            self.assertIn(key, data)

    def test_meetings_detected(self):
        from core.email.store_p2 import get_today_emails
        data = get_today_emails(db_path=self.db)
        self.assertTrue(any("meeting" in e.get("subject", "").lower()
                            for e in data["meetings"]))


class TestSpamApiWorkflow(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()
        self.eid = _ins(self.db, self.aid, uid=9, mid="<sp@t>",
            sender="spammer@evil.xyz", subj="FREE MONEY",
            body="Click here to claim your prize now!")

    def tearDown(self): self.td.cleanup()

    def test_scan_spam_flags_email(self):
        from core.email.api_p2 import scan_spam
        with patch("core.email.ai_p2.ai_score_spam", return_value=75):
            flagged = scan_spam(limit=10, db_path=self.db)
        self.assertGreaterEqual(flagged, 1)

    def test_whitelist_overrides(self):
        from core.email.api_p2 import add_spam_whitelist, scan_spam
        from core.email.store_p2 import get_p2_meta
        add_spam_whitelist("spammer@evil.xyz", self.db)
        with patch("core.email.ai_p2.ai_score_spam", return_value=90):
            scan_spam(limit=10, db_path=self.db)
        m = get_p2_meta(self.eid, self.db)
        if m:
            self.assertEqual(m.get("spam_status", "safe"), "safe")

    def test_review_workflow(self):
        from core.email.api_p2 import mark_spam_reviewed
        from core.email.store_p2 import upsert_p2_meta, get_p2_meta
        upsert_p2_meta(self.eid, spam_status="suspicious",
                       spam_confidence=50, db_path=self.db)
        mark_spam_reviewed(self.eid, is_spam=False, db_path=self.db)
        m = get_p2_meta(self.eid, self.db)
        self.assertEqual(m["spam_status"], "safe")
        self.assertEqual(m["spam_reviewed"], 1)


# ---------------------------------------------------------------------------
# Phase 1 regression tests — verify nothing is broken
# ---------------------------------------------------------------------------

class TestPhase1Regression(unittest.TestCase):
    def setUp(self):
        self.td, self.db, self.aid = _make_db()

    def tearDown(self): self.td.cleanup()

    def test_upsert_and_get_email(self):
        from core.email.store import get_email_by_id
        eid = _ins(self.db, self.aid, uid=100, mid="<reg@t>", subj="Regression")
        em = get_email_by_id(eid, self.db)
        self.assertEqual(em.subject, "Regression")

    def test_fts_search_still_works(self):
        from core.email.store import search_fts
        _ins(self.db, self.aid, uid=101, mid="<fts@t>",
             subj="Quarterly Report", body="Q3 results")
        results = search_fts("quarterly", db_path=self.db)
        self.assertTrue(any("Quarterly" in r.subject for r in results))

    def test_sync_state(self):
        from core.email.store import get_sync_state, update_sync_state
        update_sync_state(self.aid, "INBOX", 42, self.db)
        self.assertEqual(get_sync_state(self.aid, "INBOX", self.db), 42)

    def test_mark_read(self):
        from core.email.store import get_email_by_id, mark_read
        eid = _ins(self.db, self.aid, uid=102, mid="<rd@t>")
        mark_read(eid, self.db)
        em = get_email_by_id(eid, self.db)
        self.assertTrue(em.is_read)

    def test_update_ai_fields(self):
        from core.email.store import get_email_by_id, update_ai_fields
        eid = _ins(self.db, self.aid, uid=103, mid="<ai@t>")
        update_ai_fields(eid, summary="Test summary", tags="work",
                         priority=4, spam_score=10, db_path=self.db)
        em = get_email_by_id(eid, self.db)
        self.assertEqual(em.summary, "Test summary")
        self.assertEqual(em.priority, 4)

    def test_crypto_roundtrip(self):
        from core.email.crypto import encrypt_password, decrypt_password
        for pw in ["simple", "c0mpl€x!", ""]:
            self.assertEqual(decrypt_password(encrypt_password(pw)), pw)

    def test_p2_migrations_dont_break_p1(self):
        """Applying p2 migrations must not drop or corrupt Phase 1 tables."""
        eid = _ins(self.db, self.aid, uid=200, mid="<compat@t>")
        from core.email.store_p2 import apply_p2_migrations
        apply_p2_migrations(self.db)
        from core.email.store import get_email_by_id
        em = get_email_by_id(eid, self.db)
        self.assertEqual(em.id, eid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
