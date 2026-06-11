"""Phase 2 AI functions for the PaliMind email module.

Extends core/email/ai.py with new inference functions.
All functions degrade gracefully — never raises, returns safe defaults.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from core.email.ai import _call_ollama, _render_prompt


# ---------------------------------------------------------------------------
# Needs-reply detection
# ---------------------------------------------------------------------------

def detect_needs_reply(
    subject: str,
    sender: str,
    body_text: str,
) -> tuple[bool, int, str]:
    """Return (needs_reply, confidence 0-100, reason).

    Uses AI when available; falls back to heuristics only.
    """
    # ---- Heuristic fast-path ------------------------------------------------
    heuristic_result = _heuristic_needs_reply(subject, body_text)

    prompt = _render_prompt(
        "needs_reply",
        subject=subject[:200],
        sender=sender[:200],
        body_text=body_text[:3000],
    )
    raw = _call_ollama(
        "You are an email triage assistant. Respond only with JSON.",
        prompt,
    )
    if raw:
        try:
            data = _parse_json(raw)
            needs = bool(data.get("needs_reply", False))
            conf = min(100, max(0, int(data.get("confidence", 50))))
            reason = str(data.get("reason", ""))[:200]
            return needs, conf, reason
        except Exception:
            pass

    return heuristic_result


def _heuristic_needs_reply(subject: str, body_text: str) -> tuple[bool, int, str]:
    """Rule-based needs-reply detection (no AI required)."""
    text = (subject + " " + body_text).lower()
    patterns = [
        (r"\?\s*$", 70, "ends with a question"),
        (r"\bplease (reply|respond|confirm|let me know)\b", 80, "explicit reply request"),
        (r"\bcan you\b", 65, "contains 'can you'"),
        (r"\bcould you\b", 65, "contains 'could you'"),
        (r"\baction required\b", 85, "action required"),
        (r"\bdeadline\b", 75, "contains deadline"),
        (r"\binterview\b", 80, "interview mention"),
        (r"\bjob offer\b", 90, "job offer"),
        (r"\bfollowing up\b", 60, "follow-up email"),
        (r"\brsvp\b", 85, "RSVP requested"),
    ]
    for pattern, confidence, reason in patterns:
        if re.search(pattern, text):
            return True, confidence, reason
    return False, 0, "no reply signals detected"


# ---------------------------------------------------------------------------
# Newsletter detection
# ---------------------------------------------------------------------------

def detect_newsletter(
    subject: str,
    sender: str,
    body_text: str,
    list_unsubscribe: str = "",
    list_id: str = "",
) -> tuple[bool, int]:
    """Return (is_newsletter, confidence 0-100).

    Combines header heuristics with optional AI classification.
    """
    # Strong header signals — no AI needed
    if list_unsubscribe or list_id:
        return True, 95

    heuristic_conf = _heuristic_newsletter_confidence(subject, sender, body_text)
    if heuristic_conf >= 80:
        return True, heuristic_conf

    # AI classification
    prompt = _render_prompt(
        "newsletter_detect",
        subject=subject[:200],
        sender=sender[:200],
        body_text=body_text[:2000],
    )
    raw = _call_ollama(
        "You are an email classifier. Respond only with JSON.",
        prompt,
    )
    if raw:
        try:
            data = _parse_json(raw)
            is_nl = bool(data.get("is_newsletter", False))
            conf = min(100, max(0, int(data.get("confidence", 50))))
            # Blend with heuristic
            blended = max(heuristic_conf, conf) if is_nl else min(heuristic_conf, 100 - conf)
            return is_nl or blended >= 60, blended
        except Exception:
            pass

    return heuristic_conf >= 60, heuristic_conf


def _heuristic_newsletter_confidence(subject: str, sender: str, body_text: str) -> int:
    """Return 0-100 newsletter confidence from heuristics alone."""
    score = 0
    text = (subject + " " + body_text).lower()

    # Subject patterns
    if re.search(r"\b(newsletter|digest|weekly|monthly|bulletin|update)\b", subject.lower()):
        score += 30
    if re.search(r"\b(unsubscribe|opt.out|manage preferences|email preferences)\b", text):
        score += 35
    if re.search(r"\b(dear subscriber|hi there|hello everyone|dear member)\b", text):
        score += 20
    if re.search(r"\b(view in browser|view online|web version)\b", text):
        score += 20
    if re.search(r"\b(marketing@|newsletter@|noreply@|no-reply@)\b", sender.lower()):
        score += 25
    if len(body_text) > 2000:
        score += 10  # long bulk emails

    return min(score, 100)


# ---------------------------------------------------------------------------
# Spam analysis (enhanced)
# ---------------------------------------------------------------------------

def compute_enhanced_spam_score(
    subject: str,
    sender: str,
    body_text: str,
    list_unsubscribe: str = "",
    sender_pref: Optional[str] = None,  # 'whitelist'/'blacklist'/None
) -> tuple[str, int, str]:
    """Return (status, confidence, reason) where status is 'safe'/'suspicious'/'spam'.

    Combines heuristics + existing AI spam score.
    Respects whitelist/blacklist overrides.
    """
    # Whitelist/blacklist override
    if sender_pref == "whitelist":
        return "safe", 0, "sender is whitelisted"
    if sender_pref == "blacklist":
        return "spam", 100, "sender is blacklisted"

    heuristic_score, heuristic_signals = _heuristic_spam_score(subject, sender, body_text)

    # Get AI score if available
    from core.email.ai import score_spam as ai_score_spam
    ai_score = ai_score_spam(subject, body_text, sender)

    # Blend: max of heuristic and AI
    blended = max(heuristic_score, ai_score)
    primary_reason = heuristic_signals[0] if heuristic_signals else "AI spam score"

    if blended >= 70:
        return "spam", blended, primary_reason
    elif blended >= 35:
        return "suspicious", blended, primary_reason
    else:
        return "safe", blended, "no significant spam signals"


def _heuristic_spam_score(
    subject: str,
    sender: str,
    body_text: str,
) -> tuple[int, list[str]]:
    """Return (score 0-100, list of detected signal descriptions)."""
    score = 0
    signals: list[str] = []
    text = (subject + " " + body_text).lower()

    checks = [
        (r"\b(click here|act now|limited time|urgent|winner|congratulations)\b", 20, "urgency/prize language"),
        (r"\b(verify your account|confirm your identity|suspended|locked)\b", 25, "phishing language"),
        (r"\b(free money|cash prize|lottery|inheritance)\b", 30, "scam keywords"),
        (r"http[s]?://[^\s]{0,10}\b(bit\.ly|tinyurl|goo\.gl|t\.co)\b", 15, "shortened URLs"),
        (r"\b(unsubscribe from all|remove me|stop emails)\b", 10, "bulk email pattern"),
        (r"[\$£€]\s*\d+[\.,]?\d*", 15, "monetary amounts in subject/body"),
        (r"[A-Z]{5,}", 10, "excessive capitalization"),
        (r"!{2,}", 10, "excessive exclamation marks"),
    ]
    # Suspicious sender patterns
    sender_checks = [
        (r"@.*\.(xyz|top|click|win|site|online)$", 20, "suspicious TLD"),
        (r"noreply|no-reply|donotreply", 5, "no-reply sender"),
        (r"\d{4,}@", 15, "numeric sender username"),
    ]

    for pattern, pts, label in checks:
        if re.search(pattern, text):
            score += pts
            signals.append(label)

    for pattern, pts, label in sender_checks:
        if re.search(pattern, sender.lower()):
            score += pts
            signals.append(label)

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# Semantic Q&A
# ---------------------------------------------------------------------------

def answer_email_question(
    question: str,
    email_context: str,
) -> str:
    """Answer a natural language question using retrieved email context.

    Returns answer text or a fallback message if AI unavailable.
    """
    if not email_context.strip():
        return "No relevant emails found for this query."

    prompt = _render_prompt(
        "ask",
        question=question[:500],
        email_context=email_context[:8000],
    )
    result = _call_ollama(
        "You are a helpful email assistant with access to the user's inbox.",
        prompt,
    )
    return result or _keyword_fallback_answer(question, email_context)


def _keyword_fallback_answer(question: str, context: str) -> str:
    """Return a simple fallback when AI is unavailable."""
    lines = [l for l in context.split("\n") if l.strip()]
    return (
        f"[AI unavailable] Found {len(lines)} relevant email(s). "
        "Run 'pm email search' with specific keywords for detailed results."
    )


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------

def summarise_today(email_context: str) -> str:
    """Generate an executive daily inbox summary."""
    if not email_context.strip():
        return "No emails received in the last 24 hours."

    prompt = _render_prompt("today_summary", email_context=email_context[:6000])
    result = _call_ollama(
        "You are a concise executive assistant.",
        prompt,
    )
    return result or "AI summary unavailable. Check individual categories below."


# ---------------------------------------------------------------------------
# Style-aware drafting
# ---------------------------------------------------------------------------

def draft_with_style(
    intent: str,
    recipient: str,
    style_examples: str,
) -> str:
    """Draft an email matching the user's personal style from sent examples."""
    prompt = _render_prompt(
        "style_draft",
        intent=intent[:500],
        recipient=recipient[:200],
        style_examples=style_examples[:4000],
    )
    result = _call_ollama(
        "You are an expert at mimicking personal email writing styles.",
        prompt,
    )
    return result or ""


# ---------------------------------------------------------------------------
# Reminder auto-summary
# ---------------------------------------------------------------------------

def auto_summarise_reminder(subject: str, sender: str, body_text: str) -> str:
    """Generate a one-line reminder note from email content."""
    prompt = _render_prompt(
        "reminder_summary",
        subject=subject[:200],
        sender=sender[:200],
        body_text=body_text[:1000],
    )
    result = _call_ollama(
        "You are a concise task extractor.",
        prompt,
    )
    if result:
        # Trim to single line
        return result.split("\n")[0].strip()[:120]
    return f"Follow up on: {subject[:80]}"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict:
    """Extract first JSON object from potentially noisy LLM output."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Extract JSON block
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"No JSON found in: {text[:200]}")
