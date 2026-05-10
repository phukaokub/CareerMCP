"""Tests for career_mcp.matcher."""

import pytest
from career_mcp.matcher import filter_and_rank, score_job
from career_mcp.models import JobListing, UserProfile, WorkMode


def _profile(**overrides) -> UserProfile:
    defaults = dict(
        full_name="Alice",
        email="alice@example.com",
        technical_skills=["Python", "React", "Docker"],
        soft_skills=["Communication"],
        preferred_job_titles=["Senior Software Engineer"],
        work_modes=[WorkMode.remote, WorkMode.hybrid],
        preferred_locations=["Bangkok", "Remote"],
        salary_currency="THB",
        salary_min=80_000,
        salary_max=200_000,
        preferred_industries=["Technology"],
        blacklisted_companies=[],
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _job(**overrides) -> JobListing:
    defaults = dict(
        id="J1",
        source="linkedin",
        title="Senior Software Engineer",
        company="Acme Tech",
        location="Bangkok",
        work_mode=WorkMode.hybrid,
        salary_min=100_000,
        salary_max=180_000,
        salary_currency="THB",
        description="We need a Python and React developer. Technology company.",
        requirements=["Python", "React", "Docker"],
        url="https://linkedin.com/jobs/J1",
    )
    defaults.update(overrides)
    return JobListing(**defaults)


class TestScoreJob:
    def test_high_score_for_matching_job(self):
        result = score_job(_job(), _profile())
        assert result.score >= 70, f"Expected ≥70, got {result.score}"
        assert "Python" in result.matched_skills

    def test_blacklisted_company_returns_zero(self):
        p = _profile(blacklisted_companies=["Acme Tech"])
        result = score_job(_job(company="Acme Tech"), p)
        assert result.score == 0
        assert len(result.disqualifiers) > 0

    def test_blacklist_case_insensitive(self):
        p = _profile(blacklisted_companies=["acme tech"])
        result = score_job(_job(company="Acme Tech"), p)
        assert result.score == 0

    def test_missing_skills_recorded(self):
        p = _profile(technical_skills=["Python", "Rust", "Go"])
        j = _job(description="Python developer wanted.", requirements=["Python"])
        result = score_job(j, p)
        assert "Rust" in result.missing_skills or "Go" in result.missing_skills

    def test_title_mismatch_reduces_score(self):
        j = _job(title="Junior Marketing Analyst")
        result = score_job(j, _profile())
        # Title weight (20) should not be gained
        full_match = score_job(_job(), _profile())
        assert result.score < full_match.score

    def test_salary_below_minimum_reduces_score(self):
        j = _job(salary_min=30_000, salary_max=50_000)
        p = _profile(salary_min=80_000)
        result_low = score_job(j, p)
        result_ok = score_job(_job(salary_min=90_000), p)
        assert result_low.score < result_ok.score

    def test_no_salary_gives_partial_credit(self):
        j = _job(salary_min=None, salary_max=None)
        result = score_job(j, _profile(salary_min=None))
        # Should not be penalised to zero for missing salary
        assert result.score > 0

    def test_location_match_adds_score(self):
        j_match = _job(location="Bangkok, Thailand")
        j_no = _job(location="Tokyo, Japan")
        p = _profile(preferred_locations=["Bangkok"])
        r_match = score_job(j_match, p)
        r_no = score_job(j_no, p)
        assert r_match.score >= r_no.score

    def test_score_capped_at_100(self):
        result = score_job(_job(), _profile())
        assert result.score <= 100


class TestFilterAndRank:
    def test_returns_sorted_descending(self):
        jobs = [
            _job(id="J1", title="Senior Software Engineer", salary_min=100_000),
            _job(id="J2", title="Junior Receptionist", description="no tech", requirements=[]),
        ]
        results = filter_and_rank(jobs, _profile())
        if len(results) >= 2:
            assert results[0].score >= results[1].score

    def test_min_score_filters_out_low(self):
        jobs = [
            _job(id="J1", title="Senior Software Engineer", salary_min=100_000),
            _job(
                id="J2",
                title="Junior Receptionist",
                description="no tech overlap",
                requirements=[],
                salary_min=20_000,
            ),
        ]
        results = filter_and_rank(jobs, _profile(), min_score=60)
        for r in results:
            assert r.score >= 60

    def test_blacklisted_company_excluded(self):
        p = _profile(blacklisted_companies=["Acme Tech"])
        jobs = [_job(id="J1", company="Acme Tech")]
        results = filter_and_rank(jobs, p, min_score=0)
        assert all(r.job.company != "Acme Tech" for r in results)

    def test_empty_job_list(self):
        results = filter_and_rank([], _profile())
        assert results == []
