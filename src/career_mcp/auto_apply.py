"""Auto-apply logic.

Given a list of MatchResults, generates cover letters and
submits applications through the relevant MCP server tools.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from career_mcp.database import JobDatabase
from career_mcp.models import ApplicationRecord, ApplicationStatus, MatchResult, UserProfile

_UTC = timezone.utc

logger = logging.getLogger(__name__)


class AutoApplyEngine:
    """Generates cover letters and submits job applications."""

    def __init__(self, profile: UserProfile, db: JobDatabase) -> None:
        self._profile = profile
        self._db = db

    def build_cover_letter(self, match: MatchResult) -> str:
        """Render the cover letter template with job- and profile-specific values."""
        template = self._profile.cover_letter_template or _DEFAULT_TEMPLATE
        return template.format(
            full_name=self._profile.full_name,
            job_title=match.job.title,
            company=match.job.company,
            match_reasons=match.match_reasons,
            career_goal=self._profile.career_goal.strip(),
        )

    async def apply(
        self,
        match: MatchResult,
        tool_caller: Any,  # async callable(tool_name, args) -> result
    ) -> ApplicationRecord:
        """Submit an application for *match* and persist the record.

        Args:
            match: Scored job match.
            tool_caller: An async callable that executes MCP tools on behalf of the caller.
                         Signature: ``async (tool_name: str, args: dict) -> Any``

        Returns:
            The persisted ApplicationRecord (status = applied on success,
            discovered on failure).
        """
        job = match.job
        cover_letter = self.build_cover_letter(match)

        # Persist as "matched" first so we have a DB row even if apply fails
        record = ApplicationRecord(
            job_id=job.id,
            source=job.source,
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            match_score=match.score,
            status=ApplicationStatus.matched,
            cover_letter=cover_letter,
        )
        record = await self._db.upsert_application(record)

        # Determine which MCP tool to call
        apply_tool = f"{job.source}__apply_job"

        try:
            logger.info("Applying to '%s' at '%s' via %s …", job.title, job.company, apply_tool)
            await tool_caller(
                apply_tool,
                {
                    "job_id": job.id,
                    "job_url": job.url,
                    "cover_letter": cover_letter,
                    "resume_text": self._profile.experience_summary,
                },
            )
            # Update status to applied
            record.status = ApplicationStatus.applied
            record.applied_at = datetime.now(_UTC)
            await self._db.update_status(job.id, job.source, ApplicationStatus.applied)
            if record.id:
                await self._db.log_event(
                    record.id,
                    "applied",
                    {"tool": apply_tool, "score": match.score},
                )
            logger.info(
                "✔ Applied to '%s' at '%s' (score=%d)", job.title, job.company, match.score
            )
        except Exception as exc:
            logger.warning(
                "✘ Failed to apply to '%s' at '%s': %s", job.title, job.company, exc
            )
            record.status = ApplicationStatus.discovered
            await self._db.update_status(
                job.id, job.source, ApplicationStatus.discovered, notes=str(exc)
            )
            if record.id:
                await self._db.log_event(
                    record.id,
                    "apply_failed",
                    {"error": str(exc)},
                )

        return record

    async def process_matches(
        self,
        matches: list[MatchResult],
        tool_caller: Any,
    ) -> list[ApplicationRecord]:
        """Apply to all *matches* respecting the profile's per-run limit.

        Skips matches below the minimum score and jobs already applied to.
        Returns the list of ApplicationRecords for this run.
        """
        if not self._profile.auto_apply_enabled:
            logger.info("Auto-apply is disabled in the user profile.")
            return []

        applied: list[ApplicationRecord] = []
        for match in matches:
            if len(applied) >= self._profile.auto_apply_max_per_run:
                logger.info(
                    "Reached max applications per run (%d). Stopping.",
                    self._profile.auto_apply_max_per_run,
                )
                break

            if match.score < self._profile.auto_apply_min_score:
                logger.debug(
                    "Skipping '%s' (score=%d < min=%d)",
                    match.job.title,
                    match.score,
                    self._profile.auto_apply_min_score,
                )
                continue

            # Skip if already applied
            existing = await self._db.get_application(match.job.id, match.job.source)
            if existing and existing.status == ApplicationStatus.applied:
                logger.debug(
                    "Already applied to '%s' at '%s'. Skipping.", match.job.title, match.job.company
                )
                continue

            record = await self.apply(match, tool_caller)
            if record.status == ApplicationStatus.applied:
                applied.append(record)

        return applied


_DEFAULT_TEMPLATE = """\
Dear Hiring Team at {company},

I am excited to apply for the {job_title} position.

{match_reasons}

{career_goal}

Thank you for considering my application.

Best regards,
{full_name}
"""
