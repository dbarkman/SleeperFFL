# SleeperFFL

Draft assistant and waiver-wire watcher for a Sleeper fantasy football league,
built on Sleeper's read-only HTTP API.

The API cannot make moves — there is no write access and no auth token exists.
Everything here tells you what to do; you still make the pick, set the lineup and
submit the claim in the Sleeper app.

## Install

```bash
uv sync
uv run sleeperffl --help
```

## Commands

| Command | What it does |
|---|---|
| `sleeperffl league` | League settings, managers, waiver order |
| `sleeperffl board` | Best-available board ranked by value over replacement |
| `sleeperffl draft` | Live draft board with pick recommendations |
| `sleeperffl roster` | Your roster with season projections |
| `sleeperffl lineup` | Start/sit check for a week |
| `sleeperffl waivers` | Best free agents available in your league now |
| `sleeperffl watch` | One waiver-watcher pass, pushes to ntfy |

## Draft day

```bash
uv run sleeperffl draft            # polls every 5s once the draft is live
uv run sleeperffl draft --slot 3   # plan from a hypothetical seat beforehand
```

The board refreshes as picks come in and shows what to take next.

### How a recommendation is made

1. **League-specific scoring.** Every projected stat line is scored with your
   league's own `scoring_settings` rather than Sleeper's generic `pts_ppr`, so
   bonuses, premium TE and odd kicker rules are all handled.
2. **Replacement level.** What a freely available starter is worth at each
   position *in this league*. An 8-team league has a far higher replacement
   level than a 14-team one, which is why raw projected points rank players
   badly. Flex slots are handed out greedily to whichever position still has the
   best player left, mirroring how a draft actually unfolds.
3. **VOR** — projected points above that replacement level.
4. **VONA** — value over the best player likely to still be there at your *next*
   pick, using an ADP-based survival curve over the exact number of picks until
   your turn comes round again. This is what stops you taking a player who would
   have lasted two more rounds.
5. **Roster shape.** Unfilled starting slots outrank bench depth; positions at
   their cap are dropped from the board entirely; kickers and defenses are
   suppressed until the final rounds; a position with mandatory slots and no
   backup gets a nudge.

`VONA` is the column to read at the clock. `VOR` is the column to read when
comparing players in the abstract.

## Waiver watcher

```bash
uv run sleeperffl waivers          # look at the wire now
uv run sleeperffl watch            # one pass, pushes alerts to ntfy
```

Sleeper has no free-agents endpoint, so the pool is derived: every player with a
projection, minus everyone rostered across all teams. Running that on a schedule
and diffing against the previous run turns it into alerts.

Three triggers:

* **Dropped** — a player who was rostered last run and is now free, above a
  value threshold.
* **Opening** — a free agent behind a rostered player who just went Out or IR.
* **Trending** — a leaguewide add surge on someone still available here.

Each alert carries advice framed for your league's waiver rules: a bid for FAAB
leagues, or whether the player is worth burning your priority position for a
rolling-waiver league.

Alerts de-duplicate per player with a 12-hour cooldown, and the first run only
records a baseline.

See `deploy/README.md` for running it on a schedule with systemd.

## Configuration

All optional — everything is discovered from your username by default.

| Variable | Default |
|---|---|
| `SLEEPERFFL_USERNAME` | `dbdev` |
| `SLEEPERFFL_LEAGUE_ID` | discovered (required if you are in several leagues) |
| `SLEEPERFFL_SEASON` | current season from Sleeper |
| `SLEEPERFFL_NTFY_TOPIC` | `dbdev-ffl` |
| `SLEEPERFFL_NTFY_SERVER` | `https://ntfy.sh` |
| `SLEEPERFFL_CACHE_DIR` | `~/.cache/sleeperffl` |
| `SLEEPERFFL_STATE_DIR` | `~/.local/state/sleeperffl` |

## Tests

```bash
uv run pytest
```

## A note on the endpoints

Two of the most useful endpoints are undocumented and can change without notice:

* `/projections/nfl/<season>[/<week>]` — projected stat lines and redraft ADP.
* `/stats/nfl/<season>/<week>` — actual results.
* `/schedule/nfl/regular/<season>` — used to derive bye weeks, which appear
  nowhere in the documented player map.

The documented API alone has no projections at all, so without these the tool
would be a scoreboard reader. Everything that touches them degrades rather than
crashes if they go away.
