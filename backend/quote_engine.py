"""
Dry Ice Blasting Quote Engine - Calculation Logic
3-pass architecture: Vision Tags -> Classification -> Pricing
"""
import math
from pricing_config import QUOTE_ENGINE_CONFIG as CFG
from pricing_config import RESALE_PREP_CONFIG as RESALE_CFG


def round_quote(amount: float) -> int:
    """Apply business rounding rules."""
    if amount < 5000:
        return math.ceil(amount / 100) * 100
    elif amount <= 25000:
        return math.ceil(amount / 500) * 500
    else:
        return math.ceil(amount / 1000) * 1000


def select_pricing_model(job_category: str, geometry_complexity: str, confidence_score: float, estimated_sqft: float) -> str:
    """Decide which pricing model to use based on job characteristics."""
    industrial_cats = ["industrial_equipment", "electrical_equipment", "food_conveyor_system", "tooling_molds_dies"]

    if confidence_score < CFG["confidence_thresholds"]["medium"]:
        return "hourly"
    if job_category in industrial_cats:
        return "project_based"
    if geometry_complexity == "simple" and confidence_score >= CFG["confidence_thresholds"]["high"] and estimated_sqft > 0:
        return "square_foot"
    if estimated_sqft > 0 and geometry_complexity in ("simple", "moderate"):
        return "square_foot"
    return "project_based"


def calculate_travel(distance_miles: float) -> tuple[float, float]:
    """Calculate travel cost from distance."""
    travel_cfg = CFG["adjustments"]["travel"]
    free_radius = travel_cfg["local_radius_miles"]
    if distance_miles <= free_radius:
        return 0, 0
    billable_miles = distance_miles - free_radius
    cost = billable_miles * travel_cfg["per_mile_rate"]
    return round(cost, 2), billable_miles


