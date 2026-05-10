# CareerMCP

> **AI-powered job-search and auto-apply agent** — connects to LinkedIn and JobsDB via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io), scores open positions against your saved profile, and applies automatically.

---

## Overview

CareerMCP spawns an AI agent (powered by Anthropic Claude) that:

1. **Searches** LinkedIn and JobsDB through MCP tool calls.
2. **Matches & scores** every listing against your saved skills, preferences, and career goal (0–100 score).
3. **Auto-applies** to the best matches — generating a personalised cover letter for each — up to your configured daily limit.
4. **Tracks** every discovered and applied position in a local SQLite database with full audit history.

```
┌─────────────────────────────────────────────────────────────┐
│                        CareerMCP CLI                        │
│  career-mcp run | career-mcp status | career-mcp list       │
└───────────────────────┬─────────────────────────────────────┘
                        │
            ┌───────────▼───────────┐
            │      CareerAgent      │   ← Claude AI (agentic loop)
            │   (src/career_mcp/    │
            │      agent.py)        │
            └──┬──────────┬─────────┘
               │          │
    ┌──────────▼──┐   ┌───▼──────────┐
    │ LinkedIn MCP│   │ JobsDB MCP   │   ← External MCP servers
    └─────────────┘   └──────────────┘
               │          │
    ┌──────────▼──────────▼──────────┐
    │     Matcher  │  AutoApply      │   ← Local scoring & apply logic
    │     (matcher.py)  (auto_apply) │
    └──────────────┬─────────────────┘
                   │
         ┌─────────▼─────────┐
         │  SQLite Database  │   ← career_agent.db
         └───────────────────┘
```

---

## Quick Start

### 1. Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| Node.js | ≥ 18 (for MCP servers via `npx`) |
| Anthropic API key | [Get one here](https://console.anthropic.com) |

### 2. Install

```bash
git clone https://github.com/phukaokub/CareerMCP.git
cd CareerMCP
pip install -e .
```

### 3. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

### 4. Configure MCP servers

```bash
cp config/mcp_servers.yaml.example config/mcp_servers.yaml
# Edit config/mcp_servers.yaml if you need custom server paths or SSE URLs
```

### 5. Create your user profile

```bash
cp config/user_profile.yaml.example config/user_profile.yaml
# Edit config/user_profile.yaml — add your skills, preferences, and career goal
```

### 6. Run the agent

```bash
career-mcp run
```

---

## CLI Reference

```
career-mcp [OPTIONS] COMMAND [ARGS]

Options:
  -v, --verbose   Enable debug logging.

Commands:
  run     Run the job-search and auto-apply agent.
  status  Show a summary of tracked job applications.
  list    List tracked job applications (filterable by status).
```

### `run`

```bash
career-mcp run [--profile PATH] [--servers PATH] [--db PATH]
```

Starts the agent. It will search LinkedIn and JobsDB, score results, and
auto-apply to qualifying positions.

### `status`

```bash
career-mcp status [--db PATH]
```

Prints an aggregated table of all tracked applications grouped by status.

### `list`

```bash
career-mcp list [--status applied] [--limit 50] [--db PATH]
```

Shows a detailed table of applications. Filter by any `ApplicationStatus`
value: `discovered`, `matched`, `applied`, `rejected`, `interviewing`,
`offered`, `accepted`, `declined`.

---

## Configuration Files

### `config/user_profile.yaml`

The central file that drives every decision the agent makes.

| Section | Purpose |
|---|---|
| `personal` | Name, email, LinkedIn URL, etc. |
| `skills.technical` | Technical skills list (used for keyword matching) |
| `skills.soft` | Soft skills (also matched) |
| `experience_summary` | 2–4 sentence background used in cover letters |
| `career_goal` | What you want in your next role — guides ranking and cover letters |
| `preferences` | Titles, employment type, work mode, location, salary, industry |
| `auto_apply` | Enable/disable, min score threshold, max per run, cover letter template |

### `config/mcp_servers.yaml`

Defines how the agent connects to LinkedIn and JobsDB MCP servers.
Supports both `stdio` (local process) and `sse` (remote HTTP) transports.

Environment variables set in `.env` automatically override the `env:` keys
inside each server block, so secrets never need to be hardcoded in YAML.

### `.env`

Holds API keys and credentials. **Never commit this file.**

---

## Scoring Algorithm

Each job is scored from 0–100 using weighted criteria:

| Criterion | Weight |
|---|---|
| Skill keyword overlap | 40 pts |
| Job title match | 20 pts |
| Location / work-mode match | 15 pts |
| Salary range match | 15 pts |
| Industry detection | 10 pts |

Jobs from blacklisted companies are immediately scored 0 and excluded.
Only jobs at or above `auto_apply.min_match_score` are applied to.

---

## Project Structure

```
CareerMCP/
├── config/
│   ├── mcp_servers.yaml.example   # MCP server connection template
│   └── user_profile.yaml.example  # User profile template
├── data/                          # SQLite DB lives here (git-ignored)
├── src/career_mcp/
│   ├── __init__.py
│   ├── agent.py        # AI agent orchestrator (Claude agentic loop)
│   ├── auto_apply.py   # Cover letter generation + application submission
│   ├── cli.py          # Click CLI (run / status / list)
│   ├── config.py       # YAML config loader
│   ├── database.py     # Async SQLite job-tracking database
│   ├── matcher.py      # Job-scoring and ranking engine
│   ├── mcp_client.py   # MCP server connection pool (stdio + SSE)
│   └── models.py       # Pydantic data models
├── tests/
│   ├── test_auto_apply.py
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_matcher.py
│   └── test_models.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── requirements.txt
```

---

## Development

```bash
# Install with dev extras
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/ tests/
```

---

## MCP Server Recommendations

| Platform | MCP Server |
|---|---|
| LinkedIn | [`linkedin-mcp`](https://github.com/alfonsograziano/linkedin-mcp) or any compatible server |
| JobsDB | Custom SSE server exposing `search_jobs` and `apply_job` tools |

Any MCP server that exposes `search_jobs` and `apply_job` tools will work.
The agent namespaces tool calls as `<server_name>__<tool_name>` (e.g.
`linkedin__search_jobs`).

---

## License

MIT © 2026 Teerawat Chuaphanngam
