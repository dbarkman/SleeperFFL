"""Command line interface."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .api import SleeperClient
from .cache import Cache
from .config import Config
from .draft import format_pick, load_draft_state, recommend
from .league import League, load_league
from .notify import Notifier
from .pool import build_pool
from .scoring import score_line
from .value import replacement_levels, vor
from .waivers import (
    WatcherState,
    detect_alerts,
    rank_free_agents,
    update_state,
    waiver_advice,
)

app = typer.Typer(add_completion=False, help="Sleeper draft assistant and waiver watcher.")
console = Console()

POSITION_STYLE = {
    "QB": "bright_magenta",
    "RB": "green",
    "WR": "cyan",
    "TE": "yellow",
    "K": "grey62",
    "DEF": "blue",
}


def _context(league_id: Optional[str], season: Optional[str]) -> tuple[SleeperClient, League, Config]:
    config = Config.from_env()
    client = SleeperClient(Cache(config.cache_dir))
    user = client.user(config.username)
    if not user:
        raise typer.BadParameter(f"Sleeper user '{config.username}' not found.")
    resolved_season = season or config.season or client.state()["league_season"]
    league = load_league(
        client, user["user_id"], str(resolved_season), league_id or config.league_id
    )
    return client, league, config


def _pos(position: str) -> str:
    return f"[{POSITION_STYLE.get(position, 'white')}]{position}[/]"


@app.command()
def league(
    league_id: Optional[str] = typer.Option(None, "--league-id"),
    season: Optional[str] = typer.Option(None, "--season"),
) -> None:
    """Show league settings, managers and roster shape."""
    client, lg, _ = _context(league_id, season)
    with client:
        console.print(
            Panel(
                f"[bold]{lg.name}[/]\n"
                f"{lg.total_rosters} teams · {lg.season} · status [bold]{lg.status}[/]\n"
                f"Starters: {' / '.join(lg.starting_slots)}  (+{lg.bench_size} bench)\n"
                f"Scoring: {lg.scoring.get('rec', 0)} PPR, {lg.scoring.get('pass_td', 0)} pt pass TD\n"
                f"Waivers: {lg.waiver_type}, {lg.waiver_clear_days} day clear\n"
                f"Playoffs start week {lg.settings.get('playoff_week_start', '?')}",
                title="League",
            )
        )

        table = Table(title=f"Managers ({len(lg.managers)}/{lg.total_rosters} joined)")
        table.add_column("Team")
        table.add_column("Manager")
        table.add_column("Roster", justify="right")
        table.add_column("Waiver", justify="right")
        for manager in sorted(lg.managers, key=lambda m: m.roster_id or 99):
            roster = next(
                (r for r in lg.rosters if r.get("roster_id") == manager.roster_id), {}
            )
            position = (roster.get("settings") or {}).get("waiver_position", "-")
            mark = " [dim](you)[/]" if manager.user_id == lg.my_user_id else ""
            commissioner = " [yellow]★[/]" if manager.is_commissioner else ""
            table.add_row(
                f"{manager.label}{mark}{commissioner}",
                manager.display_name,
                str(manager.roster_id or "-"),
                str(position),
            )
        console.print(table)


@app.command()
def board(
    league_id: Optional[str] = typer.Option(None, "--league-id"),
    season: Optional[str] = typer.Option(None, "--season"),
    position: Optional[str] = typer.Option(None, "--position", "-p", help="Filter to one position"),
    limit: int = typer.Option(40, "--limit", "-n"),
) -> None:
    """Static best-available board by value over replacement."""
    client, lg, _ = _context(league_id, season)
    with client:
        pool = build_pool(client, lg.season, lg.scoring, lg.roster_positions)
        levels = replacement_levels(lg, pool)
        rows = [(p, vor(p, levels)) for p in pool.values()]
        if position:
            rows = [r for r in rows if r[0].position == position.upper()]
        rows.sort(key=lambda r: r[1], reverse=True)

        table = Table(title=f"{lg.name} — value board ({lg.scoring.get('rec', 0)} PPR)")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Player")
        table.add_column("Pos", justify="center")
        table.add_column("Tm", justify="center")
        table.add_column("Bye", justify="right")
        table.add_column("ADP", justify="right")
        table.add_column("Proj", justify="right")
        table.add_column("VOR", justify="right")
        for index, (player, value) in enumerate(rows[:limit], start=1):
            table.add_row(
                str(index),
                player.name + (" [red]!" if player.injury_status else ""),
                _pos(player.position),
                player.team or "-",
                str(player.bye_week or "-"),
                f"{player.adp:.1f}" if player.adp else "-",
                f"{player.proj_season:.0f}",
                f"[bold]{value:+.0f}[/]",
            )
        console.print(table)
        console.print(
            "[dim]Replacement level: "
            + "  ".join(f"{pos} {level:.0f}" for pos, level in sorted(levels.items()))
            + "[/]"
        )


def _draft_view(lg: League, pool, state, limit: int) -> Table:
    grid = Table.grid(expand=True)
    grid.add_column()

    if state.my_slot is None:
        grid.add_row(
            Panel(
                "[yellow]Draft slot unknown.[/] The commissioner has not set the draft "
                "order yet. Pass [bold]--slot N[/] to plan from a hypothetical seat.",
                title="Heads up",
            )
        )
        return grid

    until = state.picks_until_my_turn()
    upcoming = state.my_next_picks(3)
    labels = ", ".join(format_pick(p, state.teams, state.snake) for p in upcoming) or "none left"

    if until == 0:
        header = "[bold green]YOU ARE ON THE CLOCK[/]"
    elif until is None:
        header = "[dim]Your draft is done.[/]"
    else:
        header = f"[bold]{until}[/] picks until your turn"

    grid.add_row(
        Panel(
            f"{header}\n"
            f"Pick {state.on_the_clock} of {state.total_picks} · "
            f"round {format_pick(state.on_the_clock, state.teams, state.snake)}\n"
            f"Your slot: {state.my_slot} · your picks: {labels}",
            title=f"{lg.name} draft",
        )
    )

    recommendations = recommend(lg, pool, state, limit=limit)
    table = Table(title="Recommended", expand=True)
    table.add_column("Player")
    table.add_column("Pos", justify="center")
    table.add_column("Bye", justify="right")
    table.add_column("ADP", justify="right")
    table.add_column("VOR", justify="right")
    table.add_column("VONA", justify="right")
    table.add_column("Why", style="dim")
    for rec in recommendations:
        player = rec.player
        table.add_row(
            f"[bold]{player.name}[/]",
            _pos(player.position),
            str(player.bye_week or "-"),
            f"{player.adp:.1f}" if player.adp else "-",
            f"{rec.vor:+.0f}",
            f"[bold]{rec.vona:+.0f}[/]",
            rec.reason,
        )
    grid.add_row(table)

    my_ids = state.my_drafted_ids()
    if my_ids:
        roster = Table(title="Your roster", expand=True)
        roster.add_column("Rd", justify="right", style="dim")
        roster.add_column("Player")
        roster.add_column("Pos", justify="center")
        roster.add_column("Bye", justify="right")
        for pick in state.picks:
            if pick.get("draft_slot") != state.my_slot:
                continue
            player = pool.get(pick.get("player_id"))
            if not player:
                continue
            roster.add_row(
                str(pick.get("round", "?")),
                player.name,
                _pos(player.position),
                str(player.bye_week or "-"),
            )
        grid.add_row(roster)

    recent = state.picks[-6:]
    if recent:
        log = Table(title="Last picks", expand=True)
        log.add_column("Pick", justify="right", style="dim")
        log.add_column("Player")
        log.add_column("Pos", justify="center")
        for pick in recent:
            player = pool.get(pick.get("player_id"))
            name = player.name if player else pick.get("player_id", "?")
            position = _pos(player.position) if player else "?"
            log.add_row(str(pick.get("pick_no", "?")), name, position)
        grid.add_row(log)

    return grid


@app.command()
def draft(
    league_id: Optional[str] = typer.Option(None, "--league-id"),
    season: Optional[str] = typer.Option(None, "--season"),
    slot: Optional[int] = typer.Option(None, "--slot", help="Your draft column, if not set yet"),
    limit: int = typer.Option(6, "--limit", "-n", help="How many recommendations to show"),
    interval: float = typer.Option(5.0, "--interval", help="Seconds between polls"),
    once: bool = typer.Option(False, "--once", help="Render once and exit"),
) -> None:
    """Live draft board with pick recommendations."""
    client, lg, _ = _context(league_id, season)
    with client:
        if not lg.draft_id:
            console.print("[red]This league has no draft yet.[/]")
            raise typer.Exit(1)
        pool = build_pool(client, lg.season, lg.scoring, lg.roster_positions)

        if once:
            state = load_draft_state(client, lg.draft_id, lg.my_user_id, slot)
            console.print(_draft_view(lg, pool, state, limit))
            return

        console.print("[dim]Polling draft. Ctrl-C to stop.[/]")
        with Live(console=console, refresh_per_second=4, screen=False) as live:
            try:
                while True:
                    state = load_draft_state(client, lg.draft_id, lg.my_user_id, slot)
                    live.update(_draft_view(lg, pool, state, limit))
                    if state.is_complete:
                        break
                    time.sleep(interval)
            except KeyboardInterrupt:
                pass
        console.print("[dim]Stopped.[/]")


@app.command()
def roster(
    league_id: Optional[str] = typer.Option(None, "--league-id"),
    season: Optional[str] = typer.Option(None, "--season"),
) -> None:
    """Your current roster with projections."""
    client, lg, _ = _context(league_id, season)
    with client:
        mine = lg.my_roster
        if not mine:
            console.print("[yellow]You have no roster in this league yet.[/]")
            return
        pool = build_pool(client, lg.season, lg.scoring, lg.roster_positions)
        levels = replacement_levels(lg, pool)
        starters = set(mine.get("starters") or [])

        table = Table(title=f"{lg.name} — your roster")
        table.add_column("Slot", justify="center")
        table.add_column("Player")
        table.add_column("Pos", justify="center")
        table.add_column("Bye", justify="right")
        table.add_column("Proj", justify="right")
        table.add_column("VOR", justify="right")
        rows = [pool[pid] for pid in (mine.get("players") or []) if pid in pool]
        rows.sort(key=lambda p: p.proj_season, reverse=True)
        for player in rows:
            table.add_row(
                "[green]ST[/]" if player.player_id in starters else "[dim]BN[/]",
                player.name + (" [red]!" if player.injury_status else ""),
                _pos(player.position),
                str(player.bye_week or "-"),
                f"{player.proj_season:.0f}",
                f"{vor(player, levels):+.0f}",
            )
        console.print(table)


@app.command()
def lineup(
    week: Optional[int] = typer.Option(None, "--week", "-w"),
    league_id: Optional[str] = typer.Option(None, "--league-id"),
    season: Optional[str] = typer.Option(None, "--season"),
) -> None:
    """Start/sit check for a week, using this league's scoring."""
    client, lg, _ = _context(league_id, season)
    with client:
        target_week = week or client.state()["week"]
        mine = lg.my_roster
        if not mine:
            console.print("[yellow]You have no roster in this league yet.[/]")
            return
        pool = build_pool(client, lg.season, lg.scoring, lg.roster_positions)
        weekly = {
            row["player_id"]: score_line(row.get("stats"), lg.scoring)
            for row in client.week_projections(lg.season, target_week)
            if row.get("player_id")
        }
        starters = set(mine.get("starters") or [])

        table = Table(title=f"Week {target_week} projections")
        table.add_column("Slot", justify="center")
        table.add_column("Player")
        table.add_column("Pos", justify="center")
        table.add_column("Wk proj", justify="right")
        table.add_column("Flag", style="yellow")

        rows = []
        for player_id in mine.get("players") or []:
            player = pool.get(player_id)
            if not player:
                continue
            points = weekly.get(player_id, 0.0)
            rows.append((player, points, player_id in starters))
        rows.sort(key=lambda r: r[1], reverse=True)

        for player, points, is_starter in rows:
            flags = []
            if player.bye_week == target_week:
                flags.append("ON BYE")
            if player.injury_status:
                flags.append(player.injury_status)
            table.add_row(
                "[green]ST[/]" if is_starter else "[dim]BN[/]",
                player.name,
                _pos(player.position),
                f"{points:.1f}",
                ", ".join(flags),
            )
        console.print(table)

        benched = [r for r in rows if not r[2]]
        started = [r for r in rows if r[2]]
        swaps = []
        for bench_player, bench_points, _ in benched:
            for start_player, start_points, _ in started:
                if bench_player.position != start_player.position:
                    continue
                if bench_points > start_points + 1.0 or start_player.bye_week == target_week:
                    swaps.append((bench_player, bench_points, start_player, start_points))
                    break
        if swaps:
            console.print("\n[bold yellow]Suggested changes[/]")
            for bench_player, bench_points, start_player, start_points in swaps:
                console.print(
                    f"  Start [bold]{bench_player.name}[/] ({bench_points:.1f}) "
                    f"over {start_player.name} ({start_points:.1f})"
                )
        else:
            console.print("\n[green]Lineup looks optimal.[/]")


