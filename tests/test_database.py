"""Tests for career_mcp.database."""

import pytest
from pathlib import Path

from career_mcp.database import JobDatabase
from career_mcp.models import ApplicationRecord, ApplicationStatus


@pytest.fixture
async def db(tmp_path: Path) -> JobDatabase:
    database = JobDatabase(tmp_path / "test.db")
    await database.initialise()
    return database


def _record(**overrides) -> ApplicationRecord:
    defaults = dict(
        job_id="JOB001",
        source="linkedin",
        title="Senior Software Engineer",
        company="Acme Corp",
        location="Bangkok",
        url="https://linkedin.com/jobs/JOB001",
        match_score=85,
    )
    defaults.update(overrides)
    return ApplicationRecord(**defaults)


class TestUpsertApplication:
    async def test_insert_creates_record(self, db: JobDatabase):
        rec = await db.upsert_application(_record())
        assert rec.id is not None
        assert rec.id > 0

    async def test_upsert_updates_existing(self, db: JobDatabase):
        r1 = await db.upsert_application(_record(match_score=70))
        r2 = await db.upsert_application(_record(match_score=90))
        # Same job_id + source → should be same row
        assert r1.id == r2.id
        # Score should be updated
        fetched = await db.get_application("JOB001", "linkedin")
        assert fetched is not None
        assert fetched.match_score == 90

    async def test_different_sources_are_separate(self, db: JobDatabase):
        r1 = await db.upsert_application(_record(source="linkedin"))
        r2 = await db.upsert_application(_record(source="jobsdb"))
        assert r1.id != r2.id


class TestUpdateStatus:
    async def test_status_updated(self, db: JobDatabase):
        await db.upsert_application(_record())
        await db.update_status("JOB001", "linkedin", ApplicationStatus.applied)
        rec = await db.get_application("JOB001", "linkedin")
        assert rec is not None
        assert rec.status == ApplicationStatus.applied

    async def test_applied_status_sets_applied_at(self, db: JobDatabase):
        await db.upsert_application(_record())
        await db.update_status("JOB001", "linkedin", ApplicationStatus.applied)
        rec = await db.get_application("JOB001", "linkedin")
        assert rec is not None
        assert rec.applied_at is not None


class TestListApplications:
    async def test_list_all(self, db: JobDatabase):
        await db.upsert_application(_record(job_id="J1", source="linkedin"))
        await db.upsert_application(_record(job_id="J2", source="jobsdb"))
        records = await db.list_applications()
        assert len(records) == 2

    async def test_list_by_status(self, db: JobDatabase):
        await db.upsert_application(_record(job_id="J1"))
        await db.upsert_application(_record(job_id="J2"))
        await db.update_status("J1", "linkedin", ApplicationStatus.applied)
        applied = await db.list_applications(status=ApplicationStatus.applied)
        assert len(applied) == 1
        assert applied[0].job_id == "J1"

    async def test_limit_respected(self, db: JobDatabase):
        for i in range(10):
            await db.upsert_application(_record(job_id=f"J{i}"))
        records = await db.list_applications(limit=3)
        assert len(records) == 3


class TestStats:
    async def test_stats_empty(self, db: JobDatabase):
        stats = await db.stats()
        assert stats == {}

    async def test_stats_counts(self, db: JobDatabase):
        await db.upsert_application(_record(job_id="J1"))
        await db.upsert_application(_record(job_id="J2"))
        await db.update_status("J1", "linkedin", ApplicationStatus.applied)
        stats = await db.stats()
        assert stats.get("applied", 0) == 1
        # J2 stays as 'matched' (default after upsert without status change)


class TestLogEvent:
    async def test_event_logged(self, db: JobDatabase):
        rec = await db.upsert_application(_record())
        # Should not raise
        await db.log_event(rec.id, "test_event", {"key": "value"})