def calculate_quote_from_params(
    job_category: str,
    contamination_level: int = 2,
    geometry_complexity: str = "moderate",
    access_difficulty: str = "easy",
    estimated_sqft: float = 0,
    estimated_hours: float = 0,
    surface_count: int = 1,
    measurements: dict | None = None,
    travel_miles: float = 0,
    after_hours: bool = False,
    high_risk: bool = False,
    quick_mode: bool = False
) -> dict:
    """
    Main quote calculation engine.
    Returns a dict with quote_low, quote_high, line_items, breakdown, etc.
    """
    cat_cfg = CFG["job_categories"].get(job_category)
    if not cat_cfg:
        return {"error": f"Unknown job category: {job_category}"}

    contam_cfg = CFG["contamination_levels"].get(contamination_level, CFG["contamination_levels"][2])
    geom_cfg = CFG["geometry_complexity"].get(geometry_complexity, CFG["geometry_complexity"]["moderate"])
    access_cfg = CFG["access_difficulty"].get(access_difficulty, CFG["access_difficulty"]["easy"])

    # Calculate sqft from measurements if provided
    calc_sqft = estimated_sqft
    if measurements and not calc_sqft:
        length = float(measurements.get("length", 0))
        width = float(measurements.get("width", 0))
        height = float(measurements.get("height", 0))
        if height > 0:
            calc_sqft = (2 * length * height) + (2 * width * height) + (length * width)
        else:
            calc_sqft = length * width
        calc_sqft *= surface_count

    # Quick mode: simple flat-rate from category baseline
    if quick_mode:
        base_low = cat_cfg["base_quote"]["low"] * surface_count
        base_high = cat_cfg["base_quote"]["high"] * surface_count
        travel_cost, billable_miles = calculate_travel(travel_miles)
        total_low = round_quote(base_low + travel_cost)
        total_high = round_quote(base_high + travel_cost)
        total_low = max(total_low, CFG["adjustments"]["minimum_charge"])
        line_items = [{"item": f"{cat_cfg['label']} (Quick Quote)", "low": base_low, "high": base_high}]
        if travel_cost > 0:
            line_items.append({"item": f"Travel ({billable_miles:.0f} mi beyond {CFG['adjustments']['travel']['local_radius_miles']} mi radius)", "low": travel_cost, "high": travel_cost})
        return {
            "pricing_model": "quick_quote",
            "job_category": job_category,
            "job_category_label": cat_cfg["label"],
            "quote_low": total_low,
            "quote_high": total_high,
            "total_sqft": round(calc_sqft, 1),
            "line_items": line_items,
            "breakdown": {
                "base_range": cat_cfg["base_quote"],
                "surface_count": surface_count,
                "travel_cost": travel_cost,
                "travel_miles": travel_miles,
            },
            "confidence_score": 0.5,
            "requires_onsite": True,
            "reasoning_summary": f"Quick estimate for {cat_cfg['label']}. Range based on typical job scope. On-site verification recommended.",
            "upsell_suggestions": []
        }

    # Full engine: select pricing model
    pricing_model = select_pricing_model(job_category, geometry_complexity, 0.75, calc_sqft)

    # Multipliers
    contam_mult_low = contam_cfg["pricing_multiplier"]["low"]
    contam_mult_high = contam_cfg["pricing_multiplier"]["high"]
    geom_mult_low = geom_cfg["pricing_multiplier"]["low"]
    geom_mult_high = geom_cfg["pricing_multiplier"]["high"]
    access_mult = access_cfg["multiplier"]

    risk_mult = CFG["adjustments"]["high_risk_multiplier"] if high_risk else 1.0
    hours_mult = CFG["adjustments"]["after_hours_multiplier"] if after_hours else 1.0

    line_items = []
    quote_low = 0
    quote_high = 0

    if pricing_model == "square_foot" and calc_sqft > 0:
        sqft_cfg = CFG["pricing_models"]["square_foot"]["base_range"]
        base_low = sqft_cfg["low"] * calc_sqft
        base_high = sqft_cfg["high"] * calc_sqft
        line_items.append({"item": f"Surface Area ({calc_sqft:.0f} sq ft @ ${sqft_cfg['low']}-${sqft_cfg['high']}/sqft)", "low": round(base_low), "high": round(base_high)})
        quote_low = base_low * contam_mult_low * geom_mult_low * access_mult
        quote_high = base_high * contam_mult_high * geom_mult_high * access_mult

    elif pricing_model == "hourly":
        hr_cfg = CFG["pricing_models"]["hourly"]["base_range"]
        est_hours = estimated_hours or max(1, calc_sqft / 150) if calc_sqft > 0 else 4
        est_hours *= contam_cfg["time_multiplier"]
        base_low = hr_cfg["low"] * est_hours
        base_high = hr_cfg["high"] * est_hours
        line_items.append({"item": f"Labor ({est_hours:.1f} hrs @ ${hr_cfg['low']}-${hr_cfg['high']}/hr)", "low": round(base_low), "high": round(base_high)})
        # Add media cost
        ice_lbs = est_hours * CFG["air_and_media"]["dry_ice_lb_per_hour"] * contam_cfg["media_multiplier"]
        ice_cost = ice_lbs * CFG["air_and_media"]["dry_ice_cost_per_lb"]
        line_items.append({"item": f"Dry Ice Media ({ice_lbs:.0f} lbs)", "low": round(ice_cost), "high": round(ice_cost * 1.3)})
        quote_low = (base_low + ice_cost) * geom_mult_low * access_mult
        quote_high = (base_high + ice_cost * 1.3) * geom_mult_high * access_mult

    else:  # project_based
        base_low = cat_cfg["base_quote"]["low"]
        base_high = cat_cfg["base_quote"]["high"]
        line_items.append({"item": f"{cat_cfg['label']} (Project)", "low": base_low, "high": base_high})
        quote_low = base_low * contam_mult_low * geom_mult_low * access_mult
        quote_high = base_high * contam_mult_high * geom_mult_high * access_mult

    # Surface count
    if surface_count > 1:
        quote_low *= surface_count
        quote_high *= surface_count
        line_items.append({"item": f"x{surface_count} units/surfaces", "low": 0, "high": 0})

    # Contamination line item
    if contamination_level > 1:
        line_items.append({
            "item": f"Contamination: {contam_cfg['name'].title()} (Lvl {contamination_level}) - {contam_mult_low}x-{contam_mult_high}x",
            "low": 0, "high": 0
        })

    # Complexity line item
    if geometry_complexity != "simple":
        line_items.append({
            "item": f"Geometry: {geometry_complexity.title()} - {geom_mult_low}x-{geom_mult_high}x",
            "low": 0, "high": 0
        })

    # Access line item
    if access_difficulty != "easy":
        line_items.append({
            "item": f"Access: {access_difficulty.title()} - {access_mult}x",
            "low": 0, "high": 0
        })

    # Risk premium
    if high_risk:
        quote_low *= risk_mult
        quote_high *= risk_mult
        line_items.append({"item": f"High-Risk Premium ({risk_mult}x)", "low": 0, "high": 0})

    # After hours premium
    if after_hours:
        quote_low *= hours_mult
        quote_high *= hours_mult
        line_items.append({"item": f"After-Hours Premium ({hours_mult}x)", "low": 0, "high": 0})

    # Setup & teardown
    setup_hrs = CFG["adjustments"]["setup_teardown_hours"]
    setup_cost = setup_hrs * CFG["pricing_models"]["hourly"]["base_range"]["low"]
    quote_low += setup_cost
    quote_high += setup_cost
    line_items.append({"item": f"Setup & Teardown ({setup_hrs}hr)", "low": setup_cost, "high": setup_cost})

    # Travel
    travel_cost, billable_miles = calculate_travel(travel_miles)
    if travel_cost > 0:
        quote_low += travel_cost
        quote_high += travel_cost
        line_items.append({"item": f"Travel ({billable_miles:.0f} mi beyond {CFG['adjustments']['travel']['local_radius_miles']} mi)", "low": travel_cost, "high": travel_cost})

    # Minimum
    min_charge = CFG["adjustments"]["minimum_charge"]
    minimum_applied = False
    if quote_low < min_charge:
        quote_low = min_charge
        minimum_applied = True

    # Round
    quote_low = round_quote(quote_low)
    quote_high = round_quote(quote_high)

    # Tighten the range — start from mid-range, cap the high at 1.8x of low
    # Customer-friendly: "Here's what it costs" not "It's somewhere between X and 5X"
    if quote_high > quote_low * 1.8:
        mid_point = (quote_low + quote_high) / 2
        quote_low = round_quote(mid_point * 0.85)
        quote_high = round_quote(mid_point * 1.25)
    
    # Ensure low < high
    if quote_low >= quote_high:
        quote_high = round_quote(quote_low * 1.3)

    # Upsells
    upsells = []
    for u in CFG["upsell_triggers"]:
        trigger = u["trigger"].lower()
        cat_lower = job_category.lower().replace("_", " ")
        if any(word in cat_lower for word in trigger.split()):
            upsells.append(u["upsell"])

    return {
        "pricing_model": pricing_model,
        "job_category": job_category,
        "job_category_label": cat_cfg["label"],
        "quote_low": quote_low,
        "quote_high": quote_high,
        "total_sqft": round(calc_sqft, 1),
        "estimated_hours": round(estimated_hours or 0, 1),
        "line_items": line_items,
        "breakdown": {
            "contamination_level": contamination_level,
            "contamination_name": contam_cfg["name"],
            "geometry_complexity": geometry_complexity,
            "access_difficulty": access_difficulty,
            "surface_count": surface_count,
            "after_hours": after_hours,
            "high_risk": high_risk,
            "travel_cost": travel_cost,
            "travel_miles": travel_miles,
            "setup_cost": setup_cost,
            "minimum_applied": minimum_applied,
        },
        "confidence_score": 0.7,
        "requires_onsite": False,
        "reasoning_summary": f"{cat_cfg['label']} with {contam_cfg['name']} contamination, {geometry_complexity} geometry, {access_difficulty} access. Pricing model: {pricing_model}.",
        "upsell_suggestions": upsells
    }