@app.command()
def waivers(
    league_id: Optional[str] = typer.Option(None, "--league-id"),
    season: Optional[str] = typer.Option(None, "--season"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Best available free agents in your league right now."""
    client, lg, _ = _context(league_id, season)
    with client:
        pool = build_pool(client, lg.season, lg.scoring, lg.roster_positions)
        trending = {row["player_id"]: row.get("count", 0) for row in client.trending("add")}
        rows = rank_free_agents(lg, pool, limit=limit)

        table = Table(title=f"{lg.name} — top free agents")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Player")
        table.add_column("Pos", justify="center")
        table.add_column("Tm", justify="center")
        table.add_column("Bye", justify="right")
        table.add_column("Proj", justify="right")
        table.add_column("VOR", justify="right")
        table.add_column("24h adds", justify="right")
        for index, (player, value) in enumerate(rows, start=1):
            adds = trending.get(player.player_id)
            table.add_row(
                str(index),
                player.name + (" [red]!" if player.injury_status else ""),
                _pos(player.position),
                player.team or "-",
                str(player.bye_week or "-"),
                f"{player.proj_season:.0f}",
                f"{value:+.0f}",
                f"{adds:,}" if adds else "-",
            )
        console.print(table)
        if rows:
            console.print(f"[dim]{waiver_advice(lg, rows[0][1], 1)}[/]")


@app.command()
def watch(
    league_id: Optional[str] = typer.Option(None, "--league-id"),
    season: Optional[str] = typer.Option(None, "--season"),
    notify: bool = typer.Option(True, "--notify/--no-notify", help="Send ntfy push"),
    min_vor: float = typer.Option(-20.0, "--min-vor", help="Ignore players below this VOR"),
    limit: int = typer.Option(6, "--limit", help="Max alerts per run"),
) -> None:
    """One waiver-watcher pass. Designed to be driven by a systemd timer."""
    client, lg, config = _context(league_id, season)
    with client:
        pool = build_pool(client, lg.season, lg.scoring, lg.roster_positions)
        trending = client.trending("add", limit=100)

        state_path = Path(config.state_dir) / f"watch_{lg.league_id}.json"
        state = WatcherState.load(state_path)
        first_run = not state.initialised

        alerts = detect_alerts(lg, pool, state, trending, min_vor=min_vor)[:limit]
        update_state(state, lg, pool, alerts)
        state.save(state_path)

        if first_run:
            console.print(
                "[dim]Baseline recorded. Drops will be detected from the next run onward.[/]"
            )
            return

        if not alerts:
            console.print("[dim]No wire movement worth flagging.[/]")
            return

        notifier = Notifier(
            config.ntfy_server, config.ntfy_topic, token=config.ntfy_token, enabled=notify
        )
        for alert in alerts:
            console.print(f"[bold]{alert.headline}[/]\n  {alert.detail}")
            if notify:
                sent = notifier.send(
                    title=alert.headline,
                    message=alert.detail,
                    priority=alert.priority,
                    click=f"https://sleeper.com/leagues/{lg.league_id}/team",
                )
                if not sent:
                    console.print("  [yellow]ntfy push failed[/]")


if __name__ == "__main__":
    app()
