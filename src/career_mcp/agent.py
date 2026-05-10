"""AI agent orchestrator.

Uses the Anthropic Claude API in an agentic loop to:
  1. Search LinkedIn and JobsDB for open positions.
  2. Score / match results against the user profile.
  3. Auto-apply to qualifying jobs.
  4. Persist all records in the SQLite database.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from career_mcp.auto_apply import AutoApplyEngine
from career_mcp.database import JobDatabase
from career_mcp.matcher import filter_and_rank
from career_mcp.mcp_client import MCPClientPool
from career_mcp.models import (
    ApplicationRecord,
    EmploymentType,
    JobListing,
    MatchResult,
    UserProfile,
    WorkMode,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are CareerMCP, an AI job-search agent.

Your mission:
1. Use the available MCP tools to search LinkedIn and JobsDB for open positions
   that match the user's profile below.
2. Retrieve full job descriptions for the most promising listings.
3. Call the `record_jobs` function with a JSON list of JobListing objects so the
   system can score and persist them.
4. If auto-apply is enabled, the system will apply automatically after scoring.

Always search both LinkedIn and JobsDB. Prefer quality over quantity — aim for
listings that closely match the user's preferred titles, skills, and locations.

USER PROFILE
============
{profile_summary}
"""


class CareerAgent:
    """Orchestrates the end-to-end job-search and application workflow."""

    def __init__(
        self,
        profile: UserProfile,
        db: JobDatabase,
        pool: MCPClientPool,
        anthropic_client: anthropic.AsyncAnthropic | None = None,
        model: str = "claude-opus-4-5",
        max_iterations: int = 30,
    ) -> None:
        self._profile = profile
        self._db = db
        self._pool = pool
        self._client = anthropic_client or anthropic.AsyncAnthropic()
        self._model = model
        self._max_iterations = max_iterations
        self._apply_engine = AutoApplyEngine(profile, db)

    async def run(self) -> list[ApplicationRecord]:
        """Run the full agent loop and return applied records."""
        logger.info("CareerAgent starting (model=%s)", self._model)

        # Combine MCP tools + internal record_jobs tool
        tools = self._build_tools()
        messages: list[dict] = [
            {"role": "user", "content": "Find and apply to jobs matching my profile."}
        ]

        collected_jobs: list[JobListing] = []
        applied_records: list[ApplicationRecord] = []

        for iteration in range(self._max_iterations):
            logger.debug("Agent iteration %d/%d", iteration + 1, self._max_iterations)

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=_SYSTEM_PROMPT.format(
                    profile_summary=_format_profile(self._profile)
                ),
                tools=tools,
                messages=messages,
            )

            # Append assistant response to history
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                logger.info("Agent finished (end_turn).")
                break

            if response.stop_reason != "tool_use":
                logger.warning("Unexpected stop_reason: %s", response.stop_reason)
                break

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name: str = block.name
                tool_input: dict = block.input

                logger.info("Tool call: %s(%s)", tool_name, _truncate(tool_input))

                try:
                    if tool_name == "record_jobs":
                        jobs = _parse_job_listings(tool_input.get("jobs", []))
                        collected_jobs.extend(jobs)
                        matches = filter_and_rank(jobs, self._profile)
                        # Persist discovered matches
                        for m in matches:
                            await self._db.upsert_application(
                                _match_to_record(m)
                            )
                        result_content = json.dumps(
                            {
                                "recorded": len(jobs),
                                "matches": [
                                    {"title": m.job.title, "company": m.job.company, "score": m.score}
                                    for m in matches
                                ],
                            }
                        )
                    else:
                        raw = await self._pool.call_tool(tool_name, tool_input)
                        result_content = _serialise(raw)
                except Exception as exc:
                    logger.warning("Tool '%s' error: %s", tool_name, exc)
                    result_content = json.dumps({"error": str(exc)})

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_content,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        # Auto-apply phase
        if collected_jobs:
            all_matches: list[MatchResult] = filter_and_rank(collected_jobs, self._profile)
            logger.info(
                "Scored %d jobs. Top score: %d",
                len(all_matches),
                all_matches[0].score if all_matches else 0,
            )
            applied_records = await self._apply_engine.process_matches(
                all_matches, self._pool.call_tool
            )
            logger.info("Applied to %d job(s) this run.", len(applied_records))

        return applied_records

    def _build_tools(self) -> list[dict]:
        """Combine MCP server tools with the internal record_jobs tool."""
        mcp_tools = self._pool.all_tools()
        return mcp_tools + [_RECORD_JOBS_TOOL]


