"""Weekly fact sheet: every number an article may use, with an id.

Articles are written from this sheet only. Anything not on it is not a fact
the writer may state.
"""
import json
import math
import statistics
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import db
from .collect import date_range
from .parse import number, ratio

PT = ZoneInfo("America/Los_Angeles")
KST = ZoneInfo("Asia/Seoul")
PCT_SOURCE = {"FG%": "FGM/A", "FT%": "FTM/A"}  # percentage category -> made/attempted stat
NON_STARTING = {"BN", "IL", "IL+", "NA"}  # never starters, whatever the settings list
BLOWOUT_WINS = 8
STREAK_LENGTH = 3
CANDIDATES = 5


def _fmt(value):
    """Totals as Yahoo prints them: 50, not 50.0."""
    return str(int(value)) if float(value).is_integer() else str(round(value, 1))


def _record(wlt):
    return "-".join(str(n) for n in wlt)


def _pt_midnight(day):
    return int(datetime.combine(datetime.fromisoformat(day).date(), time(), PT).timestamp())


def _categories(conn):
    rows = conn.execute("SELECT * FROM stat_categories ORDER BY position").fetchall()
    by_name = {r["display_name"]: r for r in rows}
    out = []
    for r in rows:
        if r["is_display_only"]:
            continue
        source = by_name.get(PCT_SOURCE.get(r["display_name"]))
        out.append({
            "name": r["display_name"],
            "stat_id": r["stat_id"],
            "lower": bool(r["lower_is_better"]),
            "source_id": source["stat_id"] if source else None,
            "source_name": source["display_name"] if source else None,
        })
    return out


# ---- matchups ------------------------------------------------------------

def _compare(cat, stats_a, stats_b):
    """'a' / 'b' / 'tie' from the two teams' values, or None if either is missing."""
    va = vb = None
    if cat["source_id"]:
        ra, rb = ratio(stats_a.get(cat["source_id"])), ratio(stats_b.get(cat["source_id"]))
        if ra and rb and ra[1] and rb[1]:
            va, vb = ra[0] / ra[1], rb[0] / rb[1]
    if va is None or vb is None:
        va, vb = number(stats_a.get(cat["stat_id"])), number(stats_b.get(cat["stat_id"]))
    if va is None or vb is None:
        return None
    if va == vb:
        return "tie"
    return "a" if (va < vb) == cat["lower"] else "b"


def _week_results(conn, week, cats):
    """Category-by-category outcome of every matchup in a week."""
    out = []
    for m in conn.execute("SELECT * FROM matchups WHERE week=? ORDER BY idx", (week,)).fetchall():
        a, b = m["team_a"], m["team_b"]
        stats = {
            team: dict(conn.execute(
                "SELECT stat_id, value FROM matchup_stats WHERE week=? AND team_key=?", (week, team)))
            for team in (a, b)
        }
        official = {
            r["stat_id"]: r
            for r in conn.execute("SELECT * FROM matchup_winners WHERE week=? AND idx=?", (week, m["idx"]))
        }
        tally = {a: [0, 0, 0], b: [0, 0, 0]}
        cat_rows = []
        for cat in cats:
            row = official.get(cat["stat_id"])
            if row is not None:
                who = "tie" if row["is_tied"] else {a: "a", b: "b"}.get(row["winner_team_key"])
            else:
                who = _compare(cat, stats[a], stats[b])
            if who == "a":
                tally[a][0] += 1
                tally[b][1] += 1
            elif who == "b":
                tally[b][0] += 1
                tally[a][1] += 1
            elif who == "tie":
                tally[a][2] += 1
                tally[b][2] += 1
            cat_rows.append({"cat": cat, "who": who, "stats": (stats[a], stats[b])})
        wins_a, wins_b = tally[a][0], tally[b][0]
        out.append({
            "idx": m["idx"], "a": a, "b": b, "tally": tally, "cats": cat_rows,
            "winner": a if wins_a > wins_b else b if wins_b > wins_a else None,
            "decided": any(sum(t) for t in tally.values()),
            "playoffs": bool(m["is_playoffs"]), "status": m["status"],
        })
    return out


