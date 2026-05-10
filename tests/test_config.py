"""Tests for career_mcp.config."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from career_mcp.config import load_server_config, load_user_profile
from career_mcp.models import EmploymentType, WorkMode


def _write_profile(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "user_profile.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def _write_servers(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "mcp_servers.yaml"
    p.write_text(textwrap.dedent(content))
    return p


class TestLoadUserProfile:
    def test_loads_full_profile(self, tmp_path: Path):
        path = _write_profile(
            tmp_path,
            """
            personal:
              full_name: Alice Smith
              email: alice@example.com
              phone: "+66-81-234-5678"
              location: Bangkok
              linkedin_url: https://linkedin.com/in/alice
            skills:
              technical:
                - Python
                - React
              soft:
                - Communication
            experience_summary: "5 years Python dev."
            career_goal: "Senior engineer role."
            preferences:
              job_titles:
                - Senior Software Engineer
              employment_type:
                - full_time
              work_mode:
                - remote
                - hybrid
              locations:
                - Bangkok
              salary:
                currency: THB
                min: 80000
                max: 200000
              industries:
                - Technology
              company_size:
                - large
              blacklisted_companies: []
            auto_apply:
              enabled: true
              min_match_score: 75
              max_applications_per_run: 5
              cover_letter_template: "Dear {company},"
            """,
        )
        profile = load_user_profile(path)
        assert profile.full_name == "Alice Smith"
        assert "Python" in profile.technical_skills
        assert WorkMode.remote in profile.work_modes
        assert EmploymentType.full_time in profile.employment_types
        assert profile.salary_min == 80_000
        assert profile.auto_apply_min_score == 75

    def test_raises_when_file_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_user_profile(tmp_path / "nonexistent.yaml")

    def test_ignores_unknown_enum_values(self, tmp_path: Path):
        path = _write_profile(
            tmp_path,
            """
            personal:
              full_name: Bob
              email: bob@example.com
            preferences:
              work_mode:
                - unknown_mode
            """,
        )
        profile = load_user_profile(path)
        assert profile.work_modes == []


class TestLoadServerConfig:
    def test_loads_servers(self, tmp_path: Path):
        path = _write_servers(
            tmp_path,
            """
            servers:
              linkedin:
                transport: stdio
                command: npx
                args: ["-y", "linkedin-mcp"]
                env:
                  LINKEDIN_EMAIL: ""
              jobsdb:
                transport: sse
                url: http://localhost:3002/sse
                env: {}
            agent:
              model: claude-opus-4-5
              max_iterations: 20
            """,
        )
        cfg = load_server_config(path)
        assert "linkedin" in cfg["servers"]
        assert cfg["servers"]["linkedin"]["command"] == "npx"
        assert cfg["agent"]["model"] == "claude-opus-4-5"

    def test_raises_when_file_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_server_config(tmp_path / "nonexistent.yaml")

    def test_env_override_from_environment(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LINKEDIN_EMAIL", "test@example.com")
        path = _write_servers(
            tmp_path,
            """
            servers:
              linkedin:
                transport: stdio
                command: npx
                args: []
                env:
                  LINKEDIN_EMAIL: ""
            """,
        )
        cfg = load_server_config(path)
        assert cfg["servers"]["linkedin"]["env"]["LINKEDIN_EMAIL"] == "test@example.com"
