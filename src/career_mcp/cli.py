"""Click CLI for CareerMCP."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )
    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "anthropic._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """CareerMCP – AI-powered job search and auto-apply agent."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose)


# ── run ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to user_profile.yaml (defaults to config/user_profile.yaml).",
)
@click.option(
    "--servers",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to mcp_servers.yaml (defaults to config/mcp_servers.yaml).",
)
@click.option(
    "--db",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the SQLite database file.",
)
@click.pass_context
def run(ctx: click.Context, profile: Path | None, servers: Path | None, db: Path | None) -> None:
    """Run the job-search and auto-apply agent."""
    asyncio.run(_run_agent(profile, servers, db, ctx.obj.get("verbose", False)))


async def _run_agent(
    profile_path: Path | None,
    servers_path: Path | None,
    db_path: Path | None,
    verbose: bool,
) -> None:
    from career_mcp.agent import CareerAgent
    from career_mcp.config import load_server_config, load_user_profile
    from career_mcp.database import JobDatabase
    from career_mcp.mcp_client import MCPClientPool

    try:
        profile = load_user_profile(profile_path)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    try:
        srv_cfg = load_server_config(servers_path)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    db = JobDatabase(db_path)
    await db.initialise()

    server_configs = srv_cfg.get("servers", {})
    agent_cfg = srv_cfg.get("agent", {})
    model = agent_cfg.get("model", "claude-opus-4-5")
    max_iter = agent_cfg.get("max_iterations", 30)

    pool = MCPClientPool(server_configs)
    async with pool.connect_all():
        agent = CareerAgent(
            profile=profile,
            db=db,
            pool=pool,
            model=model,
            max_iterations=max_iter,
        )
        console.print("[bold green]CareerMCP agent started…[/bold green]")
        applied = await agent.run()
        console.print(
            f"\n[bold]Done![/bold] Applied to [green]{len(applied)}[/green] job(s) this run."
        )

    await _print_stats(db)


# ── status ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--db",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the SQLite database file.",
)
def status(db: Path | None) -> None:
    """Show a summary of tracked job applications."""
    asyncio.run(_show_status(db))


async def _show_status(db_path: Path | None) -> None:
    from career_mcp.database import JobDatabase
    from career_mcp.models import ApplicationStatus

    db = JobDatabase(db_path)
    await db.initialise()
    stats = await db.stats()

    table = Table(title="Application Status Summary", show_header=True, header_style="bold cyan")
    table.add_column("Status", style="dim")
    table.add_column("Count", justify="right")

    for s in ApplicationStatus:
        count = stats.get(s.value, 0)
        color = "green" if s == ApplicationStatus.applied else "white"
        table.add_row(s.value, f"[{color}]{count}[/{color}]")

    console.print(table)


# ── list ──────────────────────────────────────────────────────────────────────

@cli.command(name="list")
@click.option(
    "--status",
    "status_filter",
    default=None,
    help="Filter by status (e.g. applied, matched, interviewing).",
)
@click.option("--limit", default=20, show_default=True, help="Maximum rows to display.")
@click.option(
    "--db",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path to the SQLite database file.",
)
def list_applications(status_filter: str | None, limit: int, db: Path | None) -> None:
    """List tracked job applications."""
    asyncio.run(_list_applications(status_filter, limit, db))


async def _list_applications(
    status_filter: str | None, limit: int, db_path: Path | None
) -> None:
    from career_mcp.database import JobDatabase
    from career_mcp.models import ApplicationStatus

    db = JobDatabase(db_path)
    await db.initialise()

    status_enum = None
    if status_filter:
        try:
            status_enum = ApplicationStatus(status_filter)
        except ValueError:
            console.print(f"[red]Unknown status '{status_filter}'.[/red]")
            sys.exit(1)

    records = await db.list_applications(status=status_enum, limit=limit)

    table = Table(
        title="Job Applications", show_header=True, header_style="bold cyan", show_lines=True
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Source")
    table.add_column("Score", justify="right")
    table.add_column("Status")
    table.add_column("Discovered")

    for rec in records:
        table.add_row(
            str(rec.id),
            rec.title,
            rec.company,
            rec.source,
            str(rec.match_score),
            rec.status.value,
            rec.discovered_at.strftime("%Y-%m-%d"),
        )

    console.print(table)


async def _print_stats(db) -> None:  # type: ignore[no-untyped-def]
    stats = await db.stats()
    parts = [f"{k}: {v}" for k, v in sorted(stats.items())]
    console.print("  Stats → " + " | ".join(parts) if parts else "  No records yet.")