def _matchup_section(results, names):
    out = []
    for r in results:
        a, b = r["a"], r["b"]
        categories = []
        for row in r["cats"]:
            cat, (sa, sb) = row["cat"], row["stats"]
            entry = {"name": cat["name"], "values": [sa.get(cat["stat_id"]) or None, sb.get(cat["stat_id"]) or None]}
            if cat["source_id"]:
                entry["made_attempted"] = [sa.get(cat["source_id"]) or None, sb.get(cat["source_id"]) or None]
            entry["winner"] = {"a": names[a], "b": names[b], "tie": "tie", None: None}[row["who"]]
            categories.append(entry)
        out.append({
            "teams": [names[a], names[b]],
            "score": [_record(r["tally"][a]), _record(r["tally"][b])],
            "winner": names[r["winner"]] if r["winner"] else None,
            "status": r["status"],
            "categories": categories,
        })
    return out


def _score_checks(conn, week, results, names):
    """Category wins we worked out must match the score Yahoo shows."""
    official = {r["idx"]: r for r in conn.execute("SELECT * FROM matchup_scores WHERE week=?", (week,))}
    checks = []
    for r in results:
        row = official.get(r["idx"])
        ours = (r["tally"][r["a"]][0], r["tally"][r["b"]][0])
        if row and ours != (row["wins_a"], row["wins_b"]):
            checks.append({
                "type": "score_mismatch", "teams": [names[r["a"]], names[r["b"]]],
                "computed": f"{ours[0]}-{ours[1]}", "yahoo": f"{row['wins_a']}-{row['wins_b']}",
            })
    return checks


# ---- standings -----------------------------------------------------------

def _standings(results_by_week, through_week, team_keys, names):
    """Cumulative category record through a week. A tie is half a win."""
    totals = {t: [0, 0, 0] for t in team_keys}
    for week in range(1, through_week + 1):
        for r in results_by_week.get(week, []):
            if r["playoffs"]:
                continue
            for team in (r["a"], r["b"]):
                if team in totals:
                    totals[team] = [x + y for x, y in zip(totals[team], r["tally"][team])]
    rows = []
    for team, (w, l, t) in totals.items():
        games = w + l + t
        rows.append({
            "team_key": team, "team": names[team], "w": w, "l": l, "t": t,
            "record": _record((w, l, t)),
            "pct": round((w + 0.5 * t) / games, 3) if games else None,
        })
    ranked = any(r["pct"] is not None for r in rows)
    rows.sort(key=lambda r: (-(r["pct"] or 0), -r["w"], r["team"]) if ranked else (r["team"],))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i if ranked else None
    return rows


def _standings_checks(conn, rows, week_end):
    """Compare our record with the first Yahoo snapshot that covers the same games."""
    checks = []
    for r in rows:
        games = r["w"] + r["l"] + r["t"]
        snap = conn.execute(
            """SELECT wins, losses, ties FROM standings
               WHERE team_key=? AND date>=? AND wins+losses+ties=? ORDER BY date LIMIT 1""",
            (r["team_key"], week_end, games),
        ).fetchone()
        if snap and games and tuple(snap) != (r["w"], r["l"], r["t"]):
            checks.append({
                "type": "standings_mismatch", "team": r["team"],
                "computed": r["record"], "yahoo": _record(tuple(snap)),
            })
    return checks


# ---- player weeks --------------------------------------------------------

def _bench_slots(conn):
    """Slots the league marks as non-starting; every other slot is a starter."""
    rows = conn.execute("SELECT position, is_starting FROM roster_positions").fetchall()
    return {r["position"] for r in rows if r["is_starting"] == 0} | NON_STARTING


def _player_weeks(conn, cats, start, end):
    """Sum each player's days per team, split into started and not-started days."""
    bench = _bench_slots(conn)
    day_stats = {}
    for r in conn.execute(
        "SELECT date, player_key, stat_id, value FROM player_stats WHERE date BETWEEN ? AND ?", (start, end)
    ):
        day_stats.setdefault((r["date"], r["player_key"]), {})[r["stat_id"]] = r["value"]

    acc = {}
    for r in conn.execute(
        """SELECT r.date, r.team_key, r.player_key, r.slot, p.name, p.nba_team,
                  COALESCE(d.played, 0) AS played
           FROM roster_daily r JOIN players p USING(player_key)
           LEFT JOIN player_days d ON d.date=r.date AND d.player_key=r.player_key
           WHERE r.date BETWEEN ? AND ? ORDER BY r.date""", (start, end)
    ):
        started = r["slot"] not in bench
        entry = acc.setdefault((r["team_key"], r["player_key"], started), {
            "team_key": r["team_key"], "name": r["name"], "nba_team": r["nba_team"],
            "started": started, "games": 0,
            "sums": {c["stat_id"]: 0.0 for c in cats},
            "shots": {c["stat_id"]: [0.0, 0.0] for c in cats if c["source_id"]},
        })
        if not r["played"]:
            continue
        entry["games"] += 1
        stats = day_stats.get((r["date"], r["player_key"]), {})
        for cat in cats:
            if cat["source_id"]:
                made_att = ratio(stats.get(cat["source_id"]))
                if made_att:
                    entry["shots"][cat["stat_id"]][0] += made_att[0]
                    entry["shots"][cat["stat_id"]][1] += made_att[1]
            else:
                entry["sums"][cat["stat_id"]] += number(stats.get(cat["stat_id"])) or 0.0
    return list(acc.values())


