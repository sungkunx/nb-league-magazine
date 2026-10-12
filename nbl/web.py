"""Data collected through the browser (see scripts/web_extract.js).

The browser script returns pipe-delimited text ending in a checksum line.
That text is saved as-is under <data_dir>/web:

    league/settings.txt, league/draft.txt
    weeks/week-NN.txt                 official team totals and score per matchup
    days/<date>/teams.txt             every team's slots and player lines that day
    days/<date>/lineup-pre.txt        optional: the same page read before the games
    days/<date>/standings.txt         optional snapshot
    days/<date>/transactions.txt      optional snapshot (merged across days)

load() fills the same database tables the API collector fills, so fact
sheets are built the same way from either source.
"""
import json
import re
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

NON_STARTING = {"BN", "IL", "IL+", "NA"}
PCT_SOURCE = {"FG%": "FGM/A", "FT%": "FTM/A"}
LOWER_IS_BETTER = {"TO"}
SEASON_START_MONTH = 8  # Aug-Dec belong to the season's first calendar year


class WebDataError(Exception):
    pass


# ---- checksum envelope ---------------------------------------------------

def _crc_line(lines):
    body = "\n".join(lines)
    return f"#crc={zlib.crc32(body.encode('utf-8')):08x} lines={len(lines)}"


def seal(lines):
    """Same envelope the browser script produces."""
    return "\n".join(lines) + "\n" + _crc_line(lines)


def unseal(text):
    """Verify the checksum; return (header fields, data lines)."""
    lines = text.replace("\r\n", "\n").rstrip("\n").split("\n")
    if len(lines) < 2 or not re.fullmatch(r"#crc=[0-9a-f]{8} lines=\d+", lines[-1]):
        raise WebDataError("no #crc line at the end: the text is incomplete")
    body, want = lines[:-1], lines[-1]
    got = _crc_line(body)
    if got != want:
        raise WebDataError(f"checksum mismatch (file says {want}, content gives {got}): copied incorrectly")
    head = body[0].split(" ")
    if not head[0].startswith("#nbl-") or len(head) < 2:
        raise WebDataError(f"unrecognised first line: {body[0]}")
    header = {"kind": head[0][5:], "version": head[1]}
    header.update(part.split("=", 1) for part in head[2:] if "=" in part)
    return header, body[1:]


def _open(text, kind):
    header, lines = unseal(text)
    if header["kind"] != kind:
        raise WebDataError(f"expected a {kind} file, got {header['kind']}")
    return header, [line.split("|") for line in lines]


def _values(columns, cells):
    if cells == ["-"]:
        return None
    if len(cells) != len(columns):
        raise WebDataError(f"{len(cells)} values for {len(columns)} columns: {'|'.join(cells)}")
    return dict(zip(columns, cells))


def _season_date(season, month, day):
    return date(season if month >= SEASON_START_MONTH else season + 1, month, day)


# ---- one stats day -------------------------------------------------------

def _player_info(info):
    m = re.match(r"^([A-Z]{2,3}) - ([A-Z,]+)\s*(.*)$", info)
    if m:
        return {"nba_team": m.group(1), "position": m.group(2), "status": m.group(3)}
    return {"nba_team": None, "position": None, "status": info}


def parse_day(text):
    header, rows = _open(text, "day")
    day = {"date": header.get("date"), "base": header.get("base"), "columns": [], "teams": [], "errors": []}
    team = None
    for row in rows:
        kind = row[0]
        if kind == "C":
            day["columns"] = [c for c in row[1:] if c]
        elif kind == "T":
            team = {"id": row[1], "name": row[2], "shown": row[3] if len(row) > 3 else "",
                    "players": [], "totals": None}
            day["teams"].append(team)
        elif kind == "P":
            team["players"].append({
                "slot": row[1], "pid": row[2], "name": row[3], **_player_info(row[4]),
                "stats": _values(day["columns"], row[5:]),
            })
        elif kind == "S":
            team["totals"] = _values(day["columns"], row[1:])
        elif kind == "E":
            day["errors"].append(" ".join(row[1:]))
    return day


def _add(total, value):
    """Add one cell ('27' or '10/18') to a running [a, b] total."""
    if "/" in value:
        made, attempted = value.split("/")
        total[0] += int(made)
        total[1] += int(attempted)
    else:
        total[0] += float(value)


def _show(total, like):
    if "/" in like:
        return f"{total[0]}/{total[1]}"
    return str(int(total[0])) if float(total[0]).is_integer() else str(total[0])


def _is_blank_line(stats):
    return all(v in ("0", "0/0") for v in stats.values())


