"""Apply a league's own scoring settings to a Sleeper stat or projection line.

Sleeper's ``scoring_settings`` keys are the same names as the keys in a stat
line (``rec``, ``rush_yd``, ``pass_td``, the ``pts_allow_*`` buckets for
defenses, the ``fgm_*`` distance buckets for kickers), so scoring a line is a
dot product over the keys the two have in common. Doing it this way rather than
reading Sleeper's precomputed ``pts_ppr`` means custom scoring, bonuses and
premium-TE settings are all honoured automatically.
"""

from __future__ import annotations

from typing import Any, Mapping

# Keys that appear in scoring_settings but are league configuration rather than
# a per-stat multiplier, so they must never be folded into the dot product.
NON_STAT_KEYS = frozenset(
    {
        "rec_yd_bonus",
        "best_ball",
        "type",
    }
)


def score_line(stats: Mapping[str, Any] | None, scoring: Mapping[str, float]) -> float:
    """Fantasy points for one stat line under one league's scoring settings."""
    if not stats:
        return 0.0
    total = 0.0
    for key, multiplier in scoring.items():
        if key in NON_STAT_KEYS or not multiplier:
            continue
        value = stats.get(key)
        if isinstance(value, (int, float)):
            total += float(value) * float(multiplier)
    return round(total, 2)


def is_standard_ppr(scoring: Mapping[str, float]) -> bool:
    """True when the league scores a plain full-PPR line with no bonuses."""
    if scoring.get("rec") != 1.0:
        return False
    return not any(key.startswith("bonus") and value for key, value in scoring.items())