def _line(entry, cats):
    line = {}
    for cat in cats:
        if cat["source_id"]:
            made, att = entry["shots"][cat["stat_id"]]
            line[cat["source_name"]] = f"{_fmt(made)}/{_fmt(att)}"
            line[cat["name"]] = round(made / att, 3) if att else None
        else:
            total = entry["sums"][cat["stat_id"]]
            line[cat["name"]] = int(total) if total.is_integer() else round(total, 1)
    return line


def _zscores(values):
    spread = statistics.pstdev(values) if len(values) > 1 else 0.0
    if not spread:
        return [0.0] * len(values)
    mean = statistics.fmean(values)
    return [(v - mean) / spread for v in values]


def _score(entries, cats):
    """Sum of z-scores across the scoring categories, among players who
    started at least one game. Shooting counts as makes above (or below) what
    the pool's average percentage would give on the same attempts."""
    pool = [e for e in entries if e["started"] and e["games"]]
    totals = [0.0] * len(pool)
    for cat in cats:
        if cat["source_id"]:
            made = sum(e["shots"][cat["stat_id"]][0] for e in pool)
            att = sum(e["shots"][cat["stat_id"]][1] for e in pool)
            average = made / att if att else 0.0
            values = [
                e["shots"][cat["stat_id"]][0] - e["shots"][cat["stat_id"]][1] * average for e in pool
            ]
        else:
            values = [e["sums"][cat["stat_id"]] for e in pool]
        sign = -1.0 if cat["lower"] else 1.0
        totals = [t + sign * z for t, z in zip(totals, _zscores(values))]
    for entry, total in zip(pool, totals):
        entry["score"] = round(total, 2)
    return pool


def _totals_checks(entries, results, cats, names):
    """Our started-player totals must equal Yahoo's official team totals."""
    checks = []
    for r in results:
        for team, stats in zip((r["a"], r["b"]), r["cats"][0]["stats"] if r["cats"] else ({}, {})):
            mine = [e for e in entries if e["team_key"] == team and e["started"]]
            for cat in cats:
                if cat["source_id"]:
                    official = stats.get(cat["source_id"])
                    if not ratio(official):
                        continue
                    made = sum(e["shots"][cat["stat_id"]][0] for e in mine)
                    att = sum(e["shots"][cat["stat_id"]][1] for e in mine)
                    computed = f"{_fmt(made)}/{_fmt(att)}"
                    same = ratio(official) == (made, att)
                else:
                    official = stats.get(cat["stat_id"])
                    if number(official) is None:
                        continue
                    total = sum(e["sums"][cat["stat_id"]] for e in mine)
                    computed = _fmt(total)
                    same = number(official) == total
                if not same:
                    checks.append({
                        "type": "total_mismatch", "team": names[team], "category": cat["name"],
                        "official": official, "computed": computed,
                    })
    return checks


# ---- lineup changes ------------------------------------------------------

def _lineup_changes(conn, start, end, names):
    """Players whose slot crossed the starter/bench line between the snapshot
    taken before the games and the roster that actually counted."""
    bench = _bench_slots(conn)
    stat_names = dict(conn.execute("SELECT stat_id, display_name FROM stat_categories"))
    out = []
    for r in conn.execute(
        """SELECT l.date, l.team_key, l.player_key, l.slot AS before, r.slot AS after, p.name,
                  COALESCE(d.played, 0) AS played
           FROM lineup_pre l
           JOIN roster_daily r ON r.date=l.date AND r.team_key=l.team_key AND r.player_key=l.player_key
           JOIN players p ON p.player_key=l.player_key
           LEFT JOIN player_days d ON d.date=l.date AND d.player_key=l.player_key
           WHERE l.date BETWEEN ? AND ? ORDER BY l.date, l.team_key, p.name""", (start, end)
    ).fetchall():
        was_starting, is_starting = r["before"] not in bench, r["after"] not in bench
        if was_starting == is_starting:
            continue
        change = {
            "date": r["date"], "team": names.get(r["team_key"], r["team_key"]), "player": r["name"],
            "from": r["before"], "to": r["after"], "change": "started" if is_starting else "benched",
            "played": bool(r["played"]),
        }
        if r["played"]:
            change["line"] = {
                stat_names.get(stat_id, stat_id): value
                for stat_id, value in conn.execute(
                    "SELECT stat_id, value FROM player_stats WHERE date=? AND player_key=?",
                    (r["date"], r["player_key"]))
            }
        out.append(change)
    return out


