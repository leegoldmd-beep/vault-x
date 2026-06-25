"""All Pydantic models for the LeadForge API."""
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    remember_me: Optional[bool] = False

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    created_at: datetime

class BusinessProfileCreate(BaseModel):
    business_name: str
    industry: str
    services: List[str]
    location: str
    target_customers: Optional[str] = ""
    budget: Optional[str] = ""
    preferred_lead_sources: Optional[List[str]] = []
    niches: Optional[List[str]] = []
    description: Optional[str] = ""
    social_links: Optional[dict] = {}

class LeadCreate(BaseModel):
    lead_name: str
    industry: str
    contact_info: Optional[str] = ""
    source: Optional[str] = ""
    status: Optional[str] = "new"
    notes: Optional[str] = ""
    url: Optional[str] = ""
    platform: Optional[str] = ""
    opportunity_type: Optional[str] = ""
    ai_confidence: Optional[float] = 0.0
    deal_value: Optional[float] = 0.0
    phone: Optional[str] = ""
    address: Optional[str] = ""
    contact_name: Optional[str] = ""

class GenerateLeadsRequest(BaseModel):
    search_query: Optional[str] = ""
    industry: Optional[str] = ""
    location: Optional[str] = ""

class ReferralPlatformRequest(BaseModel):
    industry: str
    services: List[str]

class WorkTypeCreate(BaseModel):
    name: str
    category: str
    description: Optional[str] = ""
    keywords: Optional[List[str]] = []

class MonitoringConfigUpdate(BaseModel):
    platforms: List[str]
    scan_time: Optional[str] = "06:00"
    enabled: Optional[bool] = True
    keywords: Optional[List[str]] = []

class OpportunityScanRequest(BaseModel):
    platforms: Optional[List[str]] = None
    keywords: Optional[List[str]] = None

class FollowUpRequest(BaseModel):
    lead_id: str
    follow_up_type: str
    custom_notes: Optional[str] = ""

class QuoteRequest(BaseModel):
    lead_id: Optional[str] = None
    job_type: str
    measurements: Optional[dict] = None
    surface_count: Optional[int] = 1
    custom_price: Optional[float] = None
    notes: Optional[str] = ""
    contamination_level: Optional[int] = 2
    geometry_complexity: Optional[str] = "moderate"
    access_difficulty: Optional[str] = "easy"
    estimated_sqft: Optional[float] = 0
    estimated_hours: Optional[float] = 0
    travel_miles: Optional[float] = 0
    after_hours: Optional[bool] = False
    high_risk: Optional[bool] = False
    quick_mode: Optional[bool] = False

class VoiceCallRequest(BaseModel):
    lead_id: str
    call_type: str
    custom_script: Optional[str] = ""

class DemoRequestModel(BaseModel):
    name: str
    company: Optional[str] = ""
    phone: str
    email: Optional[str] = ""
    preferred_date: Optional[str] = ""
    preferred_time: Optional[str] = ""
    services_interested: Optional[list] = []
    notes: Optional[str] = ""

class TikTokScanRequest(BaseModel):
    location: Optional[str] = ""
    keywords: Optional[list] = []
    hashtag_categories: Optional[List[str]] = None
    max_results: Optional[int] = 20