def calculate_quote_from_vision(
    vision_tags: dict,
    confidence_score: float,
    estimated_sqft: float = 0,
    estimated_hours: float = 0,
    travel_miles: float = 0,
) -> dict:
    """
    Calculate quote from AI vision tags output.
    Uses zone-based pricing for vehicles, standard pricing for industrial.
    """
    job_category = vision_tags.get("asset_type", "truck_engine_bay")

    # Check if this is a vehicle job — use zone-based pricing
    vehicle_categories = [
        "truck_engine_bay", "truck_undercarriage", "full_vehicle_restoration",
    ]
    class8_categories = [
        "class8_truck", "class8_daycab", "class8_sleeper", "heavy_commercial",
        "industrial_equipment_mobile", "vocational_truck",
    ]
    vehicle_zones = vision_tags.get("vehicle_zones")
    class8_zones = vision_tags.get("class8_zones")
    custom_items = vision_tags.get("custom_items")
    vehicle_size = vision_tags.get("vehicle_size", "pickup")

    # Route to custom item pricing (non-vehicle: jack stands, repair stations, etc.)
    if custom_items and not vehicle_zones and not class8_zones:
        result = _calculate_custom_items_quote(vision_tags, travel_miles)
        result["confidence_score"] = confidence_score
        result["visual_tags"] = vision_tags
        result["risk_flags"] = vision_tags.get("risk_flags", [])
        result["scope_expansion_flags"] = vision_tags.get("scope_expansion_flags", [])
        if confidence_score < CFG["confidence_thresholds"]["medium"]:
            result["requires_onsite"] = True
            result["reasoning_summary"] += " LOW CONFIDENCE: Requires on-site verification before final pricing."
        return result

    # Route to Class 8 pricing
    if job_category in class8_categories or class8_zones or vehicle_size == "class8":
        result = _calculate_class8_quote(vision_tags, travel_miles)
        result["confidence_score"] = confidence_score
        result["visual_tags"] = vision_tags
        result["risk_flags"] = vision_tags.get("risk_flags", [])
        result["scope_expansion_flags"] = vision_tags.get("scope_expansion_flags", [])
        if confidence_score < CFG["confidence_thresholds"]["medium"]:
            result["requires_onsite"] = True
            result["reasoning_summary"] += " LOW CONFIDENCE: Requires on-site verification before final pricing."
        return result

    # Route to pickup/light vehicle zone pricing
    if job_category in vehicle_categories or vehicle_zones:
        result = _calculate_vehicle_zone_quote(vision_tags, travel_miles)
        result["confidence_score"] = confidence_score
        result["visual_tags"] = vision_tags
        result["risk_flags"] = vision_tags.get("risk_flags", [])
        result["scope_expansion_flags"] = vision_tags.get("scope_expansion_flags", [])
        if confidence_score < CFG["confidence_thresholds"]["medium"]:
            result["requires_onsite"] = True
            result["reasoning_summary"] += " LOW CONFIDENCE: Requires on-site verification before final pricing."
        return result

    # Standard pricing for non-vehicle jobs
    contamination_level = vision_tags.get("contamination_level", 2)
    if contamination_level not in (1, 2, 3):
        contamination_level = 2

    geometry_complexity = vision_tags.get("geometry_complexity", "moderate")
    access_difficulty = vision_tags.get("access_difficulty", "easy")
    risk_flags = vision_tags.get("risk_flags", [])
    high_risk = len(risk_flags) > 0

    result = calculate_quote_from_params(
        job_category=job_category,
        contamination_level=contamination_level,
        geometry_complexity=geometry_complexity,
        access_difficulty=access_difficulty,
        estimated_sqft=estimated_sqft,
        estimated_hours=estimated_hours,
        travel_miles=travel_miles,
        high_risk=high_risk,
    )

    result["confidence_score"] = confidence_score

    if confidence_score < CFG["confidence_thresholds"]["medium"]:
        result["requires_onsite"] = True
        result["reasoning_summary"] += " LOW CONFIDENCE: Requires on-site verification before final pricing."

    if confidence_score >= CFG["confidence_thresholds"]["high"]:
        spread = result["quote_high"] - result["quote_low"]
        result["quote_high"] = round_quote(result["quote_low"] + spread * 0.6)
        if result["quote_high"] <= result["quote_low"]:
            result["quote_high"] = round_quote(result["quote_low"] * 1.15)

    result["visual_tags"] = vision_tags
    result["risk_flags"] = vision_tags.get("risk_flags", [])
    result["scope_expansion_flags"] = vision_tags.get("scope_expansion_flags", [])

    for flag in result["scope_expansion_flags"]:
        result["upsell_suggestions"].append(f"Scope expansion: {flag.replace('_', ' ')}")

    return result


