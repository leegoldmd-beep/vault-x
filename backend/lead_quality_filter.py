"""
Lead Quality Filter — Universal validation for ALL lead generators.
Ensures leads are companies that NEED dry ice cleaning services,
not job postings, recipe sites, media, or irrelevant content.
"""

import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Domains that are NEVER valid leads
JUNK_DOMAINS = [
    # Job boards
    "indeed.com", "glassdoor.com", "ziprecruiter.com", "monster.com",
    "careerbuilder.com", "linkedin.com/jobs", "simplyhired.com",
    "salary.com", "payscale.com", "snagajob.com",
    # Media / recipes / entertainment
    "foodnetwork.com", "allrecipes.com", "food.com", "epicurious.com",
    "bonappetit.com", "delish.com", "tastingtable.com", "eater.com",
    "thekitchn.com", "seriouseats.com", "cookinglight.com",
    "youtube.com", "youtu.be", "tiktok.com", "pinterest.com",
    "reddit.com", "quora.com", "medium.com", "buzzfeed.com",
    "wikipedia.org", "wikihow.com",
    # Social media
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "snapchat.com", "threads.net",
    # Shopping
    "amazon.com", "ebay.com", "walmart.com", "etsy.com",
    "shopify.com", "alibaba.com", "aliexpress.com",
    # Generic info
    "nist.gov", "census.gov", "bls.gov",
]

# Title/content patterns that indicate NOT a valid lead
JUNK_PATTERNS = [
    # Job postings
    r"\b(hiring|job opening|apply now|career|employment|we.re hiring)\b",
    r"\b(job description|salary|per hour|benefits|resume|applicant)\b",
    r"\b(full.time|part.time|shift|remote position|work from home)\b",
    r"\b(cleaner wanted|janitor wanted|looking for.*cleaner)\b",
    r"\b(maintenance tech|custodian|housekeeper|cleaning crew)\b",
    # Recipes / cooking
    r"\b(recipe|recipes|cooking|cookbook|ingredient|bake|baking)\b",
    r"\b(dinner|breakfast|lunch|appetizer|dessert|seasoning)\b",
    r"\b(ree drummond|pioneer woman|food network|gordon ramsay)\b",
    r"\b(chef|culinary|meal prep|nutrition facts)\b",
    # News / entertainment
    r"\b(episode|tv show|watch now|streaming|podcast|subscribe)\b",
    r"\b(celebrity|entertainment|movie|film|song|album)\b",
    # Education / how-to (not services)
    r"\b(how to clean|cleaning tips|diy|tutorial|guide to)\b",
    r"\b(what is dry ice|definition of|history of)\b",
]

# Compiled patterns for performance
_JUNK_REGEXES = [re.compile(p, re.IGNORECASE) for p in JUNK_PATTERNS]

# Industries/keywords that indicate a company NEEDS outsourced cleaning
VALID_LEAD_INDICATORS = [
    # Industries that need dry ice blasting
    "fleet", "trucking", "logistics", "freight", "transportation",
    "manufacturing", "factory", "production", "assembly",
    "food processing", "food production", "beverage", "dairy", "bakery",
    "oil", "gas", "petroleum", "refinery", "pipeline",
    "power plant", "utility", "energy", "substation", "generator",
    "aerospace", "aviation", "aircraft", "defense",
    "automotive", "dealership", "body shop", "collision",
    "construction", "heavy equipment", "excavat", "crane",
    "warehouse", "distribution", "fulfillment",
    "hospital", "medical", "healthcare", "pharmaceutical",
    "church", "worship", "cathedral", "temple", "mosque",
    "school", "university", "campus",
    "hotel", "resort", "hospitality",
    "marina", "shipyard", "marine",
    "fire damage", "fire restoration", "smoke damage", "soot",
    "mold", "remediation", "restoration",
    "monument", "historic", "facade", "masonry",
    # Equipment that needs cleaning
    "engine", "motor", "compressor", "turbine", "pump",
    "conveyor", "mixer", "extruder", "press", "lathe",
    "hvac", "ductwork", "ventilation", "cooling tower",
    "switchgear", "transformer", "electrical panel",
    "tank", "vessel", "reactor", "boiler",
    "printing press", "packaging", "bottling",
    # Facility types
    "plant", "facility", "complex", "terminal", "depot",
    "hangar", "dock", "pier", "wharf",
    "park", "playground", "recreation", "bench",
    "bus stop", "transit", "shelter",
    "bounce house", "inflatable", "gym", "fitness",
]


def is_junk_domain(url: str) -> bool:
    """Check if URL is from a known junk domain."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in JUNK_DOMAINS)


def is_junk_content(title: str, description: str = "") -> bool:
    """Check if the title/description contains junk patterns (job postings, recipes, etc.)."""
    text = f"{title} {description}"
    return any(rx.search(text) for rx in _JUNK_REGEXES)


def has_valid_lead_signal(title: str, description: str = "", url: str = "") -> bool:
    """Check if a lead has any signal that it's a company needing cleaning services."""
    text = f"{title} {description} {url}".lower()
    return any(indicator in text for indicator in VALID_LEAD_INDICATORS)


def validate_lead(title: str, url: str = "", description: str = "", strict: bool = False) -> tuple:
    """Validate a potential lead. Returns (is_valid, rejection_reason).
    
    strict=True requires a positive signal (company needs cleaning).
    strict=False only rejects obvious junk.
    """
    if is_junk_domain(url):
        return False, "junk_domain"
    
    if is_junk_content(title, description):
        return False, "junk_content"
    
    if strict and not has_valid_lead_signal(title, description, url):
        return False, "no_valid_signal"
    
    return True, "ok"


def validate_2026_only(title: str, description: str = "", url: str = "") -> tuple:
    """Validate that content is from 2026. Returns (is_valid, rejection_reason)."""
    text = f"{title} {description} {url}".lower()
    
    OLD_YEARS = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"]
    has_old = any(yr in text for yr in OLD_YEARS)
    has_2026 = "2026" in text
    
    if has_old and not has_2026:
        return False, "old_year_content"
    
    return True, "ok"


def filter_leads_batch(leads: list, strict: bool = False, require_2026: bool = False) -> list:
    """Filter a batch of leads, removing junk. Returns only valid leads."""
    valid = []
    for lead in leads:
        title = lead.get("title", lead.get("lead_name", lead.get("business_name", "")))
        url = lead.get("url", lead.get("source_url", lead.get("link", "")))
        desc = lead.get("description", lead.get("snippet", lead.get("notes", "")))
        
        is_valid, reason = validate_lead(title, url, desc, strict=strict)
        if not is_valid:
            logger.debug(f"Filtered lead [{reason}]: {title[:50]}")
            continue
        
        if require_2026:
            is_valid_date, reason = validate_2026_only(title, desc, url)
            if not is_valid_date:
                logger.debug(f"Filtered lead [{reason}]: {title[:50]}")
                continue
        
        valid.append(lead)
    
    return valid
