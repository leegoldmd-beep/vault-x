"""
Zeno Learning Engine — Persistent memory and cross-agent knowledge system.
Runs overnight to analyze patterns, clean data, and improve Zeno's intelligence.

Schedule: 3:30 AM EST (8:30 AM UTC) — after fire scanner, before dawn patrol
"""
import logging
from datetime import datetime, timezone, timedelta
from collections import Counter

logger = logging.getLogger("zeno_learning")


async def run_zeno_learning(db) -> dict:
    """Main overnight learning cycle. Analyzes all app data and stores insights."""
    logger.info("Zeno Learning Engine: Starting overnight cycle...")
    now = datetime.now(timezone.utc)
    results = {
        "insights_generated": 0,
        "leads_cleaned": 0,
        "patterns_learned": 0,
        "agent_knowledge_synced": 0,
        "ran_at": now.isoformat()
    }

    try:
        # Phase 1: Clean empty/junk leads
        results["leads_cleaned"] = await _cleanup_empty_leads(db)

        # Phase 2: Learn lead patterns
        results["patterns_learned"] += await _learn_lead_patterns(db)

        # Phase 3: Learn fire scanner patterns
        results["patterns_learned"] += await _learn_fire_patterns(db)

        # Phase 4: Learn estimate patterns
        results["patterns_learned"] += await _learn_estimate_patterns(db)

        # Phase 5: Learn user interaction patterns from Zeno chats
        results["patterns_learned"] += await _learn_interaction_patterns(db)

        # Phase 6: Cross-agent knowledge sync
        results["agent_knowledge_synced"] = await _sync_agent_knowledge(db)

        # Phase 7: Generate daily insights summary
        results["insights_generated"] = await _generate_insights(db)

        # Save run record
        await db.zeno_learning_runs.insert_one({
            "ran_at": now.isoformat(),
            "results": results,
            "status": "completed"
        })

        logger.info(f"Zeno Learning: {results['leads_cleaned']} leads cleaned, "
                     f"{results['patterns_learned']} patterns, "
                     f"{results['insights_generated']} insights")

    except Exception as e:
        logger.error(f"Zeno Learning Engine error: {e}")
        results["error"] = str(e)

    return results


async def _cleanup_empty_leads(db) -> int:
    """Identify and remove leads with no meaningful data."""
    cleaned = 0

    # Find leads that are empty shells
    empty_leads = await db.leads.find({
        "$and": [
            {"$or": [
                {"lead_name": {"$in": [None, "", "Unknown", "N/A", "undefined"]}},
                {"lead_name": {"$exists": False}},
                {"company_name": {"$in": [None, "", "Unknown", "N/A", "undefined"]}},
            ]},
            {"$or": [
                {"contact_info": {"$in": [None, ""]}},
                {"contact_info": {"$exists": False}},
            ]},
            {"$or": [
                {"phone": {"$in": [None, ""]}},
                {"phone": {"$exists": False}},
            ]},
        ]
    }, {"_id": 1, "lead_name": 1, "company_name": 1}).to_list(500)

    if empty_leads:
        ids = [l["_id"] for l in empty_leads]
        result = await db.leads.delete_many({"_id": {"$in": ids}})
        cleaned = result.deleted_count
        logger.info(f"Cleaned {cleaned} empty leads (no name, no email, no phone)")

    # Also find leads with garbage data (very short names, obviously fake)
    junk_leads = await db.leads.find({
        "$or": [
            {"lead_name": {"$regex": r"^.{0,2}$"}},  # 0-2 char names
            {"lead_name": {"$regex": r"^(test|asdf|xxx|aaa|zzz)$", "$options": "i"}},
        ],
        "status": "new"  # Only clean new leads, not ones being worked
    }, {"_id": 1}).to_list(200)

    if junk_leads:
        junk_ids = [l["_id"] for l in junk_leads]
        result = await db.leads.delete_many({"_id": {"$in": junk_ids}})
        cleaned += result.deleted_count

    # Log cleanup
    if cleaned > 0:
        await db.zeno_memory.insert_one({
            "type": "cleanup",
            "category": "empty_leads",
            "data": {"leads_cleaned": cleaned},
            "created_at": datetime.now(timezone.utc).isoformat()
        })

    return cleaned


