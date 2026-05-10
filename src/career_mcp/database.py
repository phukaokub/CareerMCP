"""SQLite-backed job-tracking database using aiosqlite."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from career_mcp.models import ApplicationRecord, ApplicationStatus

_UTC = timezone.utc

_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "career_agent.db"

_CREATE_APPLICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    company       TEXT    NOT NULL,
    location      TEXT    NOT NULL DEFAULT '',
    url           TEXT    NOT NULL DEFAULT '',
    match_score   INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'discovered',
    cover_letter  TEXT    NOT NULL DEFAULT '',
    notes         TEXT    NOT NULL DEFAULT '',
    discovered_at TEXT    NOT NULL,
    applied_at    TEXT,
    updated_at    TEXT    NOT NULL,
    UNIQUE(job_id, source)
)
"""

_CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id),
    event_type     TEXT    NOT NULL,
    payload        TEXT    NOT NULL DEFAULT '{}',
    created_at     TEXT    NOT NULL
)
"""


class JobDatabase:
    """Async SQLite wrapper for job-application tracking."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def initialise(self) -> None:
        """Create tables if they don't exist."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(_CREATE_APPLICATIONS_TABLE)
            await db.execute(_CREATE_EVENTS_TABLE)
            await db.commit()

    # ── Application CRUD ─────────────────────────────────────────────────────

    async def upsert_application(self, record: ApplicationRecord) -> ApplicationRecord:
        """Insert or update an application record; returns the saved record."""
        now = datetime.now(_UTC).isoformat()
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                INSERT INTO applications
                    (job_id, source, title, company, location, url, match_score,
                     status, cover_letter, notes, discovered_at, applied_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, source) DO UPDATE SET
                    title        = excluded.title,
                    company      = excluded.company,
                    location     = excluded.location,
                    url          = excluded.url,
                    match_score  = excluded.match_score,
                    status       = excluded.status,
                    cover_letter = excluded.cover_letter,
                    notes        = excluded.notes,
                    applied_at   = excluded.applied_at,
                    updated_at   = excluded.updated_at
                RETURNING id
                """,
                (
                    record.job_id,
                    record.source,
                    record.title,
                    record.company,
                    record.location,
                    record.url,
                    record.match_score,
                    record.status.value,
                    record.cover_letter,
                    record.notes,
                    record.discovered_at.isoformat(),
                    record.applied_at.isoformat() if record.applied_at else None,
                    now,
                ),
            )
            row = await cursor.fetchone()
            await db.commit()
        record.id = row["id"]
        record.updated_at = datetime.fromisoformat(now)
        return record

    async def update_status(
        self,
        job_id: str,
        source: str,
        status: ApplicationStatus,
        notes: str = "",
    ) -> None:
        """Update the status of an existing application."""
        now = datetime.now(_UTC).isoformat()
        applied_at_set = ""
        params: list = [status.value, now]

        if status == ApplicationStatus.applied:
            applied_at_set = ", applied_at = ?"
            params.append(now)

        if notes:
            params.extend([notes, job_id, source])
            sql = (
                f"UPDATE applications SET status = ?, updated_at = ?{applied_at_set},"
                f" notes = ? WHERE job_id = ? AND source = ?"
            )
        else:
            params.extend([job_id, source])
            sql = (
                f"UPDATE applications SET status = ?, updated_at = ?{applied_at_set}"
                f" WHERE job_id = ? AND source = ?"
            )

        async with aiosqlite.connect(self._path) as db:
            await db.execute(sql, params)
            await db.commit()

    async def log_event(
        self,
        application_id: int,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        """Append an event to the events table for audit purposes."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO events (application_id, event_type, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    application_id,
                    event_type,
                    json.dumps(payload or {}),
                    datetime.now(_UTC).isoformat(),
                ),
            )
            await db.commit()

    async def get_application(
        self, job_id: str, source: str
    ) -> Optional[ApplicationRecord]:
        """Fetch a single application by job_id + source."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM applications WHERE job_id = ? AND source = ?",
                (job_id, source),
            )
            row = await cursor.fetchone()
        return _row_to_record(row) if row else None

    async def list_applications(
        self,
        status: Optional[ApplicationStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApplicationRecord]:
        """List applications, optionally filtered by status."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cursor = await db.execute(
                    "SELECT * FROM applications WHERE status = ? "
                    "ORDER BY discovered_at DESC LIMIT ? OFFSET ?",
                    (status.value, limit, offset),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM applications ORDER BY discovered_at DESC "
                    "LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            rows = await cursor.fetchall()
        return [_row_to_record(r) for r in rows]

    async def stats(self) -> dict:
        """Return aggregate statistics about tracked applications."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
            )
            rows = await cursor.fetchall()
        return {r["status"]: r["cnt"] for r in rows}


def _row_to_record(row: aiosqlite.Row) -> ApplicationRecord:
    return ApplicationRecord(
        id=row["id"],
        job_id=row["job_id"],
        source=row["source"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        url=row["url"],
        match_score=row["match_score"],
        status=ApplicationStatus(row["status"]),
        cover_letter=row["cover_letter"],
        notes=row["notes"],
        discovered_at=datetime.fromisoformat(row["discovered_at"]),
        applied_at=(
            datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None
        ),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
