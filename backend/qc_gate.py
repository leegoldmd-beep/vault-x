"""
Pre-Send QC Gate — Quality Control for all outgoing emails and video avatars.
Screens content before sending. Holds flagged items for review.
"""

import re
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# QC Rules
PLACEHOLDER_PATTERNS = [
    r"\{\{[\w_]+\}\}",           # {{variable}} unfilled
    r"\{[\w_]+\}",               # {variable} unfilled
    r"\[INSERT\s",               # [INSERT ...]
    r"\[YOUR\s",                 # [YOUR ...]
    r"PLACEHOLDER",              # literal placeholder
    r"TODO",                     # TODO left in
    r"FIXME",                    # FIXME left in
    r"Lorem ipsum",              # Lorem ipsum
]

UNPROFESSIONAL_PATTERNS = [
    r"(?i)\basdf\b",
    r"(?i)\btest\s*email\b",
    r"(?i)\bxxx+\b",
    r"(?i)\bblah\b",
]

REQUIRED_FIELDS = {
    "subject": "Email subject is empty",
    "body": "Email body is empty",
}


def qc_check_email(subject: str, body: str, recipient_email: str, contact_name: str = "", company_name: str = "") -> dict:
    """
    Run QC checks on an email before sending.
    Returns: {passed: bool, issues: [...], severity: 'pass'|'warning'|'hold'}
    """
    issues = []

    # 1. Empty fields
    if not subject or not subject.strip():
        issues.append({"type": "missing_field", "severity": "hold", "message": "Subject line is empty"})
    if not body or not body.strip():
        issues.append({"type": "missing_field", "severity": "hold", "message": "Email body is empty"})

    # 2. Recipient validation
    if not recipient_email or "@" not in recipient_email:
        issues.append({"type": "invalid_recipient", "severity": "hold", "message": f"Invalid recipient email: '{recipient_email}'"})
    elif not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", recipient_email):
        issues.append({"type": "suspect_email", "severity": "warning", "message": f"Recipient email looks suspicious: '{recipient_email}'"})

    # 3. Unfilled placeholders
    full_text = f"{subject} {body}"
    for pattern in PLACEHOLDER_PATTERNS:
        matches = re.findall(pattern, full_text)
        if matches:
            issues.append({
                "type": "unfilled_placeholder",
                "severity": "hold",
                "message": f"Unfilled placeholder found: {matches[0]}",
            })
            break  # One is enough to flag

    # 4. Generic/placeholder names
    if contact_name:
        if contact_name.lower() in ("there", "sir/madam", "whom it may concern", "name", "customer"):
            issues.append({
                "type": "generic_name",
                "severity": "warning",
                "message": f"Contact name is generic: '{contact_name}'. Email may look impersonal.",
            })

    # 5. Unprofessional content
    for pattern in UNPROFESSIONAL_PATTERNS:
        if re.search(pattern, full_text):
            issues.append({
                "type": "unprofessional",
                "severity": "hold",
                "message": f"Unprofessional content detected in email",
            })
            break

    # 6. Subject too short
    if subject and len(subject.strip()) < 5:
        issues.append({
            "type": "short_subject",
            "severity": "warning",
            "message": f"Subject line is very short ({len(subject.strip())} chars). May look like spam.",
        })

    # 7. Body too short (likely incomplete)
    if body and len(body.strip()) < 20:
        issues.append({
            "type": "short_body",
            "severity": "warning",
            "message": f"Email body is very short ({len(body.strip())} chars). May be incomplete.",
        })

    # 8. Missing company reference
    if body and "acme" not in body.lower() and "industrial" not in body.lower():
        issues.append({
            "type": "no_branding",
            "severity": "warning",
            "message": "Email doesn't mention company name. May lack professional branding.",
        })

    # Determine overall severity
    hold_issues = [i for i in issues if i["severity"] == "hold"]
    warning_issues = [i for i in issues if i["severity"] == "warning"]

    if hold_issues:
        severity = "hold"
    elif warning_issues:
        severity = "warning"
    else:
        severity = "pass"

    return {
        "passed": len(hold_issues) == 0,
        "severity": severity,
        "issues": issues,
        "issue_count": len(issues),
        "hold_count": len(hold_issues),
        "warning_count": len(warning_issues),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def qc_check_video(video_doc: dict) -> dict:
    """
    QC check a HeyGen video before including in emails.
    Returns: {passed: bool, issues: [...], severity: 'pass'|'warning'|'hold'}
    """
    issues = []

    status = video_doc.get("status", "")
    video_url = video_doc.get("video_url", "")

    if status == "failed":
        issues.append({
            "type": "video_failed",
            "severity": "hold",
            "message": "Video generation failed. Do not include in email.",
        })
    elif status == "processing":
        issues.append({
            "type": "video_processing",
            "severity": "hold",
            "message": "Video is still processing. Wait before sending.",
        })
    elif status == "completed" and not video_url:
        issues.append({
            "type": "no_video_url",
            "severity": "hold",
            "message": "Video completed but no URL available.",
        })

    # Check URL validity
    if video_url and not video_url.startswith("http"):
        issues.append({
            "type": "invalid_url",
            "severity": "hold",
            "message": f"Video URL is malformed: '{video_url[:50]}'",
        })

    hold_issues = [i for i in issues if i["severity"] == "hold"]

    return {
        "passed": len(hold_issues) == 0,
        "severity": "hold" if hold_issues else "pass",
        "issues": issues,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def qc_gate_email_send(db, subject, body, recipient_email, contact_name="", company_name="", sequence_id="", step_num=0, user_id="admin"):
    """
    Run QC gate before email send. If held, stores in qc_held_emails collection.
    Returns: (should_send: bool, qc_result: dict)
    """
    qc = qc_check_email(subject, body, recipient_email, contact_name, company_name)

    # Log every QC check
    await db.qc_log.insert_one({
        "type": "email",
        "subject": subject[:100] if subject else "",
        "recipient": recipient_email,
        "contact_name": contact_name,
        "qc_result": qc,
        "sequence_id": sequence_id,
        "step_num": step_num,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    if not qc["passed"]:
        # Hold the email for review
        await db.qc_held_emails.insert_one({
            "subject": subject,
            "body": body,
            "recipient_email": recipient_email,
            "contact_name": contact_name,
            "company_name": company_name,
            "sequence_id": sequence_id,
            "step_num": step_num,
            "user_id": user_id,
            "qc_result": qc,
            "status": "held",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # Create notification
        hold_reasons = "; ".join(i["message"] for i in qc["issues"] if i["severity"] == "hold")
        await db.notifications.insert_one({
            "user_id": user_id,
            "type": "qc_hold",
            "title": "Email Held for Review",
            "message": f"To: {recipient_email} — {hold_reasons}",
            "read": False,
            "link": "/maintenance",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "auto_generated": True,
        })

        logger.warning(f"QC HOLD: Email to {recipient_email} held. Issues: {hold_reasons}")
        return False, qc

    if qc["severity"] == "warning":
        logger.info(f"QC WARN: Email to {recipient_email} passed with warnings: {qc['warning_count']}")

    return True, qc