# ---- transactions --------------------------------------------------------

def _place(kind, team_key, names):
    if team_key:
        return names.get(team_key, team_key)
    return {"freeagents": "FA", "waivers": "Waivers"}.get(kind, kind or "?")


def _transactions(conn, names, start_ts=None, end_ts=None):
    out = []
    for t in conn.execute(
        """SELECT * FROM transactions WHERE status='successful'
           AND (? IS NULL OR timestamp>=?) AND (? IS NULL OR timestamp<?)
           ORDER BY timestamp, transaction_key""", (start_ts, start_ts, end_ts, end_ts)
    ).fetchall():
        moves = [
            {
                "player": p["name"], "action": p["action"],
                "from": _place(p["source_type"], p["source_team_key"], names),
                "to": _place(p["destination_type"], p["destination_team_key"], names),
            }
            for p in conn.execute(
                "SELECT * FROM transaction_players WHERE transaction_key=? ORDER BY rowid",
                (t["transaction_key"],))
        ]
        when = datetime.fromtimestamp(t["timestamp"], KST).strftime("%Y-%m-%d %H:%M")
        out.append({"time_kst": when, "type": t["type"], "moves": moves})
    return out


def _adds(conn, team_key, start_ts, end_ts):
    return conn.execute(
        """SELECT COUNT(*) FROM transaction_players p JOIN transactions t USING(transaction_key)
           WHERE t.status='successful' AND p.action='add' AND p.destination_team_key=?
           AND (? IS NULL OR t.timestamp>=?) AND t.timestamp<?""",
        (team_key, start_ts, start_ts, end_ts),
    ).fetchone()[0]


# ---- hooks ---------------------------------------------------------------

def _streaks(results_by_week, through_week, names):
    history = {}
    for week in range(1, through_week + 1):
        for r in results_by_week.get(week, []):
            for team in (r["a"], r["b"]):
                outcome = "tie" if r["winner"] is None else "win" if r["winner"] == team else "loss"
                history.setdefault(team, []).append(outcome)
    hooks = []
    for team in sorted(history, key=lambda t: names[t]):
        kind = history[team][-1]
        length = 0
        for outcome in reversed(history[team]):
            if outcome != kind:
                break
            length += 1
        if kind != "tie" and length >= STREAK_LENGTH:
            hooks.append({"type": "streak", "team": names[team], "kind": kind, "length": length})
    return hooks


def _hooks(results, prev_rank, teams, streaks, names, upset_gap):
    hooks = []
    for r in results:
        if not r["decided"]:
            continue
        a, b = r["a"], r["b"]
        if r["winner"] is None:
            hooks.append({"type": "tie", "teams": [names[a], names[b]], "score": _record(r["tally"][a])})
            continue
        winner = r["winner"]
        loser = b if winner == a else a
        if r["tally"][winner][0] >= BLOWOUT_WINS:
            hooks.append({
                "type": "blowout", "winner": names[winner], "loser": names[loser],
                "score": _record(r["tally"][winner]),
            })
        wr, lr = prev_rank.get(winner), prev_rank.get(loser)
        if wr and lr and wr - lr >= upset_gap:
            hooks.append({
                "type": "upset", "winner": names[winner], "winner_prev_rank": wr,
                "loser": names[loser], "loser_prev_rank": lr, "score": _record(r["tally"][winner]),
            })
    hooks.extend(streaks)
    for team in teams:
        adds = team["adds"]
        if adds["week_limit"] and adds["week"] >= adds["week_limit"]:
            hooks.append({"type": "adds_limit", "team": team["team"], "adds": adds["week"]})
    return hooks


# ---- the sheet -----------------------------------------------------------

def _with_ids(prefix, items):
    return [{"id": f"{prefix}{i}", **item} for i, item in enumerate(items, start=1)]


def _int_meta(meta, key):
    try:
        return int(meta.get(key))
    except (TypeError, ValueError):
        return None


def _season_label(meta):
    season = _int_meta(meta, "season")
    return f"{season}-{(season + 1) % 100:02d}" if season else None


