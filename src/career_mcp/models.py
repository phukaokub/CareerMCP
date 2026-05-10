"""Pydantic data models used across the CareerMCP project."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

_UTC = timezone.utc


class EmploymentType(str, Enum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    freelance = "freelance"
    internship = "internship"


class WorkMode(str, Enum):
    remote = "remote"
    hybrid = "hybrid"
    on_site = "on_site"


class ApplicationStatus(str, Enum):
    discovered = "discovered"
    matched = "matched"
    applied = "applied"
    rejected = "rejected"
    interviewing = "interviewing"
    offered = "offered"
    accepted = "accepted"
    declined = "declined"


class JobListing(BaseModel):
    """A single job listing retrieved from LinkedIn or JobsDB."""

    id: str
    source: str  # "linkedin" | "jobsdb"
    title: str
    company: str
    location: str
    work_mode: Optional[WorkMode] = None
    employment_type: Optional[EmploymentType] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None
    description: str = ""
    requirements: list[str] = Field(default_factory=list)
    url: str = ""
    posted_at: Optional[datetime] = None
    raw: dict = Field(default_factory=dict, exclude=True)


class MatchResult(BaseModel):
    """Result of matching a JobListing against the user's profile."""

    job: JobListing
    score: int  # 0–100
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    match_reasons: str = ""
    disqualifiers: list[str] = Field(default_factory=list)


class ApplicationRecord(BaseModel):
    """Persisted record of a job application."""

    id: Optional[int] = None
    job_id: str
    source: str
    title: str
    company: str
    location: str
    url: str
    match_score: int
    status: ApplicationStatus = ApplicationStatus.discovered
    cover_letter: str = ""
    notes: str = ""
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(_UTC))
    applied_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(_UTC))


class UserProfile(BaseModel):
    """Loaded user profile from user_profile.yaml."""

    full_name: str
    email: str
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    portfolio_url: str = ""
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    experience_summary: str = ""
    career_goal: str = ""
    preferred_job_titles: list[str] = Field(default_factory=list)
    employment_types: list[EmploymentType] = Field(default_factory=list)
    work_modes: list[WorkMode] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    salary_currency: str = "THB"
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    preferred_industries: list[str] = Field(default_factory=list)
    preferred_company_sizes: list[str] = Field(default_factory=list)
    blacklisted_companies: list[str] = Field(default_factory=list)
    auto_apply_enabled: bool = True
    auto_apply_min_score: int = 70
    auto_apply_max_per_run: int = 10
    cover_letter_template: str = ""

    @property
    def all_skills(self) -> list[str]:
        return self.technical_skills + self.soft_skills