def _calculate_custom_items_quote(vision_tags: dict, travel_miles: float = 0) -> dict:
    """
    Pricing for non-vehicle items (jack stands, repair stations, shop equipment, etc.).
    Uses the AI's custom_items list with per-item sqft and standard sqft pricing.
    Line items match EXACTLY what was identified in the photos.
    """
    custom_items = vision_tags.get("custom_items", [])
    contamination_level = vision_tags.get("contamination_level", 2)
    if contamination_level not in (1, 2, 3):
        contamination_level = 2
    contam_cfg = CFG["contamination_levels"].get(contamination_level, CFG["contamination_levels"][2])
    contam_mult = (contam_cfg["pricing_multiplier"]["low"] + contam_cfg["pricing_multiplier"]["high"]) / 2

    geometry = vision_tags.get("geometry_complexity", "moderate")
    geom_cfg = CFG["geometry_complexity"].get(geometry, CFG["geometry_complexity"]["moderate"])
    geom_mult = (geom_cfg["pricing_multiplier"]["low"] + geom_cfg["pricing_multiplier"]["high"]) / 2

    access = vision_tags.get("access_difficulty", "easy")
    access_cfg = CFG["access_difficulty"].get(access, CFG["access_difficulty"]["easy"])
    access_mult = access_cfg.get("pricing_multiplier", 1.0)

    # Base sqft rate for general equipment
    sqft_rate_low = CFG["pricing_models"]["square_foot"]["base_range"]["low"]
    sqft_rate_high = CFG["pricing_models"]["square_foot"]["base_range"]["high"]
    avg_rate = (sqft_rate_low + sqft_rate_high) / 2

    line_items = []
    total_sqft = 0
    total_amount = 0

    for item in custom_items:
        name = item.get("name", "Unknown Item")
        sqft = float(item.get("sqft", 0))
        notes = item.get("notes", "")
        if sqft <= 0:
            continue
        total_sqft += sqft
        item_cost = sqft * avg_rate * contam_mult * geom_mult * access_mult
        item_cost = round(item_cost)
        total_amount += item_cost
        desc = f"{name} ({sqft:.0f} sqft @ ${avg_rate:.2f}/sqft)"
        if notes:
            desc += f" — {notes}"
        line_items.append({"item": desc, "amount": item_cost})

    # Estimated hours
    est_hours = max(1, total_sqft / 150) * contam_cfg["time_multiplier"]
    est_hours = max(est_hours, 2)

    # Dry ice
    ice_lbs_per_hr = CFG["air_and_media"]["dry_ice_lb_per_hour"]
    ice_cost_per_lb = CFG["air_and_media"]["dry_ice_cost_per_lb"]
    total_ice_lbs = est_hours * ice_lbs_per_hr * contam_cfg["media_multiplier"]
    total_ice_cost = total_ice_lbs * ice_cost_per_lb
    line_items.append({"item": f"Dry Ice Media ({total_ice_lbs:.0f} lbs)", "amount": round(total_ice_cost)})
    total_amount += total_ice_cost

    # Operator
    operator_rate = 350
    operator_hours = max(8, math.ceil(est_hours))
    operator_cost = operator_rate * operator_hours
    line_items.append({"item": f"Operator ({operator_hours} hrs @ ${operator_rate}/hr, 8hr min)", "amount": operator_cost})
    total_amount += operator_cost

    # Setup
    setup_hrs = CFG["adjustments"]["setup_teardown_hours"]
    setup_cost = setup_hrs * CFG["pricing_models"]["hourly"]["base_range"]["low"]
    line_items.append({"item": f"Setup & Teardown ({setup_hrs}hr)", "amount": round(setup_cost)})
    total_amount += setup_cost

    # Travel
    travel_cost, billable_miles = calculate_travel(travel_miles)
    if travel_cost > 0:
        line_items.append({"item": f"Travel ({billable_miles:.0f} mi)", "amount": round(travel_cost)})
        total_amount += travel_cost

    # Minimums & rounding
    min_charge = CFG["adjustments"]["minimum_charge"]
    if total_amount < min_charge:
        total_amount = min_charge

    quote_total = round_quote(total_amount)

    return {
        "pricing_model": "custom_items",
        "job_category": vision_tags.get("asset_type", "general_equipment"),
        "job_category_label": "Equipment / Shop Items",
        "quote_total": quote_total,
        "quote_low": quote_total,
        "quote_high": round_quote(quote_total * 1.15),
        "total_sqft": round(total_sqft, 1),
        "estimated_hours": round(est_hours, 1),
        "line_items": line_items,
        "breakdown": {
            "contamination_level": contamination_level,
            "contamination_name": contam_cfg["name"],
            "geometry_complexity": geometry,
            "access_difficulty": access,
            "surface_count": len(custom_items),
            "travel_cost": travel_cost,
            "travel_miles": travel_miles,
            "setup_cost": setup_cost,
        },
        "requires_onsite": False,
        "reasoning_summary": f"{len(custom_items)} items identified for dry ice blasting. {contam_cfg['name']} contamination, {geometry} geometry. Total {total_sqft:.0f} sqft.",
        "upsell_suggestions": [],
    }



