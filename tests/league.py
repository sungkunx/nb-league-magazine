"""Test helper: build a small league directly in the database."""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from nbl import db

PT = ZoneInfo("America/Los_Angeles")

# (stat_id, display_name, lower_is_better, is_display_only) in league order.
CATS = [
    ("9004003", "FGM/A", 0, 1), ("5", "FG%", 0, 0),
    ("9007006", "FTM/A", 0, 1), ("8", "FT%", 0, 0),
    ("10", "3PTM", 0, 0), ("12", "PTS", 0, 0), ("15", "REB", 0, 0), ("16", "AST", 0, 0),
    ("17", "ST", 0, 0), ("18", "BLK", 0, 0), ("19", "TO", 1, 0), ("27", "DD", 0, 0),
]
STAT_ID = {name: stat_id for stat_id, name, _, _ in CATS}
SCORING = [name for _, name, _, display in CATS if not display]  # the 10 categories
WEEKS = [(1, "2026-10-20", "2026-10-25"), (2, "2026-10-26", "2026-11-01"), (3, "2026-11-02", "2026-11-08")]


def epoch(pt_text):
    return int(datetime.fromisoformat(pt_text).replace(tzinfo=PT).timestamp())


class League:
    def __init__(self, teams=("Alpha", "Bravo", "Cobra", "Delta")):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(db.SCHEMA)
        c = self.conn
        c.executemany("INSERT INTO meta VALUES (?,?)", [
            ("name", "NB League"), ("season", "2026"), ("start_date", "2026-10-20"),
            ("max_weekly_adds", "4"), ("max_adds", "100"), ("playoff_start_week", "20"),
        ])
        c.executemany("INSERT INTO weeks VALUES (?,?,?)", WEEKS)
        c.executemany("INSERT INTO stat_categories VALUES (?,?,?,?,?,?)", [
            (stat_id, name, name, lower, display, i) for i, (stat_id, name, lower, display) in enumerate(CATS)
        ])
        c.executemany("INSERT INTO roster_positions VALUES (?,?,?)", [
            ("PG", 1, 1), ("SG", 1, 1), ("SF", 1, 1), ("PF", 1, 1), ("C", 1, 1), ("Util", 3, 1),
            ("BN", 2, 0), ("IL", 1, 0),
        ])
        for i, name in enumerate(teams, start=1):
            c.execute("INSERT INTO teams VALUES (?,?,?,?)", (name, i, name, f"mgr-{name}"))
        self._matchups = {}

    def close(self):
        self.conn.close()

    def days(self, *dates):
        """Mark stats days as collected."""
        for d in dates:
            self.conn.execute("INSERT OR REPLACE INTO run_log VALUES (?,?,?,?,?)", (d, 1, None, None, "[]"))
        return self

    def matchup(self, week, a, b, stats_a=None, stats_b=None, winners=None, status="postevent", playoffs=False):
        """stats_*: {category name: raw value}. winners: {category name: 'a' | 'b' | 'tie'}."""
        idx = self._matchups.setdefault(week, 0)
        self._matchups[week] += 1
        start, end = next((s, e) for w, s, e in WEEKS if w == week)
        self.conn.execute(
            "INSERT INTO matchups VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (week, idx, start, end, status, int(playoffs), 0, 0, None, a, b),
        )
        for team, stats in ((a, stats_a or {}), (b, stats_b or {})):
            for name, value in stats.items():
                self.conn.execute(
                    "INSERT INTO matchup_stats VALUES (?,?,?,?)", (week, team, STAT_ID[name], str(value))
                )
        for name, who in (winners or {}).items():
            winner = {"a": a, "b": b, "tie": None}[who]
            self.conn.execute(
                "INSERT INTO matchup_winners VALUES (?,?,?,?,?)",
                (week, idx, STAT_ID[name], winner, int(who == "tie")),
            )
        return self

    def result(self, week, a, b, wins_a, wins_b, ties=0, **kwargs):
        """A matchup decided wins_a-wins_b-ties across the 10 categories."""
        assert wins_a + wins_b + ties == len(SCORING)
        order = ["a"] * wins_a + ["b"] * wins_b + ["tie"] * ties
        return self.matchup(week, a, b, winners=dict(zip(SCORING, order)), **kwargs)

    def play(self, date, team, player, slot, **stats):
        """One player on one team's roster for one day. Stats by category name,
        with FG="8/15" and FT="4/5" for shooting. No stats = did not play."""
        key = f"p:{player}"
        c = self.conn
        c.execute("INSERT OR REPLACE INTO players VALUES (?,?,?,?,?)", (key, player, "NBA", "G", ""))
        c.execute("INSERT OR REPLACE INTO roster_daily VALUES (?,?,?,?,?)", (date, team, key, slot, ""))
        c.execute("INSERT OR REPLACE INTO player_days VALUES (?,?,?)", (date, key, int(bool(stats))))
        raw = {name: "-" for _, name, _, _ in CATS}
        raw["FGM/A"] = raw["FTM/A"] = "-/-"
        for name, value in stats.items():
            raw[{"FG": "FGM/A", "FT": "FTM/A"}.get(name, name)] = str(value)
        for name, value in raw.items():
            c.execute("INSERT OR REPLACE INTO player_stats VALUES (?,?,?,?)", (date, key, STAT_ID[name], value))
        return self

    def tx(self, key, pt_time, kind, moves, status="successful"):
        """moves: list of (player, action, source, destination); a team name,
        or 'freeagents' / 'waivers'."""
        teams = {r[0] for r in self.conn.execute("SELECT team_key FROM teams")}
        self.conn.execute(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?)", (key, kind, status, epoch(pt_time), None, None)
        )
        for player, action, source, dest in moves:
            self.conn.execute(
                "INSERT INTO transaction_players VALUES (?,?,?,?,?,?,?,?)",
                (key, f"p:{player}", player, action,
                 "team" if source in teams else source, source if source in teams else None,
                 "team" if dest in teams else dest, dest if dest in teams else None),
            )
        return self

    def draft(self, pick, rnd, team, player, adp=None, **prev):
        """One draft pick, with Yahoo's average pick and last season's totals."""
        key = f"p:{player}"
        c = self.conn
        c.execute("INSERT OR REPLACE INTO players VALUES (?,?,?,?,?)", (key, player, "NBA", "G", ""))
        c.execute("INSERT INTO draft_results VALUES (?,?,?,?)", (pick, rnd, team, key))
        c.execute("INSERT INTO draft_analysis VALUES (?,?,?,?)", (key, adp, None, None))
        for name, value in prev.items():
            stat = STAT_ID[{"FG": "FGM/A", "FT": "FTM/A"}.get(name, name)]
            c.execute("INSERT INTO prev_season_stats VALUES (?,?,?)", (key, stat, str(value)))
        return self

    def pre(self, date, team, player, slot):
        """The slot a player was in when the lineup was looked at before the games."""
        self.conn.execute("INSERT OR REPLACE INTO lineup_pre VALUES (?,?,?,?)", (date, team, f"p:{player}", slot))
        return self