def day_problems(day):
    """Reasons not to trust this day's file. Empty list = consistent."""
    problems = [f"browser reported: {e}" for e in day["errors"]]
    try:
        d = date.fromisoformat(day["date"])
        expected = f"{d:%a}, {d:%b} {d.day}"
    except (TypeError, ValueError):
        return problems + [f"bad date in header: {day['date']}"]
    for team in day["teams"]:
        if team["shown"] and team["shown"] != expected:
            problems.append(f"{team['name']}: page shows {team['shown']}, expected {expected}")
        totals = team["totals"]
        for col in day["columns"]:
            like = (totals or {}).get(col) or next(
                (p["stats"][col] for p in team["players"] if p["stats"]), "0")
            total = [0, 0]
            for p in team["players"]:
                if p["slot"] not in NON_STARTING and p["stats"]:
                    _add(total, p["stats"][col])
            ours = _show(total, like)
            yahoo = totals[col] if totals else _show([0, 0], like)
            if ours != yahoo:
                problems.append(f"{team['name']}: {col} started players sum to {ours}, Yahoo shows {yahoo}")
    return problems


# ---- other files ---------------------------------------------------------

def parse_week(text, season):
    header, rows = _open(text, "week")
    week = {"week": int(header["week"]), "start": None, "end": None, "columns": [], "matchups": [], "errors": []}
    for row in rows:
        kind = row[0]
        if kind == "W":
            ends = []
            for label in row[2:4]:
                m = re.match(r"^\w{3} (\d{1,2})/(\d{1,2})$", label)
                ends.append(_season_date(season, int(m.group(1)), int(m.group(2))).isoformat() if m else None)
            week["start"], week["end"] = ends
        elif kind == "C":
            week["columns"] = [c for c in row[1:] if c]
        elif kind == "M":
            wins = [int(v) if v.isdigit() else None for v in row[3:5]]
            week["matchups"].append({"teams": row[1:3], "wins": wins, "names": [], "stats": []})
        elif kind == "A":
            matchup = week["matchups"][-1]
            matchup["names"].append(row[2])
            matchup["stats"].append(_values(week["columns"], row[3:]) or {})
        elif kind == "E":
            week["errors"].append(" ".join(row[1:]))
    return week


def _int(value):
    m = re.search(r"\d+", value or "")
    return int(m.group()) if m else None


def parse_settings(text):
    _, rows = _open(text, "settings")
    raw = {row[1]: "|".join(row[2:]) for row in rows if row[0] == "K"}
    positions = {}
    for pos in [p.strip() for p in raw.get("Roster Positions", "").split(",") if p.strip()]:
        positions[pos] = positions.get(pos, 0) + 1
    playoff = re.search(r"Week (\d+)", raw.get("Playoffs", ""))
    return {
        "name": raw.get("League Name"),
        "num_teams": _int(raw.get("Max Teams")),
        "max_adds": _int(raw.get("Max Acquisitions for Entire Season")),
        "max_weekly_adds": _int(raw.get("Max Acquisitions per Week")),
        "playoff_start_week": int(playoff.group(1)) if playoff else None,
        "trade_end_date": raw.get("Trade End Date"),
        "categories": re.findall(r"\(([^)]+)\)", raw.get("Players Stat Categories", "")),
        "roster_positions": positions,
        "raw": raw,
    }


def parse_standings(text):
    _, rows = _open(text, "standings")
    out = []
    for row in rows:
        if row[0] != "R":
            continue
        wins, losses, ties = (int(n) for n in row[4].split("-"))
        out.append({
            "rank": _int(row[1]), "id": row[2], "name": row[3], "wins": wins, "losses": losses,
            "ties": ties, "pct": float(row[5]) if row[5] not in ("", "-") else None, "moves": _int(row[6]),
        })
    return out


def _move(detail, team):
    if detail == "Traded to":
        return {"action": "trade", "source_type": "team", "source_team": None,
                "destination_type": "team", "destination_team": team}
    if detail.startswith("To "):
        dest = "waivers" if "Waiver" in detail else "freeagents"
        return {"action": "drop", "source_type": "team", "source_team": team,
                "destination_type": dest, "destination_team": None}
    if detail in ("Free Agent", "Waiver", "Waivers"):
        source = "freeagents" if detail == "Free Agent" else "waivers"
        return {"action": "add", "source_type": source, "source_team": None,
                "destination_type": "team", "destination_team": team}
    return {"action": "other", "source_type": detail, "source_team": None,
            "destination_type": None, "destination_team": team}


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _page_time(when, season):
    """'Nov 8, 2:04 am' -> naive datetime in the season's calendar year."""
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{1,2}):(\d{2}) ([ap]m)", when)
    if not m or m.group(1) not in MONTHS:
        raise WebDataError(f"unreadable transaction time: {when!r}")
    month, day, hour, minute = MONTHS.index(m.group(1)) + 1, int(m.group(2)), int(m.group(3)), int(m.group(4))
    hour = hour % 12 + (12 if m.group(5) == "pm" else 0)
    year = _season_date(season, month, 1).year
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        raise WebDataError(f"impossible transaction time: {when!r}") from None


