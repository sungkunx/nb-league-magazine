"""SQLite view of everything in the raw store.

The database is disposable: rebuild() recreates it from the raw responses, so
a parsing fix never needs the data to be collected again.
"""
import json
import sqlite3
from pathlib import Path

from . import parse

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE weeks(week INT PRIMARY KEY, start TEXT, end TEXT);
CREATE TABLE stat_categories(stat_id TEXT PRIMARY KEY, name TEXT, display_name TEXT,
    lower_is_better INT, is_display_only INT, position INT);
CREATE TABLE roster_positions(position TEXT PRIMARY KEY, count INT, is_starting INT);
CREATE TABLE teams(team_key TEXT PRIMARY KEY, team_id INT, name TEXT, manager TEXT);
CREATE TABLE players(player_key TEXT PRIMARY KEY, name TEXT, nba_team TEXT, position TEXT, status TEXT);
CREATE TABLE roster_daily(date TEXT, team_key TEXT, player_key TEXT, slot TEXT, status TEXT,
    PRIMARY KEY(date, team_key, player_key));
CREATE TABLE lineup_pre(date TEXT, team_key TEXT, player_key TEXT, slot TEXT,
    PRIMARY KEY(date, team_key, player_key));
CREATE TABLE player_days(date TEXT, player_key TEXT, played INT, PRIMARY KEY(date, player_key));
CREATE TABLE player_stats(date TEXT, player_key TEXT, stat_id TEXT, value TEXT,
    PRIMARY KEY(date, player_key, stat_id));
CREATE TABLE matchups(week INT, idx INT, week_start TEXT, week_end TEXT, status TEXT,
    is_playoffs INT, is_consolation INT, is_tied INT, winner_team_key TEXT,
    team_a TEXT, team_b TEXT, PRIMARY KEY(week, idx));
CREATE TABLE matchup_stats(week INT, team_key TEXT, stat_id TEXT, value TEXT,
    PRIMARY KEY(week, team_key, stat_id));
CREATE TABLE matchup_winners(week INT, idx INT, stat_id TEXT, winner_team_key TEXT, is_tied INT,
    PRIMARY KEY(week, idx, stat_id));
CREATE TABLE matchup_scores(week INT, idx INT, wins_a INT, wins_b INT, PRIMARY KEY(week, idx));
CREATE TABLE standings(date TEXT, team_key TEXT, rank INT, wins INT, losses INT, ties INT,
    pct REAL, playoff_seed INT, PRIMARY KEY(date, team_key));
CREATE TABLE transactions(transaction_key TEXT PRIMARY KEY, type TEXT, status TEXT,
    timestamp INT, trader_team_key TEXT, tradee_team_key TEXT);
CREATE TABLE transaction_players(transaction_key TEXT, player_key TEXT, name TEXT, action TEXT,
    source_type TEXT, source_team_key TEXT, destination_type TEXT, destination_team_key TEXT,
    PRIMARY KEY(transaction_key, player_key));
CREATE TABLE draft_results(pick INT PRIMARY KEY, round INT, team_key TEXT, player_key TEXT);
CREATE TABLE draft_analysis(player_key TEXT PRIMARY KEY, average_pick REAL, average_round REAL,
    percent_drafted REAL);
CREATE TABLE prev_season_stats(player_key TEXT, stat_id TEXT, value TEXT,
    PRIMARY KEY(player_key, stat_id));