def _calculate_vehicle_zone_quote(vision_tags: dict, travel_miles: float = 0) -> dict:
    """
    Zone-based pricing for vehicle dry ice blasting.
    Breaks estimate into: undercarriage, wheel wells, engine bay, bed.
    Each zone priced by sqft with dry ice usage.
    """
    zones_cfg = CFG.get("vehicle_zones", {})
    contamination_level = vision_tags.get("contamination_level", 2)
    contam_cfg = CFG["contamination_levels"].get(contamination_level, CFG["contamination_levels"][2])
    contam_mult = (contam_cfg["pricing_multiplier"]["low"] + contam_cfg["pricing_multiplier"]["high"]) / 2

    # Determine vehicle size from vision tags
    vehicle_size = vision_tags.get("vehicle_size", "pickup")
    if vehicle_size not in ("pickup", "semi", "suv"):
        vehicle_size = "pickup"

    # Get zones from vision tags or use all zones
    active_zones = vision_tags.get("vehicle_zones") or list(zones_cfg.keys())
    if isinstance(active_zones, dict):
        # Vision returned zone data with sqft overrides
        zone_overrides = active_zones
        active_zones = list(zone_overrides.keys())
    else:
        zone_overrides = {}

    line_items = []
    total_low = 0
    total_high = 0
    total_hours = 0
    total_dry_ice_lbs = 0
    total_sqft = 0

    for zone_key in active_zones:
        zone = zones_cfg.get(zone_key)
        if not zone:
            continue

        # Get sqft for this zone — from vision override or default
        override = zone_overrides.get(zone_key, {})
        sqft = override.get("sqft", 0) or zone["typical_sqft"].get(vehicle_size, 0)
        if sqft <= 0:
            continue

        hours = override.get("hours", 0) or zone["labor_hours"].get(vehicle_size, 0)
        rate_low = zone["rate_per_sqft"]["low"]
        rate_high = zone["rate_per_sqft"]["high"]
        dry_ice_lbs = sqft * zone["dry_ice_lbs_per_sqft"]

        zone_low = round(sqft * rate_low * contam_mult)
        zone_high = round(sqft * rate_high * contam_mult)

        line_items.append({
            "item": f"{zone['label']} ({sqft:.0f} sqft, ~{dry_ice_lbs:.0f} lbs dry ice, ~{hours:.1f} hrs)",
            "low": zone_low,
            "high": zone_high,
            "category": "Service",
        })

        total_low += zone_low
        total_high += zone_high
        total_hours += hours
        total_dry_ice_lbs += dry_ice_lbs
        total_sqft += sqft

    # Dry ice materials line item
    ice_cost = round(total_dry_ice_lbs * CFG["air_and_media"]["dry_ice_cost_per_lb"])
    line_items.append({
        "item": f"Dry Ice Media ({total_dry_ice_lbs:.0f} lbs @ ${CFG['air_and_media']['dry_ice_cost_per_lb']:.2f}/lb)",
        "low": ice_cost,
        "high": round(ice_cost * 1.2),
    })
    total_low += ice_cost
    total_high += round(ice_cost * 1.2)

    # Travel
    travel_cost, billable_miles = calculate_travel(travel_miles)
    if travel_cost > 0:
        total_low += round(travel_cost)
        total_high += round(travel_cost)
        line_items.append({
            "item": f"Travel ({billable_miles:.0f} mi beyond {CFG['adjustments']['travel']['local_radius_miles']} mi)",
            "low": round(travel_cost),
            "high": round(travel_cost),
        })

    # Minimum
    min_charge = CFG["adjustments"]["minimum_charge"]
    if total_low < min_charge:
        total_low = min_charge

    # Round
    total_low = round_quote(total_low)
    total_high = round_quote(total_high)

    # Tighten range if too wide
    if total_high > total_low * 1.6:
        mid = (total_low + total_high) / 2
        total_low = round_quote(mid * 0.88)
        total_high = round_quote(mid * 1.15)

    if total_low >= total_high:
        total_high = round_quote(total_low * 1.2)

    return {
        "pricing_model": "vehicle_zone",
        "job_category": vision_tags.get("asset_type", "full_vehicle_restoration"),
        "job_category_label": f"Vehicle Dry Ice Blasting ({vehicle_size.title()})",
        "quote_low": total_low,
        "quote_high": total_high,
        "total_sqft": round(total_sqft, 1),
        "estimated_hours": round(total_hours, 1),
        "dry_ice_lbs": round(total_dry_ice_lbs),
        "line_items": line_items,
        "breakdown": {
            "contamination_level": contamination_level,
            "contamination_name": contam_cfg["name"],
            "vehicle_size": vehicle_size,
            "zones": active_zones,
            "travel_cost": travel_cost,
            "travel_miles": travel_miles,
        },
        "confidence_score": 0.75,
        "requires_onsite": False,
        "reasoning_summary": f"Vehicle zone-based estimate: {len(active_zones)} zones, {total_sqft:.0f} sqft total, ~{total_dry_ice_lbs:.0f} lbs dry ice, ~{total_hours:.0f} hrs labor.",
        "upsell_suggestions": [],
    }