def parse_transactions(text, season, tz):
    """Moves grouped into transactions. Times on the page are in the viewer's
    time zone (`tz`) and carry no year, so the year comes from the season."""
    _, rows = _open(text, "transactions")
    zone = ZoneInfo(tz)
    groups = {}
    for row in rows:
        if row[0] != "X":
            continue
        _, _, when, team, pid, name, _info, detail = row[:8]
        stamp = int(_page_time(when, season).replace(tzinfo=zone).timestamp())
        move = {"pid": pid, "name": name, **_move(detail, team)}
        key = f"{stamp}:trade" if move["action"] == "trade" else f"{stamp}:{team}"
        tx = groups.setdefault(key, {"key": key, "timestamp": stamp, "team": team, "players": []})
        if not any(p["pid"] == pid and p["action"] == move["action"] for p in tx["players"]):
            tx["players"].append(move)
    for tx in groups.values():
        actions = {p["action"] for p in tx["players"]}
        if "trade" in actions:
            tx["type"] = "trade"
            teams = sorted({p["destination_team"] for p in tx["players"]})
            for p in tx["players"]:
                others = [t for t in teams if t != p["destination_team"]]
                p["source_team"] = others[0] if len(others) == 1 else None
        else:
            tx["type"] = "/".join(a for a in ("add", "drop", "other") if a in actions)
    return list(groups.values())


def parse_draft(text):
    _, rows = _open(text, "draft")
    return [
        {"pick": int(r[1]), "round": int(r[2]), "team": r[3], "pid": r[4], "name": r[5]}
        for r in rows if r[0] == "D"
    ]


# ---- what to collect next ------------------------------------------------

def _valid_day(directory, name="teams.txt"):
    try:
        return parse_day((directory / name).read_text(encoding="utf-8"))["date"] == directory.name
    except (OSError, WebDataError):
        return False


def plan(root, season, season_start, now, max_days=5, season_end=None):
    """Days and weeks the next browser run should fetch.

    A stats day is fetched once it is over in US Pacific time. Week files are
    cheap, so the current week, the next one (for pairings) and - for two days
    after it ends - the previous one (for stat corrections) are refreshed.

    "lineup" is the Pacific day now in progress: its lineups can be saved
    before the games (lineup-pre.txt) to see later who was moved at the last minute.
    """
    root = Path(root)
    start = date.fromisoformat(season_start)
    end = date.fromisoformat(season_end) if season_end else None
    today = now.astimezone(ZoneInfo("America/Los_Angeles")).date()
    target = today - timedelta(days=1)
    in_season = start <= today and (end is None or today <= end)
    wanted = in_season and not _valid_day(root / "days" / today.isoformat(), "lineup-pre.txt")
    common = {"yesterday": target.isoformat(), "lineup": today.isoformat() if wanted else None}
    known = []
    for path in sorted((root / "weeks").glob("week-*.txt")):
        try:
            w = parse_week(path.read_text(encoding="utf-8"), season)
        except (OSError, WebDataError):
            continue
        if w["start"] and w["end"]:
            known.append((w["week"], date.fromisoformat(w["start"]), date.fromisoformat(w["end"])))

    def week_of(day):
        for number, first, last in known:
            if first <= day <= last:
                return number
        later = [k for k in known if k[2] < day]
        if later:
            number, _, last = max(later)
            return number + 1 + ((day - last).days - 1) // 7
        first_sunday = start + timedelta(days=(6 - start.weekday()) % 7)
        return 1 if day <= first_sunday else 2 + ((day - first_sunday).days - 1) // 7

    if target < start:
        return {"days": [], "weeks": [1], "preseason": True, "behind": 0, **common}
    done = {d.name for d in (root / "days").glob("*") if d.is_dir() and _valid_day(d)}
    last = min(target, end) if end else target
    missing = [
        d.isoformat() for d in (start + timedelta(days=i) for i in range((last - start).days + 1))
        if d.isoformat() not in done
    ]
    days = missing[:max_days]
    weeks = {week_of(date.fromisoformat(d)) for d in days}
    weeks |= {week_of(target), week_of(target) + 1}
    weeks |= {week_of(d) for d in (target - timedelta(days=1), target - timedelta(days=2)) if d >= start}
    return {"days": days, "weeks": sorted(weeks), "preseason": False,
            "behind": len(missing) - len(days), **common}