CREATE TABLE run_log(date TEXT PRIMARY KEY, live INT, fetched_at TEXT, corrected_at TEXT, warnings TEXT);
"""


def meta(conn):
    return dict(conn.execute("SELECT key, value FROM meta"))


def _root(store, rel):
    return parse.xml_root(store.load(rel))


def _name(rel):
    return rel.rsplit("/", 1)[1]


def _player(conn, p, replace):
    """Roster rows carry the freshest team/status, so they overwrite; other
    sources only fill in players we have not seen on a roster."""
    verb = "REPLACE" if replace else "IGNORE"
    conn.execute(
        f"INSERT OR {verb} INTO players VALUES (?,?,?,?,?)",
        (p["player_key"], p["name"], p["nba_team"], p["position"], p["status"]),
    )


def _load_league(conn, store):
    if store.exists("league/settings.xml"):
        root = _root(store, "league/settings.xml")
        values = {**parse.league_meta(root), **parse.settings(root)}
        conn.executemany(
            "INSERT INTO meta VALUES (?,?)",
            [(k, None if v is None else str(v)) for k, v in values.items()],
        )
        conn.executemany(
            "INSERT INTO stat_categories VALUES (?,?,?,?,?,?)",
            [
                (c["stat_id"], c["name"], c["display_name"], c["lower_is_better"], c["is_display_only"], i)
                for i, c in enumerate(parse.stat_categories(root))
            ],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO roster_positions VALUES (?,?,?)",
            [(p["position"], p["count"], p["is_starting"]) for p in parse.roster_positions(root)],
        )
    if store.exists("league/game_weeks.xml"):
        conn.executemany(
            "INSERT INTO weeks VALUES (?,?,?)",
            [(w["week"], w["start"], w["end"]) for w in parse.game_weeks(_root(store, "league/game_weeks.xml"))],
        )
    if store.exists("league/teams.xml"):
        conn.executemany(
            "INSERT INTO teams VALUES (?,?,?,?)",
            [
                (t["team_key"], t["team_id"], t["name"], t["manager"])
                for t in parse.teams(_root(store, "league/teams.xml"))
            ],
        )


def _load_draft(conn, store):
    for rel in store.files("league"):
        name = _name(rel)
        if name == "draftresults.xml":
            conn.executemany(
                "INSERT INTO draft_results VALUES (?,?,?,?)",
                [(d["pick"], d["round"], d["team_key"], d["player_key"])
                 for d in parse.draft_results(_root(store, rel))],
            )
        elif name.startswith("draft_players_"):
            for p in parse.players_meta(_root(store, rel)):
                _player(conn, p, replace=False)
                conn.execute(
                    "INSERT OR REPLACE INTO draft_analysis VALUES (?,?,?,?)",
                    (p["player_key"], p["average_pick"], p["average_round"], p["percent_drafted"]),
                )
        elif name.startswith("draft_prev_stats_"):
            for p in parse.player_stats(_root(store, rel)):
                _player(conn, p, replace=False)
                conn.executemany(
                    "INSERT OR REPLACE INTO prev_season_stats VALUES (?,?,?)",
                    [(p["player_key"], stat_id, value) for stat_id, value in p["stats"].items()],
                )


def _load_scoreboards(conn, store):
    for rel in store.files("weeks"):
        for idx, m in enumerate(parse.scoreboard(_root(store, rel))):
            keys = [t["team_key"] for t in m["teams"]]
            conn.execute(
                "INSERT OR REPLACE INTO matchups VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (m["week"], idx, m["week_start"], m["week_end"], m["status"], m["is_playoffs"],
                 m["is_consolation"], m["is_tied"], m["winner_team_key"], keys[0], keys[1]),
            )
            for team in m["teams"]:
                conn.executemany(
                    "INSERT OR REPLACE INTO matchup_stats VALUES (?,?,?,?)",
                    [(m["week"], team["team_key"], stat_id, value) for stat_id, value in team["stats"].items()],
                )
            conn.executemany(
                "INSERT OR REPLACE INTO matchup_winners VALUES (?,?,?,?,?)",
                [(m["week"], idx, w["stat_id"], w["winner_team_key"], w["is_tied"]) for w in m["stat_winners"]],
            )


def _load_day(conn, store, day):
    info = store.run_info(day)
    conn.execute(
        "INSERT INTO run_log VALUES (?,?,?,?,?)",
        (day, bool(info.get("live")), info.get("fetched_at"), info.get("corrected_at"),
         json.dumps(info.get("warnings", []), ensure_ascii=False)),
    )
    for rel in store.day_files(day):
        name = _name(rel)
        root = _root(store, rel)
        if name.startswith("roster_"):
            roster = parse.roster(root)
            for p in roster["players"]:
                _player(conn, p, replace=True)
                conn.execute(
                    "INSERT OR REPLACE INTO roster_daily VALUES (?,?,?,?,?)",
                    (day, roster["team_key"], p["player_key"], p["slot"], p["status"]),
                )
        elif name.startswith("stats_"):
            for p in parse.player_stats(root):
                conn.execute(
                    "INSERT OR REPLACE INTO player_days VALUES (?,?,?)", (day, p["player_key"], p["played"])
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO player_stats VALUES (?,?,?,?)",
                    [(day, p["player_key"], stat_id, value) for stat_id, value in p["stats"].items()],
                )
        elif name == "standings.xml":
            conn.executemany(
                "INSERT OR REPLACE INTO standings VALUES (?,?,?,?,?,?,?,?)",
                [(day, s["team_key"], s["rank"], s["wins"], s["losses"], s["ties"], s["pct"], s["playoff_seed"])
                 for s in parse.standings(root)],
            )
        elif name == "transactions.xml":
            for t in parse.transactions(root):
                conn.execute(
                    "INSERT OR REPLACE INTO transactions VALUES (?,?,?,?,?,?)",
                    (t["transaction_key"], t["type"], t["status"], t["timestamp"],
                     t["trader_team_key"], t["tradee_team_key"]),
                )
                for p in t["players"]:
                    _player(conn, p, replace=False)
                    conn.execute(
                        "INSERT OR REPLACE INTO transaction_players VALUES (?,?,?,?,?,?,?,?)",
                        (t["transaction_key"], p["player_key"], p["name"], p["action"], p["source_type"],
                         p["source_team_key"], p["destination_type"], p["destination_team_key"]),
                    )


def rebuild(store, path=":memory:"):
    """Create a fresh database from the raw store and return the connection."""
    if path != ":memory:":
        Path(path).unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _load_league(conn, store)
    for day in store.done_dates():  # ascending, so later days win on conflicts
        _load_day(conn, store, day)
    _load_draft(conn, store)
    _load_scoreboards(conn, store)
    conn.commit()
    return conn
