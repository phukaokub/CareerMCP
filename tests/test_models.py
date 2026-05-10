"""Tests for career_mcp.models."""

import pytest
from career_mcp.models import (
    ApplicationStatus,
    EmploymentType,
    JobListing,
    MatchResult,
    UserProfile,
    WorkMode,
)


def _make_profile(**overrides) -> UserProfile:
    defaults = dict(
        full_name="Alice Smith",
        email="alice@example.com",
        technical_skills=["Python", "React", "Docker"],
        soft_skills=["Communication", "Leadership"],
        preferred_job_titles=["Senior Software Engineer", "Staff Engineer"],
        work_modes=[WorkMode.remote, WorkMode.hybrid],
        preferred_locations=["Bangkok", "Remote"],
        salary_currency="THB",
        salary_min=80_000,
        salary_max=200_000,
        career_goal="Seeking a senior engineering role.",
        experience_summary="5 years of Python and React experience.",
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def test_user_profile_all_skills():
    p = _make_profile()
    assert "Python" in p.all_skills
    assert "Communication" in p.all_skills
    assert len(p.all_skills) == 5


def test_user_profile_defaults():
    p = UserProfile(full_name="Bob", email="bob@example.com")
    assert p.all_skills == []
    assert p.auto_apply_enabled is True
    assert p.auto_apply_min_score == 70
    assert p.auto_apply_max_per_run == 10


def test_job_listing_creation():
    job = JobListing(
        id="JOB001",
        source="linkedin",
        title="Senior Software Engineer",
        company="Acme Corp",
        location="Bangkok",
        work_mode=WorkMode.hybrid,
        employment_type=EmploymentType.full_time,
        salary_min=90_000,
        salary_max=150_000,
        salary_currency="THB",
        description="We need a Python developer.",
        requirements=["Python", "Docker"],
        url="https://linkedin.com/jobs/JOB001",
    )
    assert job.id == "JOB001"
    assert job.work_mode == WorkMode.hybrid
    assert job.employment_type == EmploymentType.full_time


def test_match_result_creation():
    job = JobListing(
        id="J1", source="jobsdb", title="Engineer", company="Startup", location="Remote"
    )
    mr = MatchResult(
        job=job,
        score=85,
        matched_skills=["Python"],
        missing_skills=["Kubernetes"],
        match_reasons="Matched Python.",
    )
    assert mr.score == 85
    assert "Python" in mr.matched_skills


def test_application_status_enum_values():
    assert ApplicationStatus.applied.value == "applied"
    assert ApplicationStatus.interviewing.value == "interviewing"