async def _learn_lead_patterns(db) -> int:
    """Analyze lead data to learn what makes a good vs bad lead."""
    patterns = 0

    # Source performance: which lead sources convert best
    pipeline = [
        {"$group": {
            "_id": "$source",
            "total": {"$sum": 1},
            "won": {"$sum": {"$cond": [{"$eq": ["$status", "won"]}, 1, 0]}},
            "contacted": {"$sum": {"$cond": [{"$eq": ["$status", "contacted"]}, 1, 0]}},
            "qualified": {"$sum": {"$cond": [{"$eq": ["$status", "qualified"]}, 1, 0]}},
        }},
        {"$match": {"total": {"$gte": 3}}},
        {"$sort": {"total": -1}},
        {"$limit": 15}
    ]
    source_stats = await db.leads.aggregate(pipeline).to_list(20)

    if source_stats:
        await db.zeno_memory.update_one(
            {"type": "pattern", "category": "lead_sources"},
            {"$set": {
                "data": {
                    s["_id"]: {"total": s["total"], "won": s["won"],
                               "contacted": s["contacted"], "qualified": s["qualified"]}
                    for s in source_stats if s["_id"]
                },
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        patterns += 1

    # Industry breakdown
    industry_pipeline = [
        {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 2}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    industries = await db.leads.aggregate(industry_pipeline).to_list(15)
    if industries:
        await db.zeno_memory.update_one(
            {"type": "pattern", "category": "lead_industries"},
            {"$set": {
                "data": {i["_id"]: i["count"] for i in industries if i["_id"]},
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        patterns += 1

    # Leads with estimates (high-value indicator)
    leads_with_estimates = await db.estimates.distinct("lead_id")
    if leads_with_estimates:
        await db.zeno_memory.update_one(
            {"type": "pattern", "category": "leads_with_estimates"},
            {"$set": {
                "data": {"count": len(leads_with_estimates)},
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        patterns += 1

    return patterns


async def _learn_fire_patterns(db) -> int:
    """Learn from fire scanner data — what gets tracked, what converts."""
    patterns = 0

    total_fires = await db.fire_incidents.count_documents({})
    tracked = await db.fire_incidents.count_documents({"tracked": True})
    converted = await db.fire_incidents.count_documents({"converted_to_lead": True})

    # Severity distribution
    severe = await db.fire_incidents.count_documents({"severity": "severe"})
    moderate = await db.fire_incidents.count_documents({"severity": "moderate"})

    # Cities with most incidents
    city_pipeline = [
        {"$group": {"_id": "$city", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 2}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    cities = await db.fire_incidents.aggregate(city_pipeline).to_list(15)

    await db.zeno_memory.update_one(
        {"type": "pattern", "category": "fire_scanner"},
        {"$set": {
            "data": {
                "total": total_fires, "tracked": tracked, "converted": converted,
                "severe": severe, "moderate": moderate,
                "top_cities": {c["_id"]: c["count"] for c in cities if c["_id"]},
                "track_rate": round(tracked / max(total_fires, 1) * 100, 1),
                "conversion_rate": round(converted / max(tracked, 1) * 100, 1),
            },
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    patterns += 1
    return patterns


async def _learn_estimate_patterns(db) -> int:
    """Learn estimate pricing and approval patterns."""
    patterns = 0

    total = await db.estimates.count_documents({})
    approved = await db.estimates.count_documents({"status": "approved"})
    pending = await db.estimates.count_documents({"status": "pending_approval"})
    rejected = await db.estimates.count_documents({"status": "rejected"})

    # Average values from quotes
    quotes = await db.quotes.find({}, {"_id": 0, "total": 1, "job_category": 1}).to_list(100)
    totals = [q.get("total", 0) for q in quotes if q.get("total")]
    avg_quote = round(sum(totals) / max(len(totals), 1), 2) if totals else 0

    categories = Counter(q.get("job_category", "unknown") for q in quotes)

    await db.zeno_memory.update_one(
        {"type": "pattern", "category": "estimates"},
        {"$set": {
            "data": {
                "total": total, "approved": approved, "pending": pending, "rejected": rejected,
                "approval_rate": round(approved / max(total - pending, 1) * 100, 1),
                "avg_quote_value": avg_quote,
                "top_categories": dict(categories.most_common(5)),
            },
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    return 1


async def _learn_interaction_patterns(db) -> int:
    """Analyze Zeno chat history to learn what users ask about most."""
    patterns = 0

    # Count topics from recent chats
    recent_chats = await db.vault_agent_chats.find(
        {"role": "user"},
        {"_id": 0, "content": 1}
    ).sort("timestamp", -1).limit(200).to_list(200)

    if not recent_chats:
        return 0

    # Simple keyword frequency analysis
    keywords = Counter()
    action_words = ["fire", "lead", "estimate", "scan", "patrol", "dawn", "call",
                    "email", "pipeline", "revenue", "contract", "generate", "recon"]

    for chat in recent_chats:
        content = (chat.get("content") or "").lower()
        for kw in action_words:
            if kw in content:
                keywords[kw] += 1

    await db.zeno_memory.update_one(
        {"type": "pattern", "category": "user_topics"},
        {"$set": {
            "data": dict(keywords.most_common(10)),
            "chat_count": len(recent_chats),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    return 1


async def _sync_agent_knowledge(db) -> int:
    """Collect knowledge from all agents and store for Zeno to use."""
    synced = 0

    # Dawn Patrol insights
    latest_dp = await db.dawn_patrol_briefings.find_one(
        {}, {"_id": 0, "morning_score": 1, "action_count": 1, "revenue": 1},
        sort=[("created_at", -1)]
    )
    if latest_dp:
        await db.zeno_memory.update_one(
            {"type": "agent_knowledge", "agent": "dawn_patrol"},
            {"$set": {
                "data": {
                    "morning_score": latest_dp.get("morning_score", {}),
                    "action_count": latest_dp.get("action_count", 0),
                    "pipeline_value": latest_dp.get("revenue", {}).get("pipeline", 0),
                },
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        synced += 1

    # Maintenance Agent insights
    latest_maint = await db.maintenance_reports.find_one(
        {}, {"_id": 0, "open_issues": 1, "auto_resolved": 1},
        sort=[("created_at", -1)]
    )
    if latest_maint:
        await db.zeno_memory.update_one(
            {"type": "agent_knowledge", "agent": "maintenance"},
            {"$set": {
                "data": {
                    "open_issues": latest_maint.get("open_issues", 0),
                    "auto_resolved": latest_maint.get("auto_resolved", 0),
                },
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        synced += 1

    # HubSpot sync status
    hubspot_log = await db.hubspot_sync_log.find_one(
        {}, {"_id": 0, "synced_count": 1, "errors": 1},
        sort=[("synced_at", -1)]
    )
    if hubspot_log:
        await db.zeno_memory.update_one(
            {"type": "agent_knowledge", "agent": "hubspot"},
            {"$set": {
                "data": {
                    "last_sync_count": hubspot_log.get("synced_count", 0),
                    "sync_errors": hubspot_log.get("errors", 0),
                },
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        synced += 1

    # Email performance
    email_stats = await db.email_tracking.aggregate([
        {"$group": {
            "_id": None,
            "total_sent": {"$sum": 1},
            "total_opened": {"$sum": {"$cond": [{"$gt": ["$open_count", 0]}, 1, 0]}},
            "total_clicked": {"$sum": {"$cond": [{"$gt": ["$click_count", 0]}, 1, 0]}},
        }}
    ]).to_list(1)
    if email_stats:
        s = email_stats[0]
        await db.zeno_memory.update_one(
            {"type": "agent_knowledge", "agent": "email"},
            {"$set": {
                "data": {
                    "total_sent": s.get("total_sent", 0),
                    "open_rate": round(s.get("total_opened", 0) / max(s.get("total_sent", 1), 1) * 100, 1),
                    "click_rate": round(s.get("total_clicked", 0) / max(s.get("total_sent", 1), 1) * 100, 1),
                },
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        synced += 1

    return synced


async def _generate_insights(db) -> int:
    """Generate actionable insights from all learned data."""
    insights = []
    now = datetime.now(timezone.utc)

    # Get all learned patterns
    memories = await db.zeno_memory.find(
        {"type": {"$in": ["pattern", "agent_knowledge"]}},
        {"_id": 0}
    ).to_list(50)

    mem_map = {m.get("category", m.get("agent", "")): m.get("data", {}) for m in memories}

    # Insight: Best lead source
    sources = mem_map.get("lead_sources", {})
    if sources:
        best = max(sources.items(), key=lambda x: x[1].get("won", 0) + x[1].get("qualified", 0), default=(None, {}))
        if best[0]:
            insights.append({
                "type": "insight",
                "category": "lead_source",
                "title": f"Best lead source: {best[0]}",
                "detail": f"{best[0]} has {best[1].get('won', 0)} won and {best[1].get('qualified', 0)} qualified leads out of {best[1].get('total', 0)} total.",
                "priority": "high"
            })

    # Insight: Fire conversion opportunity
    fire_data = mem_map.get("fire_scanner", {})
    if fire_data.get("severe", 0) > 5 and fire_data.get("tracked", 0) == 0:
        insights.append({
            "type": "insight",
            "category": "fire_opportunity",
            "title": f"{fire_data['severe']} severe fires not being tracked",
            "detail": "You have severe fire incidents that aren't tracked. These are your highest-value restoration leads.",
            "priority": "high"
        })

    # Insight: Estimate approval backlog
    est_data = mem_map.get("estimates", {})
    if est_data.get("pending", 0) > 10:
        insights.append({
            "type": "insight",
            "category": "estimate_backlog",
            "title": f"{est_data['pending']} estimates waiting for approval",
            "detail": f"Approval rate is {est_data.get('approval_rate', 0)}%. Clear the backlog to keep pipeline moving.",
            "priority": "high"
        })

    # Insight: Email performance
    email_data = mem_map.get("email", {})
    if email_data.get("open_rate", 100) < 20:
        insights.append({
            "type": "insight",
            "category": "email_health",
            "title": f"Email open rate low ({email_data.get('open_rate', 0)}%)",
            "detail": "Consider warming up the domain or refreshing subject lines.",
            "priority": "medium"
        })

    # Insight: User interests
    topics = mem_map.get("user_topics", {})
    if topics:
        top_topic = max(topics.items(), key=lambda x: x[1] if isinstance(x[1], int) else 0, default=(None, 0))
        if top_topic[0]:
            insights.append({
                "type": "insight",
                "category": "user_behavior",
                "title": f"Most asked topic: {top_topic[0]}",
                "detail": f"You ask about '{top_topic[0]}' most frequently. Zeno will prioritize this in future responses.",
                "priority": "low"
            })

    # Save insights
    for insight in insights:
        insight["created_at"] = now.isoformat()
        await db.zeno_memory.update_one(
            {"type": "insight", "category": insight["category"]},
            {"$set": insight},
            upsert=True
        )

    return len(insights)


async def cleanup_leads_on_demand(db) -> dict:
    """Run lead cleanup manually (triggered by Zeno command)."""
    cleaned = await _cleanup_empty_leads(db)
    return {"leads_cleaned": cleaned}
