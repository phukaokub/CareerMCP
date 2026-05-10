"""Tests for career_mcp.auto_apply."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from career_mcp.auto_apply import AutoApplyEngine
from career_mcp.database import JobDatabase
from career_mcp.models import (
    ApplicationStatus,
    JobListing,
    MatchResult,
    UserProfile,
    WorkMode,
)


def _profile(**overrides) -> UserProfile:
    defaults = dict(
        full_name="Alice Smith",
        email="alice@example.com",
        technical_skills=["Python"],
        preferred_job_titles=["Senior Software Engineer"],
        work_modes=[WorkMode.remote],
        career_goal="Looking for a senior role.",
        auto_apply_enabled=True,
        auto_apply_min_score=70,
        auto_apply_max_per_run=5,
        cover_letter_template="Dear {company}, I want {job_title}. {match_reasons} {career_goal} - {full_name}",
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _match(score: int = 85, job_id: str = "J1") -> MatchResult:
    job = JobListing(
        id=job_id,
        source="linkedin",
        title="Senior Software Engineer",
        company="Acme Tech",
        location="Bangkok",
        url=f"https://linkedin.com/jobs/{job_id}",
    )
    return MatchResult(
        job=job,
        score=score,
        matched_skills=["Python"],
        match_reasons="Matched Python.",
    )


@pytest.fixture
async def db(tmp_path: Path) -> JobDatabase:
    database = JobDatabase(tmp_path / "test.db")
    await database.initialise()
    return database


class TestBuildCoverLetter:
    def test_renders_template(self, tmp_path):
        p = _profile()
        db = JobDatabase(tmp_path / "t.db")
        engine = AutoApplyEngine(p, db)
        m = _match()
        letter = engine.build_cover_letter(m)
        assert "Acme Tech" in letter
        assert "Senior Software Engineer" in letter
        assert "Alice Smith" in letter

    def test_uses_default_template_when_none(self, tmp_path):
        p = _profile(cover_letter_template="")
        db = JobDatabase(tmp_path / "t.db")
        engine = AutoApplyEngine(p, db)
        m = _match()
        letter = engine.build_cover_letter(m)
        assert "Acme Tech" in letter


class TestApply:
    async def test_successful_apply_updates_status(self, db: JobDatabase):
        engine = AutoApplyEngine(_profile(), db)
        caller = AsyncMock(return_value={"status": "submitted"})
        rec = await engine.apply(_match(), caller)
        assert rec.status == ApplicationStatus.applied
        assert rec.applied_at is not None

    async def test_failed_apply_marks_discovered(self, db: JobDatabase):
        engine = AutoApplyEngine(_profile(), db)
        caller = AsyncMock(side_effect=Exception("Network error"))
        rec = await engine.apply(_match(), caller)
        assert rec.status == ApplicationStatus.discovered

    async def test_caller_receives_correct_tool_name(self, db: JobDatabase):
        engine = AutoApplyEngine(_profile(), db)
        caller = AsyncMock(return_value={})
        await engine.apply(_match(), caller)
        called_tool = caller.call_args[0][0]
        assert called_tool == "linkedin__apply_job"


class TestProcessMatches:
    async def test_respects_max_per_run(self, db: JobDatabase):
        p = _profile(auto_apply_max_per_run=2)
        engine = AutoApplyEngine(p, db)
        caller = AsyncMock(return_value={})
        matches = [_match(score=90, job_id=f"J{i}") for i in range(5)]
        applied = await engine.process_matches(matches, caller)
        assert len(applied) <= 2

    async def test_skips_below_min_score(self, db: JobDatabase):
        p = _profile(auto_apply_min_score=80)
        engine = AutoApplyEngine(p, db)
        caller = AsyncMock(return_value={})
        matches = [_match(score=60, job_id="J_low")]
        applied = await engine.process_matches(matches, caller)
        assert len(applied) == 0

    async def test_skips_already_applied(self, db: JobDatabase):
        engine = AutoApplyEngine(_profile(), db)
        caller = AsyncMock(return_value={})
        m = _match()
        # First apply
        await engine.apply(m, caller)
        # Second run
        caller.reset_mock()
        applied = await engine.process_matches([m], caller)
        # Should skip because already applied
        assert len(applied) == 0
        # Caller should not have been called again
        caller.assert_not_called()

    async def test_disabled_auto_apply_returns_empty(self, db: JobDatabase):
        p = _profile(auto_apply_enabled=False)
        engine = AutoApplyEngine(p, db)
        caller = AsyncMock(return_value={})
        applied = await engine.process_matches([_match()], caller)
        assert applied == []
