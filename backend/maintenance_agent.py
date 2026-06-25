"""
Maintenance Agent — Self-Learning & Self-Healing for LeadForge.
Runs periodic analysis to optimize lead-finding and follow-through.
Automatically takes corrective actions and logs everything it does.

Scope: Lead discovery, email follow-ups, quote follow-through, pipeline advancement.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


def get_sync_db():
    client = MongoClient(MONGO_URL)
    return client, client[DB_NAME]


def run_maintenance_cycle():
    """Main entry — runs all checks, takes auto-actions, and stores the report."""
    logger.info("Maintenance Agent: Starting optimization cycle...")
    client, sdb = get_sync_db()

    try:
        insights = []
        actions_taken = []

        # 1. Campaign Performance — find and fix stale/paused campaigns
        i, a = analyze_and_fix_campaigns(sdb)
        insights.extend(i)
        actions_taken.extend(a)

        # 2. Lead Quality — auto-flag stale leads, prioritize high-value
        i, a = analyze_and_fix_leads(sdb)
        insights.extend(i)
        actions_taken.extend(a)

        # 3. Quote Follow-up — auto-nudge on overdue quotes
        i, a = analyze_and_fix_quotes(sdb)
        insights.extend(i)
        actions_taken.extend(a)

        # 4. System Health
        i, a = check_system_health(sdb)
        insights.extend(i)
        actions_taken.extend(a)

        # 5. Pipeline Playbook
        insights.extend(build_playbook(sdb))

        # 6. Pricing Intelligence (async bridge)
        pricing_insights, pricing_actions = run_pricing_intelligence_sync(sdb)
        insights.extend(pricing_insights)
        actions_taken.extend(pricing_actions)

        # 7. Feedback Loop — retrain lead scoring from outcomes
        feedback_insights, feedback_actions = run_feedback_loop_sync(sdb)
        insights.extend(feedback_insights)
        actions_taken.extend(feedback_actions)

        report = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "insights_count": len(insights),
            "actions_taken_count": len(actions_taken),
            "insights": insights,
            "actions_taken": actions_taken,
            "status": "completed",
        }
        sdb.maintenance_reports.insert_one(report)

        # Persist high/critical insights as open action items
        for insight in insights:
            if insight.get("priority") in ("high", "critical"):
                sdb.maintenance_actions.update_one(
                    {"insight_key": insight.get("key", "")},
                    {"$set": {
                        **insight,
                        "resolved": False,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )

        # Auto-resolve actions that the agent already fixed
        for action in actions_taken:
            key = action.get("related_key", "")
            if key:
                sdb.maintenance_actions.update_one(
                    {"insight_key": key},
                    {"$set": {
                        "resolved": True,
                        "auto_resolved": True,
                        "resolved_at": datetime.now(timezone.utc).isoformat(),
                        "resolution_note": action.get("description", "Auto-fixed by Maintenance Agent"),
                    }},
                )

        logger.info(f"Maintenance Agent: Done. {len(insights)} insights, {len(actions_taken)} auto-actions.")

    except Exception as e:
        logger.error(f"Maintenance Agent error: {e}")
        # Store error report
        sdb.maintenance_reports.insert_one({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "error": str(e),
            "insights_count": 0,
            "actions_taken_count": 0,
            "insights": [],
            "actions_taken": [],
        })
    finally:
        client.close()


# =====================================================
# 1. CAMPAIGN ANALYSIS + AUTO-FIX
# =====================================================
def _check_paused_campaigns(sdb, sequences, now):
    """Check for paused campaigns and auto-resume if stale > 7 days."""
    insights = []
    actions = []
    for seq in sequences:
        if not seq.get("paused"):
            continue
        seq_id = seq.get("sequence_id", "unknown")
        updated = seq.get("updated_at", "")
        days_paused = 0
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days_paused = (now - updated_dt).days
            except Exception:
                pass
        if days_paused > 7:
            sdb.email_sequences.update_one(
                {"sequence_id": seq_id},
                {"$set": {"paused": False, "updated_at": now.isoformat()}}
            )
            actions.append({
                "type": "auto_resume",
                "related_key": f"paused_campaign_{seq_id}",
                "description": f"Auto-resumed campaign {seq_id[:12]} — was paused for {days_paused} days.",
                "timestamp": now.isoformat(),
            })
        else:
            insights.append({
                "key": f"paused_campaign_{seq_id}",
                "category": "campaign",
                "priority": "medium",
                "title": f"Campaign Paused: {seq_id[:12]}",
                "message": f"Paused for {days_paused} days. Will auto-resume after 7 days if not manually handled.",
                "action": "Review and resume the campaign or archive it.",
            })
    return insights, actions


def _check_stale_campaigns(sequences, now):
    """Detect active campaigns with no activity in 7+ days."""
    insights = []
    for seq in sequences:
        if seq.get("paused"):
            continue
        seq_id = seq.get("sequence_id", "unknown")
        updated = seq.get("updated_at", "")
        if not updated:
            continue
        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            days_stale = (now - updated_dt).days
            if days_stale > 7:
                insights.append({
                    "key": f"stale_campaign_{seq_id}",
                    "category": "campaign",
                    "priority": "high",
                    "title": f"Stale Campaign ({days_stale} days)",
                    "message": f"Campaign {seq_id[:12]} has had no activity in {days_stale} days.",
                    "action": "Send the next sequence step or create a follow-up.",
                })
        except Exception:
            pass
    return insights


def _check_campaign_coverage(sdb, sequences):
    """Check for leads not enrolled in any campaign."""
    all_lead_ids_in_campaigns = set()
    for seq in sequences:
        all_lead_ids_in_campaigns.update(seq.get("lead_ids", []))

    total_leads = sdb.leads.count_documents({})
    uncovered = total_leads - len(all_lead_ids_in_campaigns)
    if uncovered > 0 and total_leads > 0:
        pct = round((uncovered / total_leads) * 100)
        return [{
            "key": "uncovered_leads",
            "category": "campaign",
            "priority": "high" if pct > 50 else "medium",
            "title": f"{uncovered} Leads Not in Any Campaign ({pct}%)",
            "message": f"{pct}% of your pipeline has no outreach. These leads are going cold.",
            "action": "Create a campaign and assign these orphaned leads.",
        }]
    return []


def analyze_and_fix_campaigns(sdb):
    insights = []
    actions = []
    now = datetime.now(timezone.utc)
    sequences = list(sdb.email_sequences.find({}, {"_id": 0}))

    if not sequences:
        insights.append({
            "key": "no_campaigns",
            "category": "campaign",
            "priority": "medium",
            "title": "No Active Campaigns",
            "message": "No email campaigns exist. Campaigns are the fastest path to converting leads.",
            "action": "Create a new email sequence targeting your highest-value leads.",
        })
        return insights, actions

    paused_i, paused_a = _check_paused_campaigns(sdb, sequences, now)
    insights.extend(paused_i)
    actions.extend(paused_a)

    insights.extend(_check_stale_campaigns(sequences, now))
    insights.extend(_check_campaign_coverage(sdb, sequences))

    return insights, actions


# =====================================================
# 2. LEAD ANALYSIS + AUTO-FIX
# =====================================================
def _classify_leads(leads, now):
    """Classify leads into status counts, industry counts, stale leads, and high-value new leads."""
    status_counts = {}
    industry_counts = {}
    stale_leads = []
    high_value_new = []

    for lead in leads:
        status = lead.get("status", "new")
        status_counts[status] = status_counts.get(status, 0) + 1
        industry = lead.get("industry", "Unknown")
        industry_counts[industry] = industry_counts.get(industry, 0) + 1

        deal = lead.get("deal_value", 0)
        if isinstance(deal, (int, float)) and deal > 5000 and status == "new":
            high_value_new.append(lead)

        created = lead.get("created_at", "")
        if created and status == "new":
            try:
                if isinstance(created, str):
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                else:
                    created_dt = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
                days_old = (now - created_dt).days
                if days_old > 14:
                    stale_leads.append({"name": lead.get("lead_name", "Unknown"), "days": days_old, "id": lead.get("id", "")})
            except Exception:
                pass

    return status_counts, industry_counts, stale_leads, high_value_new


def _auto_advance_stale_leads(sdb, stale_leads, now):
    """Auto-advance leads that have been 'new' for 30+ days to 'contacted'."""
    auto_flagged = 0
    for sl in stale_leads:
        if sl["days"] > 30:
            lead_id = sl.get("id", "")
            if lead_id:
                sdb.leads.update_one(
                    {"id": lead_id, "status": "new"},
                    {"$set": {
                        "status": "contacted",
                        "auto_flagged": True,
                        "auto_flag_reason": f"Auto-advanced by Maintenance Agent — was 'new' for {sl['days']} days",
                        "updated_at": now.isoformat(),
                    }}
                )
                auto_flagged += 1
    actions = []
    if auto_flagged > 0:
        actions.append({
            "type": "auto_advance_leads",
            "related_key": "stale_leads",
            "description": f"Auto-advanced {auto_flagged} leads from 'new' to 'contacted' (stale 30+ days).",
            "timestamp": now.isoformat(),
        })
    return actions


def _build_lead_insights(leads, stale_leads, high_value_new, industry_counts):
    """Build insights list from classified lead data."""
    insights = []

    remaining_stale = [s for s in stale_leads if s["days"] <= 30]
    if remaining_stale:
        insights.append({
            "key": "stale_leads",
            "category": "leads",
            "priority": "high",
            "title": f"{len(remaining_stale)} Leads Going Cold (14-30 days)",
            "message": f"{', '.join(s['name'] for s in remaining_stale[:5])}{'...' if len(remaining_stale) > 5 else ''} — still in 'new' status.",
            "action": "Contact these leads or start a nurture campaign before they forget you.",
        })

    if high_value_new:
        total_val = sum(hv.get("deal_value", 0) for hv in high_value_new)
        insights.append({
            "key": "high_value_untouched",
            "category": "leads",
            "priority": "critical",
            "title": f"{len(high_value_new)} High-Value Leads (${total_val:,.0f}) Need Attention",
            "message": "These $5K+ leads are sitting untouched. Money on the table.",
            "action": "Prioritize personal outreach to these leads today.",
        })

    if industry_counts:
        best = max(industry_counts, key=industry_counts.get)
        insights.append({
            "key": "top_industry",
            "category": "leads",
            "priority": "low",
            "title": f"Top Industry: {best}",
            "message": f"{best} = {industry_counts[best]}/{len(leads)} leads ({round(industry_counts[best]/len(leads)*100)}%).",
            "action": f"Double down on {best} outreach.",
        })

    return insights


def analyze_and_fix_leads(sdb):
    insights = []
    actions = []
    now = datetime.now(timezone.utc)
    leads = list(sdb.leads.find({}, {"_id": 0}))

    if not leads:
        return insights, actions

    status_counts, industry_counts, stale_leads, high_value_new = _classify_leads(leads, now)

    actions.extend(_auto_advance_stale_leads(sdb, stale_leads, now))

    insights.extend(_build_lead_insights(leads, stale_leads, high_value_new, industry_counts))

    return insights, actions


# =====================================================
# 3. QUOTE FOLLOW-UP + AUTO-FIX
# =====================================================
def _detect_stale_quotes(quotes: list, now) -> tuple:
    """Identify draft quotes older than 3 days."""
    stale_quotes = []
    draft_count = 0
    draft_value = 0

    for q in quotes:
        status = q.get("status", "draft")
        price = q.get("total_price", 0) or 0

        if status != "draft":
            continue

        draft_count += 1
        draft_value += price
        created = q.get("created_at", "")
        if not created:
            continue

        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            days_old = (now - created_dt).days
            if days_old > 3:
                stale_quotes.append({
                    "id": q.get("id", ""),
                    "lead_id": q.get("lead_id", ""),
                    "value": price,
                    "days": days_old,
                })
        except Exception:
            pass

    return stale_quotes, draft_count, draft_value


def _notify_stale_quotes(sdb, stale_quotes: list, now) -> int:
    """Create follow-up notifications for quotes stale 7+ days."""
    auto_notified = 0
    for sq in stale_quotes:
        if sq["days"] > 7:
            sdb.notifications.insert_one({
                "user_id": "admin",
                "type": "quote_followup",
                "title": "Quote Follow-Up Needed",
                "message": f"Quote worth ${sq['value']:,.0f} has been in draft for {sq['days']} days. Send it or close it.",
                "read": False,
                "link": "/pipeline",
                "created_at": now.isoformat(),
                "auto_generated": True,
            })
            auto_notified += 1
    return auto_notified


def analyze_and_fix_quotes(sdb):
    insights = []
    actions = []
    now = datetime.now(timezone.utc)
    quotes = list(sdb.quotes.find({}, {"_id": 0}))

    if not quotes:
        return insights, actions

    stale_quotes, draft_count, draft_value = _detect_stale_quotes(quotes, now)

    auto_notified = _notify_stale_quotes(sdb, stale_quotes, now)

    if auto_notified > 0:
        actions.append({
            "type": "auto_notify_quotes",
            "related_key": "stale_quotes",
            "description": f"Auto-created {auto_notified} follow-up notifications for stale quotes (7+ days in draft).",
            "timestamp": now.isoformat(),
        })

    if stale_quotes:
        total_val = sum(s["value"] for s in stale_quotes)
        insights.append({
            "key": "stale_quotes",
            "category": "quotes",
            "priority": "high",
            "title": f"{len(stale_quotes)} Stale Quotes (${total_val:,.0f})",
            "message": "Draft quotes older than 3 days. Every day without follow-up reduces close probability.",
            "action": "Send or finalize these quotes now.",
        })

    if draft_count > 0:
        insights.append({
            "key": "draft_quotes_summary",
            "category": "quotes",
            "priority": "medium",
            "title": f"{draft_count} Draft Quotes (${draft_value:,.0f})",
            "message": "Total unsent quote value sitting in drafts.",
            "action": "Review and send pending quotes to move deals forward.",
        })

    return insights, actions


# =====================================================
# 4. SYSTEM HEALTH CHECK
# =====================================================
def check_system_health(sdb):
    insights = []
    actions = []

    # Failed videos
    failed_videos = sdb.leads.count_documents({"video_status": "failed"})
    if failed_videos > 0:
        insights.append({
            "key": "heygen_failures",
            "category": "system",
            "priority": "medium",
            "title": f"{failed_videos} Failed Video Generations",
            "message": "These leads won't have personalized video outreach.",
            "action": "Retry video generation from the Video Studio page.",
        })

    # Push subscription check
    sub_count = sdb.push_subscriptions.count_documents({})
    if sub_count == 0:
        insights.append({
            "key": "no_push_subs",
            "category": "system",
            "priority": "medium",
            "title": "Push Notifications Not Enabled",
            "message": "You'll miss real-time alerts for new leads, demos, and email opens.",
            "action": "Enable push notifications in Profile settings.",
        })

    # Email error rate
    recent_errors = sdb.notification_log.count_documents({
        "type": {"$regex": "error", "$options": "i"},
    })
    if recent_errors > 5:
        insights.append({
            "key": "email_errors",
            "category": "system",
            "priority": "high",
            "title": f"{recent_errors} Email Sending Errors",
            "message": "Multiple email failures detected. Check SendGrid config.",
            "action": "Verify SendGrid API key and domain in Profile settings.",
        })

    return insights, actions


# =====================================================
# 5. STRATEGIC PLAYBOOK
# =====================================================
def build_playbook(sdb):
    insights = []
    leads = list(sdb.leads.find({}, {"_id": 0}))
    quotes = list(sdb.quotes.find({}, {"_id": 0}))

    if not leads:
        return insights

    # Industry-quote revenue mapping
    lead_industry_map = {lead.get("id"): lead.get("industry", "Unknown") for lead in leads}
    industry_quotes = {}
    for q in quotes:
        industry = lead_industry_map.get(q.get("lead_id", ""), "Unknown")
        if industry not in industry_quotes:
            industry_quotes[industry] = {"count": 0, "value": 0}
        industry_quotes[industry]["count"] += 1
        industry_quotes[industry]["value"] += q.get("total_price", 0) or 0

    if industry_quotes:
        best = max(industry_quotes.items(), key=lambda x: x[1]["value"])
        if best[1]["value"] > 0:
            insights.append({
                "key": "highest_value_industry",
                "category": "playbook",
                "priority": "low",
                "title": f"Highest Value Vertical: {best[0]}",
                "message": f"{best[0]} has {best[1]['count']} quotes worth ${best[1]['value']:,.0f}.",
                "action": f"Create targeted campaigns for {best[0]} businesses.",
            })

    # Pipeline velocity
    total_leads = len(leads)
    total_quotes = len(quotes)
    if total_leads > 0:
        rate = round((total_quotes / total_leads) * 100)
        insights.append({
            "key": "pipeline_velocity",
            "category": "playbook",
            "priority": "low",
            "title": f"Pipeline Velocity: {rate}% Quote Rate",
            "message": f"{total_quotes} quotes from {total_leads} leads.",
            "action": "Aim for 30%+ quote rate." if rate < 30 else "Strong rate. Focus on closing.",
        })

    return insights


def _build_digest_message(report: dict, open_actions: int, recent_skills: list) -> str:
    """Build the morning digest notification body text."""
    insights_count = report.get("insights_count", 0)
    actions_count = report.get("actions_taken_count", 0)
    critical = len([i for i in report.get("insights", []) if i.get("priority") == "critical"])
    high = len([i for i in report.get("insights", []) if i.get("priority") == "high"])

    parts = []
    if actions_count > 0:
        parts.append(f"{actions_count} auto-fixed")
    if critical > 0:
        parts.append(f"{critical} critical")
    if high > 0:
        parts.append(f"{high} high-priority")
    if open_actions > 0:
        parts.append(f"{open_actions} need review")

    body = f"Overnight: {insights_count} insights"
    if parts:
        body += f" | {', '.join(parts)}"
    if recent_skills:
        body += f" | New skills: {', '.join(s['skill_name'] for s in recent_skills[:2])}"
    return body


def send_morning_digest():
    """Send a morning push notification summarizing overnight activity."""
    logger.info("Morning Digest: Generating summary...")
    client, sdb = get_sync_db()

    try:
        report = sdb.maintenance_reports.find_one(
            {}, {"_id": 0}, sort=[("run_at", -1)]
        )
        if not report:
            return

        open_actions = sdb.maintenance_actions.count_documents({"resolved": False})
        recent_skills = list(sdb.discovered_skills.find(
            {}, {"_id": 0, "skill_name": 1}
        ).sort("discovered_at", -1).limit(5))

        body = _build_digest_message(report, open_actions, recent_skills)

        try:
            from routes.notifications import send_push_to_all
            send_push_to_all("morning_digest", body, "/maintenance")
            logger.info(f"Morning Digest sent: {body}")
        except Exception as e:
            logger.warning(f"Morning digest push failed: {e}")

        sdb.notifications.insert_one({
            "user_id": "admin",
            "type": "morning_digest",
            "title": "Morning Digest",
            "message": body,
            "read": False,
            "link": "/maintenance",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "auto_generated": True,
        })

    except Exception as e:
        logger.error(f"Morning Digest error: {e}")
    finally:
        client.close()


def run_pricing_intelligence_sync(sdb) -> tuple:
    """Sync bridge — run pricing intelligence analysis within maintenance cycle."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    insights = []
    actions = []

    try:
        async_client = AsyncIOMotorClient(MONGO_URL)
        async_db = async_client[DB_NAME]

        async def _run():
            from services.pricing_intelligence import analyze_pricing_patterns
            return await analyze_pricing_patterns(async_db)

        loop = asyncio.new_event_loop()
        analysis = loop.run_until_complete(_run())
        loop.close()
        async_client.close()

        if analysis.get("status") == "no_data":
            return insights, actions

        # Convert pricing alerts into maintenance insights
        for alert in analysis.get("pricing_alerts", []):
            insights.append({
                "key": f"pricing_{alert['service_type']}_{alert['alert_type']}",
                "category": "pricing",
                "priority": alert["severity"],
                "message": alert["message"],
                "suggested_action": alert.get("suggested_action", "review"),
                "auto_generated": True,
                "source": "pricing_intelligence",
            })

        # Auto-actions for pricing insights
        for svc in analysis.get("service_analysis", []):
            if svc["win_rate"] >= 60 and svc["total_estimates"] >= 3:
                actions.append({
                    "related_key": f"pricing_{svc['service_type']}_high_performer",
                    "description": f"Flagged {svc['service_type']} as high-performer ({svc['win_rate']}% win rate). Boosting lead scores for this service type.",
                    "category": "pricing_auto_boost",
                    "auto": True,
                })
                # Actually boost in DB
                sdb.scoring_weights.update_one(
                    {"type": "service_performance"},
                    {"$set": {
                        "boost_services": [svc["service_type"]],
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "source": "maintenance_agent",
                    }},
                    upsert=True,
                )

        logger.info(f"Pricing Intelligence: {len(insights)} insights, {len(actions)} auto-actions")

    except Exception as e:
        logger.error(f"Pricing Intelligence sync error: {e}")

    return insights, actions