def build_week(conn, week, upset_gap=5):
    weeks = {r["week"]: r for r in conn.execute("SELECT * FROM weeks")}
    if week not in weeks:
        raise ValueError(f"week {week} is not in this season's schedule")
    start, end = weeks[week]["start"], weeks[week]["end"]
    meta = db.meta(conn)
    cats = _categories(conn)
    names = dict(conn.execute("SELECT team_key, name FROM teams"))
    managers = dict(conn.execute("SELECT team_key, manager FROM teams"))
    collected = {r[0] for r in conn.execute("SELECT date FROM run_log")}
    last_day = max(collected, default="")
    in_week = sorted(d for d in collected if start <= d <= end)
    through = in_week[-1] if in_week else None
    complete = through == end

    results_by_week = {w: _week_results(conn, w, cats) for w in weeks if w <= week + 1}
    results = results_by_week[week]
    for r in results_by_week.values():
        for m in r:
            names.setdefault(m["a"], m["a"])
            names.setdefault(m["b"], m["b"])

    finished = [w for w in weeks if w <= week and weeks[w]["end"] <= last_day]
    standings_week = max(finished, default=0)
    standings = _standings(results_by_week, standings_week, list(names), names)
    previous = _standings(results_by_week, standings_week - 1, list(names), names) if standings_week > 1 else []
    prev_rank = {r["team_key"]: r["rank"] for r in previous}
    for r in standings:
        r["prev_rank"] = prev_rank.get(r["team_key"])
        r["change"] = r["prev_rank"] - r["rank"] if r["prev_rank"] and r["rank"] else None
    rank_now = {r["team_key"]: r for r in standings}
    # "Rank coming into this week" for upsets: standings before this week's results.
    known_before = week - 1 in weeks and weeks[week - 1]["end"] <= last_day
    before = _standings(results_by_week, week - 1, list(names), names) if known_before else []
    rank_before = {r["team_key"]: r["rank"] for r in before}

    checks = []
    if through:
        missing = [d for d in date_range(start, through) if d not in collected]
        if missing:
            checks.append({"type": "missing_days", "days": missing})
    for row in conn.execute("SELECT date, warnings FROM run_log WHERE date BETWEEN ? AND ? ORDER BY date",
                            (start, end)):
        for detail in json.loads(row["warnings"] or "[]"):
            checks.append({"type": "collection_warning", "day": row["date"], "detail": detail})
    if standings_week:
        checks.extend(_standings_checks(conn, standings, weeks[standings_week]["end"]))
    checks.extend(_score_checks(conn, week, results, names))

    entries = _player_weeks(conn, cats, start, end)
    pool = _score(entries, cats)
    checks.extend(_totals_checks(entries, results, cats, names))

    def player_row(entry, with_score=True):
        row = {"name": entry["name"], "nba_team": entry["nba_team"], "games": entry["games"],
               "line": _line(entry, cats)}
        if with_score:
            row["score"] = entry.get("score")
        return row

    week_start_ts, week_end_ts = _pt_midnight(start), _pt_midnight(end) + 86400
    order = [t for r in results for t in (r["a"], r["b"])]
    order += sorted((t for t in names if t not in order), key=lambda t: names[t])
    teams = []
    for team in order:
        mine = [e for e in entries if e["team_key"] == team]
        started = sorted((e for e in mine if e["started"]), key=lambda e: -(e.get("score") or -99))
        benched = sorted((e for e in mine if not e["started"] and e["games"]), key=lambda e: e["name"])
        teams.append({
            "team": names[team], "manager": managers.get(team),
            "adds": {
                "week": _adds(conn, team, week_start_ts, week_end_ts),
                "week_limit": _int_meta(meta, "max_weekly_adds"),
                "season": _adds(conn, team, None, week_end_ts),
                "season_limit": _int_meta(meta, "max_adds"),
            },
            "players": [player_row(e) for e in started],
            "benched": [player_row(e, with_score=False) for e in benched],
        })

    def candidate(entry):
        return {**player_row(entry), "team": names[entry["team_key"]]}

    by_score = sorted(pool, key=lambda e: (-e["score"], e["name"]))
    most_games = max((e["games"] for e in pool), default=0)
    min_games = max(2, math.ceil(most_games / 2))
    regulars = [e for e in reversed(by_score) if e["games"] >= min_games]

    next_week = [
        {
            "teams": [names[r["a"]], names[r["b"]]],
            "ranks": [rank_now[r["a"]]["rank"], rank_now[r["b"]]["rank"]],
            "records": [rank_now[r["a"]]["record"], rank_now[r["b"]]["record"]],
        }
        for r in results_by_week.get(week + 1, [])
    ]
    streaks = _streaks(results_by_week, standings_week, names) if standings_week == week else []
    for r in standings:
        del r["team_key"]

    return {
        "meta": {
            "league": meta.get("name"), "season": _season_label(meta), "week": week,
            "week_start": start, "week_end": end, "through": through, "complete": complete,
            "is_playoffs": any(r["playoffs"] for r in results),
            "standings_through_week": standings_week,
            "lvp_min_games": min_games,
            "lineup_snapshot_days": [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM lineup_pre WHERE date BETWEEN ? AND ? ORDER BY date", (start, end))],
        },
        "categories": [{"name": c["name"], "lower_is_better": c["lower"]} for c in cats],
        "checks": checks,
        "matchups": _with_ids("M", _matchup_section(results, names)),
        "standings": _with_ids("S", standings),
        "teams": _with_ids("T", teams),
        "mvp_candidates": _with_ids("P", [candidate(e) for e in by_score[:CANDIDATES]]),
        "lvp_candidates": _with_ids("L", [candidate(e) for e in regulars[:CANDIDATES]]),
        "transactions": _with_ids("X", _transactions(conn, names, week_start_ts, week_end_ts)),
        "lineup_changes": _with_ids("C", _lineup_changes(conn, start, end, names)),
        "hooks": _with_ids("H", _hooks(results, rank_before, teams, streaks, names, upset_gap)),
        "next_week": _with_ids("N", next_week),
    }


def build_preseason(conn):
    """Moves made after the draft and before opening day."""
    meta = db.meta(conn)
    names = dict(conn.execute("SELECT team_key, name FROM teams"))
    end_ts = _pt_midnight(meta["start_date"])
    return {
        "meta": {"league": meta.get("name"), "season": _season_label(meta), "before": meta["start_date"]},
        "transactions": _with_ids("X", _transactions(conn, names, None, end_ts)),
    }


# ---- markdown ------------------------------------------------------------

def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join("" if c is None else str(c) for c in row) + " |" for row in rows]
    return lines


