import tempfile
import unittest
from pathlib import Path

from nbl import db
from nbl.store import RawStore
from tests.fakes import fixture, roster_xml

T1, T2 = "470.l.80126.t.1", "470.l.80126.t.2"
DAY = "2026-10-21"


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class RebuildTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = RawStore(Path(tmp.name))
        s = self.store
        s.save("league/settings.xml", fixture("settings.xml"))
        s.save("league/game_weeks.xml", fixture("game_weeks.xml"))
        s.save("league/teams.xml", fixture("teams.xml"))
        s.save("league/draftresults.xml", fixture("draftresults.xml"))
        s.save("league/draft_players_01.xml", fixture("players_draft.xml"))
        s.save("weeks/scoreboard_w01.xml", fixture("scoreboard_w1.xml"))
        s.save(f"days/{DAY}/roster_t1.xml", fixture("roster_t1.xml"))
        s.save(f"days/{DAY}/stats_01.xml", fixture("stats_01.xml"))
        s.save(f"days/{DAY}/standings.xml", fixture("standings.xml"))
        s.save(f"days/{DAY}/transactions.xml", fixture("transactions.xml"))
        s.mark_done(DAY, {"live": True, "fetched_at": "2026-10-22T07:05:00+00:00", "warnings": ["w1"]})
        self.conn = self.rebuild()

    def rebuild(self, store=None, path=":memory:"):
        conn = db.rebuild(store or self.store, path)
        self.addCleanup(conn.close)
        return conn

    def test_league_meta_and_settings_are_queryable(self):
        meta = db.meta(self.conn)
        self.assertEqual(meta["name"], "NB League 2026")
        self.assertEqual(meta["start_date"], "2026-10-20")
        self.assertEqual(meta["max_weekly_adds"], "4")
        self.assertEqual(meta["playoff_start_week"], "20")

    def test_stat_categories_keep_league_order(self):
        rows = self.conn.execute(
            "SELECT display_name, lower_is_better, is_display_only FROM stat_categories ORDER BY position"
        ).fetchall()
        self.assertEqual([tuple(r) for r in rows], [
            ("FGM/A", 0, 1), ("FG%", 0, 0), ("PTS", 0, 0), ("TO", 1, 0),
        ])

    def test_weeks_and_teams(self):
        self.assertEqual(count(self.conn, "weeks"), 2)
        row = one(self.conn, "SELECT name, manager FROM teams WHERE team_key=?", T1)
        self.assertEqual(tuple(row), ("Cho", "Chochi"))

    def test_roster_rows_record_the_slot_for_that_day(self):
        row = one(self.conn, """SELECT r.slot, r.team_key, p.name, p.nba_team FROM roster_daily r
                                JOIN players p USING(player_key)
                                WHERE r.date=? AND p.name='Nikola Jokic'""", DAY)
        self.assertEqual(tuple(row), ("C", T1, "Nikola Jokic", "DEN"))
        self.assertEqual(count(self.conn, "roster_daily"), 3)

    def test_roster_rows_use_the_folder_day_not_the_date_inside_the_file(self):
        self.store.save("days/2026-10-22/roster_t1.xml", roster_xml(T1, "1999-01-01", [("470.p.9", "X", "PG")]))
        self.store.mark_done("2026-10-22", {"live": True})
        conn = self.rebuild()
        self.assertEqual(one(conn, "SELECT date FROM roster_daily WHERE player_key='470.p.9'")[0], "2026-10-22")

    def test_player_stats_keep_raw_values_and_played_flag(self):
        value = one(self.conn, """SELECT value FROM player_stats
                                  WHERE date=? AND player_key='470.p.5352' AND stat_id='12'""", DAY)[0]
        self.assertEqual(value, "27")
        played = dict(self.conn.execute("SELECT player_key, played FROM player_days WHERE date=?", (DAY,)))
        self.assertEqual(played, {"470.p.5352": 1, "470.p.6030": 0, "470.p.4563": 1})

    def test_matchup_rows(self):
        m = one(self.conn, "SELECT * FROM matchups WHERE week=1")
        self.assertEqual((m["team_a"], m["team_b"], m["status"]), (T1, T2, "postevent"))
        self.assertEqual(m["winner_team_key"], T2)
        self.assertEqual(
            one(self.conn, "SELECT value FROM matchup_stats WHERE week=1 AND team_key=? AND stat_id='5'", T2)[0],
            ".500",
        )
        winners = {
            r["stat_id"]: (r["winner_team_key"], r["is_tied"])
            for r in self.conn.execute("SELECT * FROM matchup_winners WHERE week=1")
        }
        self.assertEqual(winners, {"5": (T2, 0), "12": (None, 1), "19": (T1, 0)})

    def test_standings_snapshot_is_dated_by_its_folder(self):
        row = one(self.conn, "SELECT rank, wins, ties, pct FROM standings WHERE date=? AND team_key=?", DAY, T2)
        self.assertEqual(tuple(row), (1, 6, 1, 0.65))

    def test_transactions_and_their_players(self):
        self.assertEqual(count(self.conn, "transactions"), 2)
        rows = self.conn.execute(
            "SELECT name, action FROM transaction_players WHERE transaction_key='470.l.80126.tr.2' ORDER BY action"
        ).fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Dylan Harper", "add"), ("Kawhi Leonard", "drop")])

    def test_transactions_from_different_days_are_merged(self):
        only_trade = fixture("transactions.xml").replace(b"470.l.80126.tr.2", b"470.l.80126.tr.9")
        self.store.save("days/2026-10-22/transactions.xml", only_trade)
        self.store.mark_done("2026-10-22", {"live": True})
        conn = self.rebuild()
        keys = [r[0] for r in conn.execute("SELECT transaction_key FROM transactions ORDER BY 1")]
        self.assertEqual(keys, ["470.l.80126.tr.2", "470.l.80126.tr.3", "470.l.80126.tr.9"])

    def test_draft_results_and_average_pick(self):
        row = one(self.conn, """SELECT d.pick, d.team_key, p.name, a.average_pick FROM draft_results d
                                JOIN players p USING(player_key) JOIN draft_analysis a USING(player_key)
                                WHERE d.pick=1""")
        self.assertEqual(tuple(row), (1, T2, "Nikola Jokic", 1.2))

    def test_run_log_keeps_warnings(self):
        row = one(self.conn, "SELECT live, warnings FROM run_log WHERE date=?", DAY)
        self.assertEqual(tuple(row), (1, '["w1"]'))

    def test_unfinished_day_is_ignored(self):
        self.store.save("days/2026-10-23/roster_t1.xml", roster_xml(T1, "2026-10-23", [("470.p.9", "X", "PG")]))
        conn = self.rebuild()  # no mark_done for 10-23
        self.assertIsNone(one(conn, "SELECT 1 FROM roster_daily WHERE date='2026-10-23'"))

    def test_rebuild_to_a_file_replaces_the_old_database(self):
        path = Path(self.store.root) / "league.db"
        db.rebuild(self.store, path).close()
        conn = self.rebuild(path=path)
        self.assertEqual(count(conn, "roster_daily"), 3)
        self.assertEqual(count(conn, "transactions"), 2)

    def test_rebuild_works_before_anything_but_settings_exists(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = RawStore(Path(tmp.name))
        store.save("league/settings.xml", fixture("settings.xml"))
        conn = self.rebuild(store)
        self.assertEqual(count(conn, "teams"), 0)
        self.assertEqual(db.meta(conn)["season"], "2026")


if __name__ == "__main__":
    unittest.main()