# ── Internal helpers ──────────────────────────────────────────────────────────

_RECORD_JOBS_TOOL: dict = {
    "name": "record_jobs",
    "description": (
        "Record job listings retrieved from MCP servers. "
        "Call this after fetching job details to persist and score them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "jobs": {
                "type": "array",
                "description": "List of job listing objects.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "source": {"type": "string", "enum": ["linkedin", "jobsdb"]},
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "location": {"type": "string"},
                        "work_mode": {
                            "type": "string",
                            "enum": ["remote", "hybrid", "on_site"],
                        },
                        "employment_type": {
                            "type": "string",
                            "enum": ["full_time", "part_time", "contract", "freelance", "internship"],
                        },
                        "salary_min": {"type": "integer"},
                        "salary_max": {"type": "integer"},
                        "salary_currency": {"type": "string"},
                        "description": {"type": "string"},
                        "requirements": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "url": {"type": "string"},
                    },
                    "required": ["id", "source", "title", "company", "location"],
                },
            }
        },
        "required": ["jobs"],
    },
}


def _format_profile(p: UserProfile) -> str:
    lines = [
        f"Name: {p.full_name}",
        f"Location: {p.location}",
        f"Technical skills: {', '.join(p.technical_skills)}",
        f"Preferred titles: {', '.join(p.preferred_job_titles)}",
        f"Work modes: {', '.join(m.value for m in p.work_modes)}",
        f"Preferred locations: {', '.join(p.preferred_locations)}",
        f"Salary ({p.salary_currency}): {p.salary_min}–{p.salary_max}",
        "",
        "Experience summary:",
        p.experience_summary.strip(),
        "",
        "Career goal:",
        p.career_goal.strip(),
    ]
    return "\n".join(lines)


def _parse_job_listings(raw_jobs: list[dict]) -> list[JobListing]:
    listings = []
    for raw in raw_jobs:
        try:
            wm_raw = raw.get("work_mode")
            et_raw = raw.get("employment_type")
            listings.append(
                JobListing(
                    id=str(raw.get("id", "")),
                    source=str(raw.get("source", "unknown")),
                    title=str(raw.get("title", "")),
                    company=str(raw.get("company", "")),
                    location=str(raw.get("location", "")),
                    work_mode=WorkMode(wm_raw) if wm_raw else None,
                    employment_type=EmploymentType(et_raw) if et_raw else None,
                    salary_min=raw.get("salary_min"),
                    salary_max=raw.get("salary_max"),
                    salary_currency=raw.get("salary_currency"),
                    description=str(raw.get("description", "")),
                    requirements=raw.get("requirements", []),
                    url=str(raw.get("url", "")),
                    raw=raw,
                )
            )
        except Exception as exc:
            logger.warning("Could not parse job listing %s: %s", raw, exc)
    return listings


def _match_to_record(m: MatchResult):
    from career_mcp.models import ApplicationStatus, ApplicationRecord

    return ApplicationRecord(
        job_id=m.job.id,
        source=m.job.source,
        title=m.job.title,
        company=m.job.company,
        location=m.job.location,
        url=m.job.url,
        match_score=m.score,
        status=ApplicationStatus.matched,
    )


def _serialise(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


def _truncate(d: dict, max_len: int = 200) -> str:
    s = json.dumps(d, default=str)
    return s[:max_len] + "…" if len(s) > max_len else s