def _calculate_class8_quote(vision_tags: dict, travel_miles: float = 0) -> dict:
    """
    Class 8 / heavy commercial truck pricing.
    Uses per-sqft rates with dry ice baked in.
    Operator charge: $350/hr, 8hr minimum.
    Dry ice ordered in 500lb increments.
    """
    class8_cfg = CFG.get("class8_zones", {})
    contamination_level = vision_tags.get("contamination_level", 2)
    contam_cfg = CFG["contamination_levels"].get(contamination_level, CFG["contamination_levels"][2])
    contam_mult = (contam_cfg["pricing_multiplier"]["low"] + contam_cfg["pricing_multiplier"]["high"]) / 2

    # Get zone sqft from vision tags (class8_zones) or vehicle_zones
    zone_data = vision_tags.get("class8_zones") or vision_tags.get("vehicle_zones") or {}
    if isinstance(zone_data, list):
        # Convert list of zone names to dict
        zone_data = {z: {} for z in zone_data}

    # Vehicle info for display
    num_axles = vision_tags.get("num_axles", 0)
    engine_info = vision_tags.get("engine", "")
    transmission = vision_tags.get("transmission", "")

    line_items = []
    total_cost = 0
    total_sqft = 0
    total_dry_ice_lbs = 0
    total_hours = 0
    zone_details = []

    for zone_key, zone_override in zone_data.items():
        zone_cfg = class8_cfg.get(zone_key)
        if not zone_cfg:
            continue

        # Get sqft from override or skip if 0
        if isinstance(zone_override, dict):
            sqft = zone_override.get("sqft", 0)
        else:
            sqft = zone_override if isinstance(zone_override, (int, float)) else 0

        if sqft <= 0:
            continue

        rate = zone_cfg["rate_per_sqft"]
        dry_ice_rate = zone_cfg["dry_ice_lbs_per_sqft"]
        dry_ice_lbs = round(sqft * dry_ice_rate * contam_mult)
        zone_cost = round(sqft * rate * contam_mult)

        # Estimate hours: ~10 sqft/min = 600 sqft/hr
        zone_hours = round(sqft / 60, 1)  # conservative 1 sqft/min for complex areas

        line_items.append({
            "item": f"{zone_cfg['label']} ({sqft:.0f} sqft @ ${rate:.2f}/sqft)",
            "amount": zone_cost,
            "sqft": sqft,
            "dry_ice_lbs": dry_ice_lbs,
            "category": "Service",
        })

        zone_details.append({
            "zone": zone_key,
            "label": zone_cfg["label"],
            "sqft": sqft,
            "rate": rate,
            "cost": zone_cost,
            "dry_ice_lbs": dry_ice_lbs,
        })

        total_cost += zone_cost
        total_sqft += sqft
        total_dry_ice_lbs += dry_ice_lbs
        total_hours += zone_hours

    # Round dry ice to 500lb increments
    increment = CFG.get("dry_ice_order_increment_lbs", 500)
    dry_ice_order = ((total_dry_ice_lbs + increment - 1) // increment) * increment
    if dry_ice_order < increment and total_dry_ice_lbs > 0:
        dry_ice_order = increment

    # Operator charge: $350/hr, 8hr minimum
    operator_rate = CFG["adjustments"]["operator_rate_per_hour"]
    operator_min_hours = CFG["adjustments"]["operator_minimum_hours"]
    operator_hours = max(total_hours, operator_min_hours)
    operator_cost = round(operator_hours * operator_rate)

    line_items.append({
        "item": f"Operator ({operator_hours:.0f} hrs @ ${operator_rate}/hr, {operator_min_hours}hr min)",
        "amount": operator_cost,
        "category": "Labor",
    })

    # Dry ice line item (informational — cost baked into sqft rate)
    line_items.append({
        "item": f"Dry Ice Media ({dry_ice_order:,} lbs — {dry_ice_order // increment} x {increment}lb blocks)",
        "amount": 0,
        "category": "Materials (included)",
    })

    # Travel
    travel_cost, billable_miles = calculate_travel(travel_miles)
    if travel_cost > 0:
        line_items.append({
            "item": f"Travel ({billable_miles:.0f} mi beyond {CFG['adjustments']['travel']['local_radius_miles']} mi)",
            "amount": round(travel_cost),
            "category": "Travel",
        })

    grand_total = total_cost + operator_cost + round(travel_cost)

    # Minimum
    min_charge = CFG["adjustments"]["minimum_charge"]
    if grand_total < min_charge:
        grand_total = min_charge

    grand_total = round_quote(grand_total)

    # Build display name
    asset_type = vision_tags.get("asset_type", "class8_truck")
    make = vision_tags.get("make", "")
    model = vision_tags.get("model", "")
    display = f"{make} {model}".strip() if make else "Class 8 Truck"

    return {
        "pricing_model": "class8_zone",
        "job_category": asset_type,
        "job_category_label": f"Heavy Commercial Dry Ice Blasting — {display}",
        "quote_total": grand_total,
        "quote_low": grand_total,
        "quote_high": grand_total,
        "total_sqft": round(total_sqft, 1),
        "estimated_hours": round(operator_hours, 1),
        "dry_ice_lbs": total_dry_ice_lbs,
        "dry_ice_order_lbs": dry_ice_order,
        "dry_ice_blocks": dry_ice_order // increment,
        "operator_cost": operator_cost,
        "operator_hours": operator_hours,
        "operator_rate": operator_rate,
        "line_items": line_items,
        "zone_details": zone_details,
        "breakdown": {
            "contamination_level": contamination_level,
            "contamination_name": contam_cfg["name"],
            "num_axles": num_axles,
            "engine": engine_info,
            "transmission": transmission,
            "vehicle_size": "class8",
            "zones": list(zone_data.keys()),
            "travel_cost": travel_cost,
            "travel_miles": travel_miles,
        },
        "confidence_score": 0.85,
        "requires_onsite": False,
        "reasoning_summary": f"Class 8 estimate: {len(zone_details)} zones, {total_sqft:.0f} sqft total, {dry_ice_order:,} lbs dry ice ({dry_ice_order // increment} blocks), {operator_hours:.0f} hrs operator time.",
        "upsell_suggestions": [],
    }


# ============================================================
# RESALE PREPARATION SERVICE — Tiered Quote Calculator
# ============================================================

def calculate_resale_prep_quote(
    equipment_type: str,
    service_tier: str,
    num_units: int = 1,
    condition: str = "moderate",
    travel_miles: float = 0,
) -> dict:
    """
    Calculate a resale preparation quote using tiered pricing.
    equipment_type: line_pump, mid_boom_pump, large_boom_pump, semi_truck, pickup_truck, car_suv
    service_tier: clean_only, clean_and_polish, full_resale_prep
    condition: light, moderate, heavy
    """
    equip = RESALE_CFG["equipment_types"].get(equipment_type)
    if not equip:
        return {"error": f"Unknown equipment type: {equipment_type}. Valid: {list(RESALE_CFG['equipment_types'].keys())}"}

    tier = RESALE_CFG["service_tiers"].get(service_tier)
    if not tier:
        return {"error": f"Unknown tier: {service_tier}. Valid: {list(RESALE_CFG['service_tiers'].keys())}"}

    # Condition multiplier
    condition_mult = {"light": 0.85, "moderate": 1.0, "heavy": 1.25}.get(condition, 1.0)

    # Base cleaning cost per unit
    base_low = equip["base_clean"]["low"] * condition_mult
    base_high = equip["base_clean"]["high"] * condition_mult

    line_items = []
    total_low = 0
    total_high = 0

    # Line item: Base cleaning
    clean_low = round(base_low)
    clean_high = round(base_high)
    total_low += clean_low
    total_high += clean_high
    line_items.append({
        "item": f"Dry Ice Blasting — {equip['label']} ({condition} buildup)",
        "low": clean_low,
        "high": clean_high,
    })

    # Add wheel polishing if tier includes it
    if "wheel_polishing" in tier["includes"]:
        wp = RESALE_CFG["addons"]["wheel_polishing"]["price"]
        total_low += wp["low"]
        total_high += wp["high"]
        line_items.append({
            "item": "Wheel Polishing & Detail Finish",
            "low": wp["low"],
            "high": wp["high"],
        })

    # Add protective coating if tier includes it
    if "protective_coating" in tier["includes"]:
        coat = equip["coating"]
        total_low += coat["low"]
        total_high += coat["high"]
        kits = RESALE_CFG["addons"]["protective_coating"]["kits_per_equipment"].get(equipment_type, 2)
        mat_cost = kits * RESALE_CFG["addons"]["protective_coating"]["material_cost_per_kit"]
        line_items.append({
            "item": f"IGL Aegis Graphene Coating ({kits} kits, 15yr protection)",
            "low": coat["low"],
            "high": coat["high"],
        })

    # Operator cost
    sqft_range = equip["typical_sqft"]
    avg_sqft = (sqft_range["low"] + sqft_range["high"]) / 2
    est_hours = max(avg_sqft / 150, 2) * condition_mult
    operator_rate = RESALE_CFG["operator"]["rate_per_hour"]
    min_hours = RESALE_CFG["operator"]["minimum_hours"]
    operator_hours = max(min_hours, math.ceil(est_hours))
    operator_cost = operator_hours * operator_rate
    total_low += operator_cost
    total_high += operator_cost
    line_items.append({
        "item": f"Operator ({operator_hours} hrs @ ${operator_rate}/hr, {min_hours}hr min)",
        "low": operator_cost,
        "high": operator_cost,
    })

    # Travel
    travel_cost, billable_miles = calculate_travel(travel_miles)
    if travel_cost > 0:
        total_low += travel_cost
        total_high += travel_cost
        line_items.append({
            "item": f"Travel ({billable_miles:.0f} mi)",
            "low": round(travel_cost),
            "high": round(travel_cost),
        })

    # Per-unit totals
    unit_low = round_quote(total_low)
    unit_high = round_quote(total_high)

    # Multi-unit
    if num_units > 1:
        # Apply volume discount
        discount = 0
        for vd in sorted(RESALE_CFG["volume_discounts"], key=lambda x: x["min_units"], reverse=True):
            if num_units >= vd["min_units"]:
                discount = vd["discount"]
                break

        fleet_low = unit_low * num_units
        fleet_high = unit_high * num_units

        if discount > 0:
            savings_low = round(fleet_low * discount)
            savings_high = round(fleet_high * discount)
            fleet_low -= savings_low
            fleet_high -= savings_high
            line_items.append({
                "item": f"Volume Discount ({int(discount * 100)}% off {num_units} units)",
                "low": -savings_low,
                "high": -savings_high,
            })

        quote_low = round_quote(fleet_low)
        quote_high = round_quote(fleet_high)
    else:
        quote_low = unit_low
        quote_high = unit_high

    return {
        "pricing_model": "resale_prep",
        "job_category": "resale_preparation",
        "job_category_label": f"Resale Prep — {equip['label']}",
        "service_tier": service_tier,
        "service_tier_label": tier["label"],
        "equipment_type": equipment_type,
        "equipment_label": equip["label"],
        "num_units": num_units,
        "condition": condition,
        "quote_low": quote_low,
        "quote_high": quote_high,
        "unit_price_low": unit_low,
        "unit_price_high": unit_high,
        "line_items": line_items,
        "estimated_hours": round(est_hours, 1),
        "total_sqft": round(avg_sqft),
        "breakdown": {
            "equipment_type": equipment_type,
            "service_tier": service_tier,
            "condition": condition,
            "num_units": num_units,
            "volume_discount": discount if num_units > 1 else 0,
            "includes": tier["includes"],
            "travel_cost": travel_cost,
            "travel_miles": travel_miles,
        },
        "requires_onsite": False,
        "confidence_score": 0.9,
        "reasoning_summary": f"{tier['label']} for {num_units}x {equip['label']}. {condition.title()} condition. Includes: {', '.join(tier['includes'])}.",
        "value_framing": RESALE_CFG["value_framing"],
        "upsell_suggestions": [
            "Upgrade to Full Resale Prep for maximum buyer confidence" if service_tier != "full_resale_prep" else "Add before/after photo documentation for listing",
        ],
    }