def _line_cells(line, columns):
    return [line.get(c) for c in columns]


def _hook_text(hook):
    kind = hook["type"]
    if kind == "tie":
        return f"무승부: {hook['teams'][0]} vs {hook['teams'][1]} ({hook['score']})"
    if kind == "blowout":
        return f"대승: {hook['winner']} {hook['score']} {hook['loser']}"
    if kind == "upset":
        return (f"업셋: {hook['winner']}(직전 {hook['winner_prev_rank']}위)가 "
                f"{hook['loser']}(직전 {hook['loser_prev_rank']}위)에게 {hook['score']} 승")
    if kind == "streak":
        return f"{hook['team']} 매치업 {hook['length']}{'연승' if hook['kind'] == 'win' else '연패'}"
    if kind == "adds_limit":
        return f"{hook['team']} 주간 영입 한도 소진 ({hook['adds']}회)"
    return str(hook)


def _move_text(move):
    return f"{move['player']} ({move['action']}: {move['from']} → {move['to']})"


def render_md(sheet):
    """The fact sheet as a readable document. Same content as the JSON."""
    meta = sheet["meta"]
    state = "주간 확정" if meta["complete"] else "진행 중"
    out = [
        f"# {meta['league']} {meta['season']} · Week {meta['week']} 팩트시트",
        "",
        f"- 기간: {meta['week_start']} ~ {meta['week_end']} (미국 태평양 시간 기준)",
        f"- 데이터: {meta['through'] or '수집 전'}까지 · {state}"
        + (" · 플레이오프" if meta["is_playoffs"] else ""),
        (f"- 순위 기준: Week {meta['standings_through_week']}까지 (무승부는 0.5승)"
         if meta["standings_through_week"] else "- 순위 기준: 아직 끝난 주 없음"),
        "",
        "## 데이터 점검",
    ]
    if sheet["checks"]:
        out.append("아래 항목이 해결되기 전에는 관련 숫자를 기사에 쓰지 않는다.")
        out += [f"- [{c['type']}] " + ", ".join(f"{k}={v}" for k, v in c.items() if k != "type")
                for c in sheet["checks"]]
    else:
        out.append("- 이상 없음")

    out += ["", "## 매치업"]
    for m in sheet["matchups"]:
        a, b = m["teams"]
        result = f"승: {m['winner']}" if m["winner"] else "무승부 또는 미정"
        out += ["", f"### {m['id']} {a} {m['score'][0]} {b} — {result}"]
        rows = []
        for c in m["categories"]:
            va, vb = c["values"]
            if "made_attempted" in c:
                va = f"{va} ({c['made_attempted'][0]})" if va else va
                vb = f"{vb} ({c['made_attempted'][1]})" if vb else vb
            rows.append([c["name"], va, vb, c["winner"]])
        out += _table(["카테고리", a, b, "승"], rows)

    out += ["", "## 순위"]
    out += _table(
        ["ID", "순위", "팀", "전적", "승률", "직전 순위", "변동"],
        [[s["id"], s["rank"], s["team"], s["record"], s["pct"], s["prev_rank"],
          None if s["change"] is None else f"{s['change']:+d}"] for s in sheet["standings"]],
    )

    columns = []
    for c in sheet["categories"]:
        columns += [PCT_SOURCE[c["name"]], c["name"]] if c["name"] in PCT_SOURCE else [c["name"]]
    for title, key in (("MVP 후보 (선발 슬롯 기록 기준)", "mvp_candidates"),
                       (f"LVP 후보 (선발 {meta['lvp_min_games']}경기 이상)", "lvp_candidates")):
        out += ["", f"## {title}"]
        out += _table(
            ["ID", "선수", "팀", "NBA", "G", "점수"] + columns,
            [[p["id"], p["name"], p["team"], p["nba_team"], p["games"], p["score"]]
             + _line_cells(p["line"], columns) for p in sheet[key]],
        )

    out += ["", "## 팀별 선수 기록 (선발 슬롯에 있던 날만 합산)"]
    for t in sheet["teams"]:
        adds = t["adds"]
        out += ["", f"### {t['id']} {t['team']} — 영입 주 {adds['week']}/{adds['week_limit']}, "
                    f"시즌 {adds['season']}/{adds['season_limit']}"]
        out += _table(
            ["선수", "NBA", "G", "점수"] + columns,
            [[p["name"], p["nba_team"], p["games"], p["score"]] + _line_cells(p["line"], columns)
             for p in t["players"]],
        )
        if t["benched"]:
            out.append("")
            out.append("벤치·IL에서 뛴 기록(팀 합계에 불포함):")
            out += _table(
                ["선수", "NBA", "G"] + columns,
                [[p["name"], p["nba_team"], p["games"]] + _line_cells(p["line"], columns)
                 for p in t["benched"]],
            )

    out += ["", "## 트랜잭션 (한국 시간)"]
    out += [f"- {x['id']} {x['time_kst']} · {x['type']} · " + "; ".join(_move_text(m) for m in x["moves"])
            for x in sheet["transactions"]] or ["- 없음"]

    out += ["", "## 경기 전 라인업 변경 (전날 밤 스냅샷 대비)"]
    covered = meta.get("lineup_snapshot_days") or []
    out.append(f"- 스냅샷이 있는 날: {', '.join(covered) if covered else '없음'}")
    for c in sheet.get("lineup_changes", []):
        what = "선발로 올림" if c["change"] == "started" else "벤치로 내림"
        if c["played"]:
            line = c.get("line", {})
            played = "그날 기록 " + ", ".join(f"{k} {v}" for k, v in line.items() if v not in ("-", "-/-"))
        else:
            played = "그날 기록 없음"
        out.append(f"- {c['id']} {c['date']} · {c['team']} · {c['player']}: {c['from']} → {c['to']} ({what}, {played})")

    out += ["", "## 스토리 훅"]
    out += [f"- {h['id']} {_hook_text(h)}" for h in sheet["hooks"]] or ["- 없음"]

    out += ["", "## 다음 주 대진"]
    out += [f"- {n['id']} {n['teams'][0]} ({n['ranks'][0]}위, {n['records'][0]}) vs "
            f"{n['teams'][1]} ({n['ranks'][1]}위, {n['records'][1]})" for n in sheet["next_week"]] or ["- 미정"]
    return "\n".join(out) + "\n"


