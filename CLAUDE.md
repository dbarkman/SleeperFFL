# SleeperFFL — project context

Draft assistant and waiver-wire watcher for David's Sleeper fantasy football
league, on Sleeper's read-only HTTP API.

## The league

8 teams, snake draft, 15 rounds.
Full PPR (1.0/rec, 4pt pass TD, no bonuses). Starters are
QB/RB/RB/WR/WR/TE/FLEX/FLEX/K/DEF plus 5 bench. Rolling waiver priority (not
FAAB), 2-day clear. Playoffs start week 15. David is commissioner, roster 1.

The 8-team size matters everywhere: replacement level is much higher than in a
standard 12-team league, which is why the tool ranks by value over replacement
rather than raw projected points.

## Layout

| Module | Role |
|---|---|
| `api.py` | HTTP client, retry/backoff, both documented and undocumented hosts |
| `cache.py` | TTL disk cache, serves stale data when Sleeper is down |
| `config.py` | Environment configuration |
| `scoring.py` | Applies league `scoring_settings` to a stat line |
| `pool.py` | Merges player map + projections + schedule into `Player` records |
| `league.py` | League settings, managers, rosters, roster shape |
| `value.py` | Replacement level, VOR, ADP survival curve, roster need |
| `draft.py` | Snake math, live draft state, recommendations |
| `waivers.py` | Free-agent derivation, alert detection, watcher state |
| `notify.py` | ntfy push |
| `cli.py` | Typer CLI, rich output |

## Things that are easy to get wrong

* **The API is read-only.** No token exists because nothing can be written. The
  tool never makes a move; it only advises. Don't add "auto-draft" or
  "auto-claim" features — the endpoints do not exist.
* **Rolling waivers, not FAAB.** `waiver_type: 0`. Advice is framed as whether
  to burn waiver priority. `waiver_advice()` handles both, but this league is
  not a bidding league.
* **Bye weeks are not in the player map.** They are derived from the
  `/schedule` endpoint by finding each team's missing week.
* **Projections and ADP come from undocumented endpoints.** They work today but
  are unsupported. Anything reading them must degrade rather than crash.
* **`draft_order` is null until the commissioner sets it.** `resolve_my_slot`
  falls back to picks already made; `--slot` overrides for planning ahead.
* **Never cache `draft_picks`.** It is the live feed during a draft.
* **Sleeper asks for at most one `/players` call per day.** It is ~5MB. The
  cache TTL enforces this; do not bypass it.

## Ranking model

`score = need_multiplier x (0.45 x VOR + 0.55 x max(VONA, 0))`

Hard rules layered on top: positions at their cap are filtered off the board
entirely (no third QB, no second kicker); when picks left no longer exceed
unfilled starting slots, only players who fill one are considered, because an
empty starting slot scores zero every week; K and DEF are suppressed until the
final rounds. When the score base is negative the need discount is mirrored
(`base x (2 - multiplier)`) so a discount can never make a player look better.

Validated by simulating the real draft against ADP-following opponents — see the
sim approach in git history. The engine wins that simulation comfortably, but it
is a heuristic, not an oracle.

## Conventions

* uv only, exact `==` pins, `uv.lock` committed.
* Tests with pytest, `respx` for HTTP mocking. Run `uv run pytest`.
* Deploy: watcher only, to web2 as a systemd timer. See `deploy/README.md`.
  The draft assistant runs locally.