# ---- database ------------------------------------------------------------

def _pct(value):
    """'182/365' -> '.499' the way Yahoo prints it."""
    made, attempted = value.split("/")
    if not (made.isdigit() and attempted.isdigit()) or not int(attempted):
        return "-"
    made, attempted = int(made), int(attempted)
    text = f"{made / attempted:.3f}"
    return text[1:] if text.startswith("0") else text


def _read(path, problems, label):
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        problems.append(f"{label}: {error}")
        return None


def _team_key(team_id):
    return f"t.{team_id}"


def _player_key(pid):
    return f"p.{pid}"


def _upsert_team(conn, team_id, name):
    conn.execute("INSERT OR REPLACE INTO teams VALUES (?,?,?,?)", (_team_key(team_id), int(team_id), name, None))


def load(conn, root, season, tz):
    """Fill an empty database from <root>. Returns problems found on the way:
    unreadable files (left out entirely) and days that do not add up."""
    root = Path(root)
    problems = []
    playoff_start = None

    conn.execute("INSERT OR REPLACE INTO meta VALUES ('season', ?)", (str(season),))
    settings_file = root / "league" / "settings.txt"
    if settings_file.exists():
        try:
            s = parse_settings(settings_file.read_text(encoding="utf-8"))
        except WebDataError as error:
            problems.append(f"settings: {error}")
        else:
            playoff_start = s["playoff_start_week"]
            for key in ("name", "num_teams", "max_adds", "max_weekly_adds", "playoff_start_week"):
                conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                             (key, None if s[key] is None else str(s[key])))
            position = 0
            for cat in s["categories"]:
                for name, display_only in ((PCT_SOURCE.get(cat), 1), (cat, 0)):
                    if name:
                        conn.execute("INSERT OR REPLACE INTO stat_categories VALUES (?,?,?,?,?,?)",
                                     (name, name, name, name in LOWER_IS_BETTER, display_only, position))
                        position += 1
            for pos, count in s["roster_positions"].items():
                conn.execute("INSERT OR REPLACE INTO roster_positions VALUES (?,?,?)",
                             (pos, count, pos not in NON_STARTING))

    for path in sorted((root / "weeks").glob("week-*.txt")):
        try:
            week = parse_week(path.read_text(encoding="utf-8"), season)
        except WebDataError as error:
            problems.append(f"{path.name}: {error}")
            continue
        problems += [f"{path.name}: browser reported: {e}" for e in week["errors"]]
        conn.execute("INSERT OR REPLACE INTO weeks VALUES (?,?,?)", (week["week"], week["start"], week["end"]))
        for idx, m in enumerate(week["matchups"]):
            a, b = (_team_key(t) for t in m["teams"])
            conn.execute(
                "INSERT OR REPLACE INTO matchups VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (week["week"], idx, week["start"], week["end"], "preevent",
                 bool(playoff_start and week["week"] >= playoff_start), 0, 0, None, a, b),
            )
            if None not in m["wins"]:
                conn.execute("INSERT OR REPLACE INTO matchup_scores VALUES (?,?,?,?)",
                             (week["week"], idx, m["wins"][0], m["wins"][1]))
            for team_id, name, stats in zip(m["teams"], m["names"], m["stats"]):
                _upsert_team(conn, team_id, name)
                values = dict(stats)
                for cat, source in PCT_SOURCE.items():
                    if source in values and cat not in values:
                        values[cat] = _pct(values[source])
                conn.executemany(
                    "INSERT OR REPLACE INTO matchup_stats VALUES (?,?,?,?)",
                    [(week["week"], _team_key(team_id), stat, value) for stat, value in values.items()],
                )

    transactions = {}
    for directory in sorted(p for p in (root / "days").glob("*") if p.is_dir()):
        day_name = directory.name
        teams_file = directory / "teams.txt"
        if teams_file.exists():
            try:
                day = parse_day(teams_file.read_text(encoding="utf-8"))
                if day["date"] != day_name:
                    raise WebDataError(f"file is for {day['date']}, folder is {day_name}")
            except WebDataError as error:
                problems.append(f"{day_name}: {error}")
            else:
                warnings = day_problems(day)
                problems += [f"{day_name}: {w}" for w in warnings]
                _load_day(conn, day, warnings)
        pre_file = directory / "lineup-pre.txt"
        if pre_file.exists():
            try:
                pre = parse_day(pre_file.read_text(encoding="utf-8"))
                if pre["date"] != day_name:
                    raise WebDataError(f"file is for {pre['date']}, folder is {day_name}")
            except WebDataError as error:
                problems.append(f"{day_name} lineup: {error}")
            else:
                for team in pre["teams"]:
                    for p in team["players"]:
                        conn.execute("INSERT OR IGNORE INTO players VALUES (?,?,?,?,?)",
                                     (_player_key(p["pid"]), p["name"], p["nba_team"], p["position"], ""))
                        conn.execute("INSERT OR REPLACE INTO lineup_pre VALUES (?,?,?,?)",
                                     (day_name, _team_key(team["id"]), _player_key(p["pid"]), p["slot"]))
        snapshot = directory / "standings.txt"
        if snapshot.exists():
            try:
                for r in parse_standings(snapshot.read_text(encoding="utf-8")):
                    conn.execute("INSERT OR REPLACE INTO standings VALUES (?,?,?,?,?,?,?,?)",
                                 (day_name, _team_key(r["id"]), r["rank"], r["wins"], r["losses"],
                                  r["ties"], r["pct"], None))
            except WebDataError as error:
                problems.append(f"{day_name} standings: {error}")
        moves = directory / "transactions.txt"
        if moves.exists():
            try:
                for tx in parse_transactions(moves.read_text(encoding="utf-8"), season, tz):
                    transactions[tx["key"]] = tx
            except WebDataError as error:
                problems.append(f"{day_name} transactions: {error}")

    for tx in transactions.values():
        conn.execute("INSERT OR REPLACE INTO transactions VALUES (?,?,?,?,?,?)",
                     (tx["key"], tx["type"], "successful", tx["timestamp"], None, None))
        for p in tx["players"]:
            conn.execute("INSERT OR IGNORE INTO players VALUES (?,?,?,?,?)",
                         (_player_key(p["pid"]), p["name"], None, None, ""))
            conn.execute(
                "INSERT OR REPLACE INTO transaction_players VALUES (?,?,?,?,?,?,?,?)",
                (tx["key"], _player_key(p["pid"]), p["name"], p["action"], p["source_type"],
                 _team_key(p["source_team"]) if p["source_team"] else None, p["destination_type"],
                 _team_key(p["destination_team"]) if p["destination_team"] else None),
            )

    draft_file = root / "league" / "draft.txt"
    if draft_file.exists():
        try:
            for d in parse_draft(draft_file.read_text(encoding="utf-8")):
                conn.execute("INSERT OR IGNORE INTO players VALUES (?,?,?,?,?)",
                             (_player_key(d["pid"]), d["name"], None, None, ""))
                conn.execute("INSERT OR REPLACE INTO draft_results VALUES (?,?,?,?)",
                             (d["pick"], d["round"], _team_key(d["team"]), _player_key(d["pid"])))
        except WebDataError as error:
            problems.append(f"draft: {error}")

    last_day = conn.execute("SELECT MAX(date) FROM run_log").fetchone()[0] or ""
    conn.execute("UPDATE matchups SET status='midevent' WHERE week_start<=?", (last_day,))
    conn.execute("UPDATE matchups SET status='postevent' WHERE week_end<=?", (last_day,))
    first = conn.execute("SELECT start FROM weeks WHERE week=1").fetchone()
    if first and first[0]:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('start_date', ?)", (first[0],))
    conn.commit()
    return problems


def _load_day(conn, day, warnings):
    d = day["date"]
    conn.execute("INSERT OR REPLACE INTO run_log VALUES (?,?,?,?,?)",
                 (d, 1, None, None, json.dumps(warnings, ensure_ascii=False)))
    for team in day["teams"]:
        _upsert_team(conn, team["id"], team["name"])
        for p in team["players"]:
            key = _player_key(p["pid"])
            conn.execute("INSERT OR REPLACE INTO players VALUES (?,?,?,?,?)",
                         (key, p["name"], p["nba_team"], p["position"], p["status"] or ""))
            conn.execute("INSERT OR REPLACE INTO roster_daily VALUES (?,?,?,?,?)",
                         (d, _team_key(team["id"]), key, p["slot"], p["status"] or ""))
            stats = p["stats"]
            played = bool(stats) and not _is_blank_line(stats)
            conn.execute("INSERT OR REPLACE INTO player_days VALUES (?,?,?)", (d, key, played))
            if stats:
                conn.executemany("INSERT OR REPLACE INTO player_stats VALUES (?,?,?,?)",
                                 [(d, key, stat, value) for stat, value in stats.items()])
