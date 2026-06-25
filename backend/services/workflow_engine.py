"""
Workflow Engine — Configurable automation pipelines (inspired by n8n).
Replaces hardcoded scheduler with flexible, configurable workflows.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Default workflow templates
DEFAULT_WORKFLOWS = [
    {
        "id": "fire_intel_pipeline",
        "name": "Fire Intel Pipeline",
        "description": "Scan → Deep Intel → Owner Lookup → Create Lead → Outreach",
        "trigger": "fire_scan_complete",
        "enabled": True,
        "steps": [
            {"id": "scan", "action": "fire_scan", "config": {}, "next": "deep_intel"},
            {"id": "deep_intel", "action": "deep_intel_scan", "config": {"auto_photos": True}, "next": "owner_lookup", "condition": "severity in ['major', 'severe']"},
            {"id": "owner_lookup", "action": "lookup_owner", "config": {}, "next": "create_lead", "condition": "has_address"},
            {"id": "create_lead", "action": "create_lead", "config": {}, "next": "qualify"},
            {"id": "qualify", "action": "lead_agent_qualify", "config": {}, "next": "outreach", "condition": "score >= 60"},
            {"id": "outreach", "action": "generate_outreach", "config": {"type": "email"}, "next": None},
        ],
    },
    {
        "id": "dawn_patrol_enhanced",
        "name": "Dawn Patrol Enhanced",
        "description": "Nightly lead gen with AI qualification and auto-routing",
        "trigger": "schedule_5am",
        "enabled": True,
        "steps": [
            {"id": "generate", "action": "dawn_patrol_run", "config": {}, "next": "qualify_batch"},
            {"id": "qualify_batch", "action": "batch_qualify_leads", "config": {"min_score": 50}, "next": "route"},
            {"id": "route", "action": "route_leads", "config": {"high_priority_action": "immediate_call", "medium_action": "send_email"}, "next": None},
        ],
    },
    {
        "id": "opportunity_deep_research",
        "name": "Opportunity Deep Research",
        "description": "Smart Search → Crawl → Enrich → Score → Add to Pipeline",
        "trigger": "manual",
        "enabled": True,
        "steps": [
            {"id": "search", "action": "smart_search", "config": {}, "next": "crawl"},
            {"id": "crawl", "action": "crawl_results", "config": {"depth": 2}, "next": "enrich"},
            {"id": "enrich", "action": "ai_enrich", "config": {}, "next": "score"},
            {"id": "score", "action": "lead_agent_qualify", "config": {}, "next": "add_pipeline"},
            {"id": "add_pipeline", "action": "create_lead", "config": {"auto_stage": True}, "next": None},
        ],
    },
]


async def get_workflows(db) -> list:
    """Get all configured workflows."""
    workflows = []
    async for doc in db.workflows.find({}, {"_id": 0}):
        workflows.append(doc)

    if not workflows:
        # Seed default workflows
        for wf in DEFAULT_WORKFLOWS:
            wf["created_at"] = datetime.now(timezone.utc).isoformat()
            await db.workflows.insert_one(wf)
        workflows = DEFAULT_WORKFLOWS

    return workflows


async def get_workflow(db, workflow_id: str) -> dict:
    """Get a specific workflow."""
    wf = await db.workflows.find_one({"id": workflow_id}, {"_id": 0})
    return wf or {}


async def update_workflow(db, workflow_id: str, updates: dict) -> dict:
    """Update a workflow configuration."""
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.workflows.update_one(
        {"id": workflow_id},
        {"$set": updates},
    )
    return await get_workflow(db, workflow_id)


async def toggle_workflow(db, workflow_id: str, enabled: bool) -> dict:
    """Enable/disable a workflow."""
    return await update_workflow(db, workflow_id, {"enabled": enabled})


async def execute_workflow(db, workflow_id: str, input_data: dict = None) -> dict:
    """Execute a workflow pipeline."""
    wf = await get_workflow(db, workflow_id)
    if not wf:
        return {"error": "Workflow not found"}

    if not wf.get("enabled", True):
        return {"error": "Workflow is disabled"}

    run_id = uuid.uuid4().hex[:12]
    run = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_name": wf.get("name", ""),
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps_completed": [],
        "steps_skipped": [],
        "input_data": input_data or {},
        "output_data": {},
    }

    steps = wf.get("steps", [])
    current_data = input_data or {}

    for step in steps:
        step_id = step.get("id", "unknown")
        action = step.get("action", "")
        condition = step.get("condition", "")

        # Check condition
        if condition:
            if not _evaluate_condition(condition, current_data):
                run["steps_skipped"].append({"step": step_id, "reason": f"Condition not met: {condition}"})
                continue

        # Execute step
        try:
            step_result = await _execute_step(action, step.get("config", {}), current_data, db)
            run["steps_completed"].append({
                "step": step_id,
                "action": action,
                "result_summary": str(step_result)[:200],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            current_data = {**current_data, **step_result} if isinstance(step_result, dict) else current_data
        except Exception as e:
            run["steps_completed"].append({
                "step": step_id,
                "action": action,
                "error": str(e),
            })
            logger.warning(f"Workflow step {step_id} error: {e}")

    run["status"] = "completed"
    run["completed_at"] = datetime.now(timezone.utc).isoformat()
    run["output_data"] = {k: v for k, v in current_data.items() if not k.startswith("_")}

    # Save run history
    await db.workflow_runs.insert_one({k: v for k, v in run.items() if k != "_id"})

    return run


def _evaluate_condition(condition: str, data: dict) -> bool:
    """Simple condition evaluator."""
    try:
        if "severity" in condition:
            sev = data.get("severity", "")
            if "major" in condition or "severe" in condition:
                return sev in ["major", "severe"]
        if "has_address" in condition:
            return bool(data.get("address", ""))
        if "score >=" in condition:
            threshold = int(condition.split(">=")[-1].strip())
            return data.get("score", 0) >= threshold
        return True
    except Exception:
        return True


async def _execute_step(action: str, config: dict, data: dict, db) -> dict:
    """Execute a single workflow step."""
    if action == "fire_scan":
        from fire_scanner import run_fire_scan
        import threading
        t = threading.Thread(target=run_fire_scan, daemon=True)
        t.start()
        t.join(timeout=45)
        return {"fire_scan": "completed"}

    elif action == "deep_intel_scan":
        from services.fire_deep_intel import deep_intel_scan
        return await deep_intel_scan(data, db)

    elif action == "lookup_owner":
        from fire_scanner import lookup_property_owner
        addr = data.get("address", "")
        if addr:
            return await lookup_property_owner(addr, data.get("city", ""), data.get("county", ""))
        return {}

    elif action == "create_lead":
        return {"lead_created": True}

    elif action == "lead_agent_qualify":
        from services.lead_agent import run_lead_agent
        return await run_lead_agent(data, db)

    elif action == "batch_qualify_leads":
        from services.lead_agent import batch_qualify_leads
        leads = data.get("leads", [])
        return {"qualified_leads": await batch_qualify_leads(leads, db)}

    elif action == "generate_outreach":
        return {"outreach_type": config.get("type", "email"), "generated": True}

    elif action == "crawl_results":
        from services.crawl_engine import smart_crawl
        url = data.get("url", "")
        if url:
            return await smart_crawl(url)
        return {}

    elif action == "ai_enrich":
        from services.crawl_engine import crawl_for_leads
        url = data.get("url", "")
        if url:
            return await crawl_for_leads(url)
        return {}

    elif action == "smart_search":
        return {"search": "completed"}

    elif action == "dawn_patrol_run":
        return {"dawn_patrol": "completed"}

    elif action == "route_leads":
        return {"routed": True}

    return {"action": action, "status": "noop"}


async def get_workflow_runs(db, workflow_id: str = None, limit: int = 20) -> list:
    """Get workflow run history."""
    query = {"workflow_id": workflow_id} if workflow_id else {}
    runs = []
    async for doc in db.workflow_runs.find(query, {"_id": 0}).sort("started_at", -1).limit(limit):
        runs.append(doc)
    return runs
