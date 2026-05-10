"""Job-matching / scoring engine.

Scores a JobListing against a UserProfile using keyword overlap,
salary range comparison, work-mode preferences, and location matching.
The result is a MatchResult with a score between 0 and 100.
"""

from __future__ import annotations

import re

from career_mcp.models import JobListing, MatchResult, UserProfile

# Weight contributions must sum to 100
_WEIGHTS = {
    "skills": 40,
    "title": 20,
    "location_mode": 15,
    "salary": 15,
    "industry": 10,
}


def score_job(job: JobListing, profile: UserProfile) -> MatchResult:
    """Score *job* against *profile* and return a MatchResult."""
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    reasons: list[str] = []
    disqualifiers: list[str] = []

    # ── Blacklist check ───────────────────────────────────────────────────────
    if _normalise(job.company) in {_normalise(c) for c in profile.blacklisted_companies}:
        disqualifiers.append(f"'{job.company}' is blacklisted.")
        return MatchResult(
            job=job,
            score=0,
            disqualifiers=disqualifiers,
        )

    # ── Skills score (40 pts) ─────────────────────────────────────────────────
    job_text = _job_text(job)
    profile_skills_lower = {s.lower() for s in profile.all_skills}
    for skill in profile.all_skills:
        if skill.lower() in job_text:
            matched_skills.append(skill)
        else:
            missing_skills.append(skill)

    if profile_skills_lower:
        skill_ratio = len(matched_skills) / len(profile_skills_lower)
    else:
        skill_ratio = 0.5  # no skills configured → neutral

    skills_score = round(skill_ratio * _WEIGHTS["skills"])
    if matched_skills:
        reasons.append(f"Matched skills: {', '.join(matched_skills[:5])}")

    # ── Title score (20 pts) ──────────────────────────────────────────────────
    title_score = 0
    job_title_lower = job.title.lower()
    for preferred in profile.preferred_job_titles:
        if _partial_match(preferred.lower(), job_title_lower):
            title_score = _WEIGHTS["title"]
            reasons.append(f"Title matches preferred '{preferred}'")
            break

    # ── Location / work-mode score (15 pts) ───────────────────────────────────
    loc_score = 0
    if job.work_mode and job.work_mode in profile.work_modes:
        loc_score += _WEIGHTS["location_mode"] // 2
        reasons.append(f"Work mode '{job.work_mode.value}' matches preference")
    for loc in profile.preferred_locations:
        if loc.lower() in job.location.lower():
            loc_score = _WEIGHTS["location_mode"]
            reasons.append(f"Location '{job.location}' matches preference")
            break

    # ── Salary score (15 pts) ─────────────────────────────────────────────────
    salary_score = 0
    if job.salary_min is not None and profile.salary_min is not None:
        if job.salary_min >= profile.salary_min:
            salary_score = _WEIGHTS["salary"]
            reasons.append(
                f"Salary {job.salary_currency} {job.salary_min:,}–{job.salary_max:,} "
                f"meets minimum requirement"
            )
        else:
            pct = job.salary_min / profile.salary_min
            salary_score = round(pct * _WEIGHTS["salary"])
    else:
        # Salary not disclosed → partial credit
        salary_score = _WEIGHTS["salary"] // 2

    # ── Industry score (10 pts) ───────────────────────────────────────────────
    industry_score = 0
    if profile.preferred_industries:
        job_text_full = job_text + " " + job.company.lower()
        for ind in profile.preferred_industries:
            if ind.lower() in job_text_full:
                industry_score = _WEIGHTS["industry"]
                reasons.append(f"Industry '{ind}' detected in listing")
                break
        # neutral half-credit if no industry info in listing
        if industry_score == 0:
            industry_score = _WEIGHTS["industry"] // 2
    else:
        industry_score = _WEIGHTS["industry"]

    total = skills_score + title_score + loc_score + salary_score + industry_score

    return MatchResult(
        job=job,
        score=min(total, 100),
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        match_reasons="\n".join(reasons) if reasons else "No strong matches found.",
        disqualifiers=disqualifiers,
    )


def filter_and_rank(
    jobs: list[JobListing],
    profile: UserProfile,
    min_score: int = 0,
) -> list[MatchResult]:
    """Score all jobs, filter by *min_score*, and sort descending."""
    results = [score_job(j, profile) for j in jobs]
    filtered = [r for r in results if r.score >= min_score and not r.disqualifiers]
    return sorted(filtered, key=lambda r: r.score, reverse=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    return text.strip().lower()


def _job_text(job: JobListing) -> str:
    parts = [
        job.title,
        job.description,
        job.company,
        " ".join(job.requirements),
    ]
    return " ".join(parts).lower()


def _partial_match(pattern: str, text: str) -> bool:
    """True when all words in *pattern* appear in *text*."""
    words = re.split(r"\W+", pattern)
    return all(w in text for w in words if w)