def run_feedback_loop_sync(sdb) -> tuple:
    """Sync bridge — run feedback loop to retrain lead scoring from outcomes."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    insights = []
    actions = []

    try:
        async_client = AsyncIOMotorClient(MONGO_URL)
        async_db = async_client[DB_NAME]

        async def _run():
            from services.feedback_loop import calculate_feedback_weights, apply_feedback_scoring
            weights_result = await calculate_feedback_weights(async_db)
            if weights_result.get("status") == "updated":
                scoring_result = await apply_feedback_scoring(async_db)
                return weights_result, scoring_result
            return weights_result, None

        loop = asyncio.new_event_loop()
        weights_result, scoring_result = loop.run_until_complete(_run())
        loop.close()
        async_client.close()

        if weights_result.get("status") == "updated":
            won = weights_result.get("won", 0)
            lost = weights_result.get("lost", 0)
            rescored = scoring_result.get("rescored", 0) if scoring_result else 0

            insights.append({
                "key": "feedback_loop_retrained",
                "category": "self_improvement",
                "priority": "medium",
                "message": f"Feedback loop retrained from {won} won + {lost} lost outcomes. {rescored} leads rescored.",
                "auto_generated": True,
                "source": "feedback_loop",
            })

            best_source = weights_result.get("insights", {}).get("best_source", "unknown")
            if best_source != "unknown":
                insights.append({
                    "key": "feedback_best_source",
                    "category": "self_improvement",
                    "priority": "low",
                    "message": f"Best converting lead source: {best_source}. Lead scores boosted for this source.",
                    "auto_generated": True,
                })

            actions.append({
                "related_key": "feedback_loop_retrained",
                "description": f"Auto-retrained scoring weights from {won + lost} outcomes. {rescored} leads rescored.",
                "category": "feedback_auto_retrain",
                "auto": True,
            })

        logger.info(f"Feedback Loop: {weights_result.get('status', 'no_data')} — {len(insights)} insights")

    except Exception as e:
        logger.error(f"Feedback Loop sync error: {e}")

    return insights, actions
