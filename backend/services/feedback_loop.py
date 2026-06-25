"""
Lead Scoring Feedback Loop — Auto-retrain scoring weights from conversion outcomes.
Tracks won/lost outcomes and adjusts weights for better future predictions.
"""

import logging
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


async def calculate_feedback_weights(db) -> dict:
    """Analyze won vs lost leads to derive optimal scoring weights."""
    won_leads = []
    lost_leads = []

    async for lead in db.leads.find({"status": "won"}, {"_id": 0}):
        won_leads.append(lead)
    async for lead in db.leads.find({"status": "lost"}, {"_id": 0}):
        lost_leads.append(lead)

    if not won_leads and not lost_leads:
        return {"status": "insufficient_data", "won": 0, "lost": 0, "weights": _get_default_weights()}

    # Analyze patterns in won leads
    won_sources = defaultdict(int)
    won_has_email = 0
    won_has_phone = 0
    won_high_score = 0
    won_avg_deal = 0

    for lead in won_leads:
        won_sources[lead.get("source", "unknown")] += 1
        if lead.get("contact_info") and "@" in lead.get("contact_info", ""):
            won_has_email += 1
        if lead.get("phone"):
            won_has_phone += 1
        if (lead.get("lead_score") or 0) >= 70:
            won_high_score += 1
        won_avg_deal += lead.get("deal_value", 0) or 0

    lost_sources = defaultdict(int)
    for lead in lost_leads:
        lost_sources[lead.get("source", "unknown")] += 1

    total_won = max(len(won_leads), 1)

    # Calculate source conversion rates
    source_weights = {}
    all_sources = set(list(won_sources.keys()) + list(lost_sources.keys()))
    for src in all_sources:
        w = won_sources.get(src, 0)
        lost_count = lost_sources.get(src, 0)
        total = w + lost_count
        if total > 0:
            rate = w / total
            source_weights[src] = round(rate * 100)

    # Build new weights
    weights = {
        "has_email": round(won_has_email / total_won * 25, 1),
        "has_phone": round(won_has_phone / total_won * 20, 1),
        "high_deal_value": 15 if (won_avg_deal / total_won) > 10000 else 8,
        "source_weights": source_weights,
        "base_score": 30,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "based_on": {"won": len(won_leads), "lost": len(lost_leads)},
    }

    # Save weights to DB
    await db.scoring_weights.update_one(
        {"type": "lead_scoring"},
        {"$set": {"weights": weights, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )

    return {
        "status": "updated",
        "won": len(won_leads),
        "lost": len(lost_leads),
        "weights": weights,
        "insights": {
            "best_source": max(source_weights.items(), key=lambda x: x[1])[0] if source_weights else "unknown",
            "email_impact": f"{round(won_has_email / total_won * 100)}% of won leads had email",
            "phone_impact": f"{round(won_has_phone / total_won * 100)}% of won leads had phone",
            "avg_deal_value": round(won_avg_deal / total_won),
        },
    }


async def apply_feedback_scoring(db) -> dict:
    """Re-score all leads using the feedback-trained weights."""
    weights_doc = await db.scoring_weights.find_one({"type": "lead_scoring"}, {"_id": 0})
    weights = weights_doc.get("weights", _get_default_weights()) if weights_doc else _get_default_weights()

    rescored = 0
    async for lead in db.leads.find({"status": {"$nin": ["won", "lost"]}}, {"_id": 0}):
        score = weights.get("base_score", 30)

        # Email bonus
        if lead.get("contact_info") and "@" in lead.get("contact_info", ""):
            score += weights.get("has_email", 15)

        # Phone bonus
        if lead.get("phone"):
            score += weights.get("has_phone", 10)

        # Deal value bonus
        deal_val = lead.get("deal_value", 0) or 0
        if deal_val > 50000:
            score += weights.get("high_deal_value", 15)
        elif deal_val > 10000:
            score += weights.get("high_deal_value", 15) * 0.6

        # Source weight
        src = lead.get("source", "unknown")
        src_weights = weights.get("source_weights", {})
        if src in src_weights:
            score += src_weights[src] * 0.15

        # Agent qualified bonus
        if lead.get("agent_qualified"):
            score += 10
        if lead.get("agent_priority") in ["critical", "high"]:
            score += 5

        score = max(0, min(100, round(score)))

        # Quality tag
        if score >= 80:
            quality = "hot"
        elif score >= 60:
            quality = "warm"
        elif score >= 40:
            quality = "cold"
        else:
            quality = "ice"

        if lead.get("id"):
            await db.leads.update_one(
                {"id": lead["id"]},
                {"$set": {"lead_score": score, "quality_tag": quality, "score_method": "feedback_loop"}}
            )
        else:
            await db.leads.update_one(
                {"lead_name": lead.get("lead_name", ""), "id": {"$exists": False}},
                {"$set": {"lead_score": score, "quality_tag": quality, "score_method": "feedback_loop"}}
            )
        rescored += 1

    return {"rescored": rescored, "weights_used": weights}


def _get_default_weights():
    return {
        "has_email": 15,
        "has_phone": 10,
        "high_deal_value": 12,
        "source_weights": {},
        "base_score": 35,
    }


async def record_outcome(db, lead_id: str, outcome: str, notes: str = "") -> dict:
    """Record a lead outcome (won/lost) for feedback training."""
    update = {
        "status": outcome,
        f"{outcome}_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes:
        update["outcome_notes"] = notes

    result = await db.leads.update_one({"id": lead_id}, {"$set": update})
    if result.modified_count == 0:
        return {"error": "Lead not found"}

    return {"lead_id": lead_id, "outcome": outcome, "recorded": True}