# ---- draft ---------------------------------------------------------------

def build_draft(conn):
    """Draft board with value against Yahoo's average pick, and each team's
    roster measured by last season's totals."""
    meta = db.meta(conn)
    cats = _categories(conn)
    names = dict(conn.execute("SELECT team_key, name FROM teams"))
    prev = {}
    for r in conn.execute("SELECT player_key, stat_id, value FROM prev_season_stats"):
        prev.setdefault(r["player_key"], {})[r["stat_id"]] = r["value"]

    picks, entries = [], {}
    for r in conn.execute(
        """SELECT d.pick, d.round, d.team_key, d.player_key, p.name, p.nba_team, p.position, a.average_pick
           FROM draft_results d LEFT JOIN players p USING(player_key)
           LEFT JOIN draft_analysis a USING(player_key) ORDER BY d.pick"""
    ):
        adp = r["average_pick"]
        picks.append({
            "pick": r["pick"], "round": r["round"], "team": names.get(r["team_key"], r["team_key"]),
            "player": r["name"] or r["player_key"], "nba_team": r["nba_team"], "position": r["position"],
            "adp": adp, "vs_adp": None if adp is None else round(r["pick"] - adp, 1),
        })
        entry = entries.setdefault(r["team_key"], {
            "sums": {c["stat_id"]: 0.0 for c in cats},
            "shots": {c["stat_id"]: [0.0, 0.0] for c in cats if c["source_id"]},
        })
        stats = prev.get(r["player_key"], {})
        for cat in cats:
            if cat["source_id"]:
                made_att = ratio(stats.get(cat["source_id"]))
                if made_att:
                    entry["shots"][cat["stat_id"]][0] += made_att[0]
                    entry["shots"][cat["stat_id"]][1] += made_att[1]
            else:
                entry["sums"][cat["stat_id"]] += number(stats.get(cat["stat_id"])) or 0.0
    picks = _with_ids("D", picks)

    lines = {team: _line(entry, cats) for team, entry in entries.items()}
    ranks = {team: {} for team in lines}
    for cat in cats:
        ordered = sorted(
            lines, key=lambda t: lines[t][cat["name"]] or 0, reverse=not cat["lower"])
        for i, team in enumerate(ordered, start=1):
            ranks[team][cat["name"]] = i
    teams = [
        {
            "team": names.get(team, team),
            "picks": [p for p in picks if p["team"] == names.get(team, team)],
            "prev_season": lines[team],
            "category_ranks": ranks[team],
        }
        for team in sorted(lines, key=lambda t: names.get(t, t))
    ]
    valued = [p for p in picks if p["vs_adp"] is not None]
    return {
        "meta": {
            "league": meta.get("name"), "season": _season_label(meta),
            "prev_season_note": "prev_season = 직전 시즌 누적 기록(Yahoo). 올해 예상치가 아니다.",
        },
        "categories": [{"name": c["name"], "lower_is_better": c["lower"]} for c in cats],
        "picks": picks,
        "steals": sorted((p for p in valued if p["vs_adp"] > 0), key=lambda p: -p["vs_adp"])[:CANDIDATES],
        "reaches": sorted((p for p in valued if p["vs_adp"] < 0), key=lambda p: p["vs_adp"])[:CANDIDATES],
        "teams": _with_ids("T", teams),
    }


