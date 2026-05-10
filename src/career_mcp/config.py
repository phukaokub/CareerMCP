"""Configuration loader for CareerMCP."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from career_mcp.models import EmploymentType, UserProfile, WorkMode

load_dotenv()

_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def _config_dir() -> Path:
    return Path(os.environ.get("CAREER_MCP_CONFIG_DIR", _DEFAULT_CONFIG_DIR))


def load_user_profile(path: Path | None = None) -> UserProfile:
    """Load and validate the user profile YAML file.

    Args:
        path: Explicit path to user_profile.yaml.  Falls back to the
              ``config/user_profile.yaml`` inside the project root.

    Raises:
        FileNotFoundError: When the profile file does not exist.
        ValueError: When required fields are missing.
    """
    if path is None:
        path = _config_dir() / "user_profile.yaml"

    if not path.exists():
        example = path.with_suffix(".yaml.example")
        raise FileNotFoundError(
            f"User profile not found at {path}.\n"
            f"Copy the example file and fill it in:\n"
            f"  cp {example} {path}"
        )

    raw: dict = yaml.safe_load(path.read_text(encoding="utf-8"))

    personal = raw.get("personal", {})
    skills = raw.get("skills", {})
    prefs = raw.get("preferences", {})
    apply_cfg = raw.get("auto_apply", {})

    salary = prefs.get("salary", {})

    def _parse_enum_list(values: list[str], enum_cls):
        result = []
        for v in values:
            try:
                result.append(enum_cls(v))
            except ValueError:
                pass  # ignore unknown values
        return result

    return UserProfile(
        full_name=personal.get("full_name", ""),
        email=personal.get("email", ""),
        phone=personal.get("phone", ""),
        location=personal.get("location", ""),
        linkedin_url=personal.get("linkedin_url", ""),
        portfolio_url=personal.get("portfolio_url", ""),
        technical_skills=skills.get("technical", []),
        soft_skills=skills.get("soft", []),
        experience_summary=raw.get("experience_summary", ""),
        career_goal=raw.get("career_goal", ""),
        preferred_job_titles=prefs.get("job_titles", []),
        employment_types=_parse_enum_list(prefs.get("employment_type", []), EmploymentType),
        work_modes=_parse_enum_list(prefs.get("work_mode", []), WorkMode),
        preferred_locations=prefs.get("locations", []),
        salary_currency=salary.get("currency", "THB"),
        salary_min=salary.get("min"),
        salary_max=salary.get("max"),
        preferred_industries=prefs.get("industries", []),
        preferred_company_sizes=prefs.get("company_size", []),
        blacklisted_companies=prefs.get("blacklisted_companies", []),
        auto_apply_enabled=apply_cfg.get("enabled", True),
        auto_apply_min_score=apply_cfg.get("min_match_score", 70),
        auto_apply_max_per_run=apply_cfg.get("max_applications_per_run", 10),
        cover_letter_template=apply_cfg.get("cover_letter_template", ""),
    )


def load_server_config(path: Path | None = None) -> dict:
    """Load mcp_servers.yaml and overlay environment-variable secrets."""
    if path is None:
        path = _config_dir() / "mcp_servers.yaml"

    if not path.exists():
        example = path.with_suffix(".yaml.example")
        raise FileNotFoundError(
            f"MCP server config not found at {path}.\n"
            f"Copy the example file and fill it in:\n"
            f"  cp {example} {path}"
        )

    cfg: dict = yaml.safe_load(path.read_text(encoding="utf-8"))

    # Override server env vars from process environment (via .env)
    for _name, server in cfg.get("servers", {}).items():
        env_block: dict = server.get("env", {})
        for key in list(env_block.keys()):
            env_val = os.environ.get(key)
            if env_val:
                env_block[key] = env_val

    return cfg