def render_draft_md(sheet):
    meta = sheet["meta"]
    columns = []
    for c in sheet["categories"]:
        columns += [PCT_SOURCE[c["name"]], c["name"]] if c["name"] in PCT_SOURCE else [c["name"]]
    cat_names = [c["name"] for c in sheet["categories"]]

    def pick_rows(picks):
        return [[p["id"], p["pick"], p["round"], p["team"], p["player"], p["nba_team"], p["position"],
                 p["adp"], p["vs_adp"]] for p in picks]

    headers = ["ID", "픽", "라운드", "팀", "선수", "NBA", "포지션", "평균 픽(ADP)", "픽-ADP"]
    out = [
        f"# {meta['league']} {meta['season']} · 드래프트 팩트시트",
        "",
        "- 픽-ADP: 양수면 평균보다 늦게 뽑힌 선수(스틸), 음수면 평균보다 일찍 뽑은 선수(리치).",
        f"- {meta['prev_season_note']}",
        "",
        "## 스틸 상위",
        *_table(headers, pick_rows(sheet["steals"])),
        "",
        "## 리치 상위",
        *_table(headers, pick_rows(sheet["reaches"])),
        "",
        "## 팀별 로스터",
    ]
    for t in sheet["teams"]:
        out += ["", f"### {t['id']} {t['team']}"]
        out += _table(headers, pick_rows(t["picks"]))
        out += ["", "직전 시즌 합계와 리그 내 순위:"]
        out += _table(
            ["구분"] + columns,
            [["합계"] + [t["prev_season"].get(c) for c in columns],
             ["순위"] + [t["category_ranks"].get(c) if c in cat_names else None for c in columns]],
        )
    out += ["", "## 전체 픽 순서", *_table(headers, pick_rows(sheet["picks"]))]
    return "\n".join(out) + "\n"
