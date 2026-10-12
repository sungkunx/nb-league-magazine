import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nbl import db, factsheet, web
from tests.league import epoch

FIX = Path(__file__).parent / "fixtures" / "web"
REAL_WEEK = Path(__file__).parent.parent / "data" / "2025" / "web"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


class SealTests(unittest.TestCase):
    def test_real_browser_output_passes_the_checksum(self):
        header, lines = web.unseal(text("week-03.txt"))
        self.assertEqual(header, {"kind": "week", "version": "v2", "base": "/2025/nba/48698", "week": "3"})
        self.assertEqual(lines[0], "W|3|Mon 11/3|Sun 11/9|7")
        self.assertEqual(len(lines), 8)

    def test_non_ascii_names_checksum_the_same_as_in_the_browser(self):
        _, lines = web.unseal(text("day-2025-11-03.txt"))
        self.assertTrue(any("Luka Dončić" in l for l in lines))

    def test_one_changed_digit_is_caught(self):
        damaged = text("week-03.txt").replace("182/365", "182/366")
        with self.assertRaises(web.WebDataError) as ctx:
            web.unseal(damaged)
        self.assertIn("checksum", str(ctx.exception))

    def test_missing_line_is_caught(self):
        lines = text("week-03.txt").split("\n")
        del lines[4]
        with self.assertRaises(web.WebDataError):
            web.unseal("\n".join(lines))

    def test_missing_checksum_line_is_caught(self):
        with self.assertRaises(web.WebDataError) as ctx:
            web.unseal("#nbl-week v2 week=3\nW|3|Mon 11/3|Sun 11/9|7\n")
        self.assertIn("#crc", str(ctx.exception))

    def test_trailing_newlines_and_windows_line_ends_are_tolerated(self):
        web.unseal(text("week-03.txt").rstrip("\n") + "\n\n")
        web.unseal(text("week-03.txt").replace("\n", "\r\n"))

    def test_seal_produces_what_the_browser_produced(self):
        original = text("week-03.txt").rstrip("\n")
        self.assertEqual(web.seal(original.split("\n")[:-1]), original)


class DayTests(unittest.TestCase):
    def setUp(self):
        self.day = web.parse_day(text("day-2025-11-03.txt"))

    def test_day_header(self):
        self.assertEqual(self.day["date"], "2025-11-03")
        self.assertEqual(self.day["columns"], ["FGM/A", "FTM/A", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO", "DD"])
        self.assertEqual([t["id"] for t in self.day["teams"]], ["4", "11", "3", "15"])
        self.assertEqual(self.day["teams"][0]["name"], "Cho")

    def test_player_line_maps_values_to_columns(self):
        brunson = self.day["teams"][0]["players"][0]
        self.assertEqual((brunson["slot"], brunson["pid"], brunson["name"]), ("PG", "6044", "Jalen Brunson"))
        self.assertEqual(brunson["stats"]["FGM/A"], "6/17")
        self.assertEqual(brunson["stats"]["PTS"], "16")
        self.assertEqual(brunson["stats"]["DD"], "0")

    def test_dash_means_no_line_that_day(self):
        mobley = self.day["teams"][0]["players"][3]
        self.assertEqual(mobley["name"], "Evan Mobley")
        self.assertIsNone(mobley["stats"])

    def test_yahoo_starting_totals_are_kept(self):
        self.assertEqual(self.day["teams"][0]["totals"]["PTS"], "91")
        self.assertEqual(self.day["teams"][0]["totals"]["FGM/A"], "37/75")

    def test_real_day_has_no_problems(self):
        self.assertEqual(web.day_problems(self.day), [])

    def test_started_players_not_adding_up_to_yahoo_total_is_a_problem(self):
        lines = text("day-2025-11-03.txt").rstrip("\n").split("\n")[:-1]
        lines = [l.replace("S|37/75|10/15|7|91|", "S|37/75|10/15|7|95|") for l in lines]
        problems = web.day_problems(web.parse_day(web.seal(lines)))
        self.assertEqual(len(problems), 1)
        self.assertIn("Cho", problems[0])
        self.assertIn("PTS", problems[0])
        self.assertIn("91", problems[0])
        self.assertIn("95", problems[0])

    def test_page_showing_a_different_date_is_a_problem(self):
        lines = text("day-2025-11-03.txt").rstrip("\n").split("\n")[:-1]
        lines = [l.replace("T|4|Cho|Mon, Nov 3", "T|4|Cho|Tue, Nov 4") for l in lines]
        problems = web.day_problems(web.parse_day(web.seal(lines)))
        self.assertTrue(any("Tue, Nov 4" in p for p in problems))

    def test_error_lines_from_the_browser_are_problems(self):
        lines = text("day-2025-11-03.txt").rstrip("\n").split("\n")[:-1] + ["E|9|no roster table"]
        problems = web.day_problems(web.parse_day(web.seal(lines)))
        self.assertTrue(any("no roster table" in p for p in problems))

    def test_player_info_gives_nba_team_and_positions_when_present(self):
        lines = ["#nbl-day v2 base=/nba/80126 date=2026-10-21 teams=1", "C|PTS",
                 "T|4|Cho|Wed, Oct 21", "P|PG|6044|Jalen Brunson|NYK - PG GTD|16", "S|16"]
        player = web.parse_day(web.seal(lines))["teams"][0]["players"][0]
        self.assertEqual((player["nba_team"], player["position"], player["status"]), ("NYK", "PG", "GTD"))


class OtherFileTests(unittest.TestCase):
    def test_week_gives_dates_matchups_and_totals(self):
        week = web.parse_week(text("week-03.txt"), season=2025)
        self.assertEqual((week["week"], week["start"], week["end"]), (3, "2025-11-03", "2025-11-09"))
        self.assertEqual(week["matchups"][0]["teams"], ["4", "11"])
        self.assertEqual(week["matchups"][0]["wins"], [5, 5])
        self.assertEqual(week["matchups"][0]["stats"][0]["FGM/A"], "182/365")
        self.assertEqual(week["matchups"][0]["names"], ["Cho", "Kharami"])

    def test_week_in_january_belongs_to_the_next_calendar_year(self):
        lines = ["#nbl-week v2 base=/nba/80126 week=12", "W|12|Mon 12/28|Sun 1/3|7", "C|PTS"]
        week = web.parse_week(web.seal(lines), season=2026)
        self.assertEqual((week["start"], week["end"]), ("2026-12-28", "2027-01-03"))

    def test_older_week_format_with_percent_columns_still_parses(self):
        week = web.parse_week(text("week-03-v1.txt"), season=2025)
        self.assertEqual(len(week["matchups"]), 8)
        self.assertEqual(week["matchups"][0]["wins"], [1, 9])

    def test_settings(self):
        s = web.parse_settings(text("settings.txt"))
        self.assertEqual(s["name"], "NB League 2026")
        self.assertEqual(s["max_weekly_adds"], 4)
        self.assertEqual(s["max_adds"], 100)
        self.assertEqual(s["playoff_start_week"], 21)
        self.assertEqual(s["num_teams"], 16)
        self.assertEqual(s["categories"], ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO", "DD"])
        self.assertEqual(s["roster_positions"], {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1, "Util": 3, "BN": 2, "IL": 1})

    def test_standings(self):
        rows = web.parse_standings(text("standings.txt"))
        self.assertEqual(rows[0], {"rank": 1, "id": "1", "name": "Baesen", "wins": 117, "losses": 76,
                                   "ties": 7, "pct": 0.603, "moves": 82})
        self.assertEqual(len(rows), 16)

    def tx(self, *lines):
        return web.parse_transactions(
            web.seal(["#nbl-transactions v2 base=/2025/nba/48698 pages=1", *lines]),
            season=2025, tz="Asia/Seoul",
        )

    def test_add_and_drop_at_the_same_time_are_one_transaction(self):
        (t,) = self.tx(
            "X|0.4|Nov 8, 2:04 am|4|5013|Harrison Barnes|SAS - SF,PF|Free Agent",
            "X|0.4|Nov 8, 2:04 am|4|6236|Terance Mann|BKN - SG,SF|To Waivers",
        )
        self.assertEqual(t["type"], "add/drop")
        self.assertEqual(t["timestamp"], epoch("2025-11-07T09:04"))  # 02:04 in Seoul = 09:04 Pacific the day before
        self.assertEqual(t["players"], [
            {"pid": "5013", "name": "Harrison Barnes", "action": "add", "source_type": "freeagents",
             "source_team": None, "destination_type": "team", "destination_team": "4"},
            {"pid": "6236", "name": "Terance Mann", "action": "drop", "source_type": "team",
             "source_team": "4", "destination_type": "waivers", "destination_team": None},
        ])

    def test_pair_split_across_a_page_break_is_still_one_transaction(self):
        txs = self.tx(
            "X|0.24|Mar 27, 7:56 pm|1|6413|Tyrese Maxey|PHI - PG|Free Agent",
            "X|1.0|Mar 27, 7:56 pm|1|5832|John Collins|DET - PF,C|To Waivers",
        )
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0]["type"], "add/drop")

    def test_waiver_claim_is_an_add_from_waivers(self):
        (t,) = self.tx("X|1.2|Mar 26, 4:19 am|15|4614|DeMar DeRozan|DEN - SF,PF|Waiver")
        self.assertEqual(t["type"], "add")
        self.assertEqual(t["players"][0]["source_type"], "waivers")

    def test_spring_dates_belong_to_the_year_after_the_season_starts(self):
        (t,) = self.tx("X|0.0|Apr 4, 8:41 pm|1|10469|Nique Clifford|SAC - SG,SF|Free Agent")
        self.assertEqual(t["timestamp"], epoch("2026-04-04T04:41"))

    def test_leap_day_and_noon_and_midnight_times(self):
        lines = ["#nbl-transactions v2 base=/nba/1 pages=1",
                 "X|0.0|Feb 29, 12:05 am|1|1|A|X - C|Free Agent",
                 "X|0.1|Feb 29, 12:05 pm|2|2|B|X - C|Free Agent"]
        a, b = web.parse_transactions(web.seal(lines), season=2027, tz="Asia/Seoul")
        self.assertEqual(b["timestamp"] - a["timestamp"], 12 * 3600)
        self.assertEqual(a["timestamp"], epoch("2028-02-28T07:05"))  # 00:05 in Seoul

    def test_unreadable_time_is_an_error(self):
        with self.assertRaises(web.WebDataError):
            self.tx("X|0.0|sometime|1|1|A|X - C|Free Agent")

    def test_trade_rows_are_paired_so_each_player_has_a_source_team(self):
        (t,) = self.tx(
            "X|0.0|Feb 7, 4:14 am|8|5197|Rudy Gobert|MIN - C|Traded to",
            "X|0.1|Feb 7, 4:14 am|2|6016|Trae Young|ATL - PG|Traded to",
        )
        self.assertEqual(t["type"], "trade")
        moves = {p["name"]: (p["source_team"], p["destination_team"]) for p in t["players"]}
        self.assertEqual(moves, {"Rudy Gobert": ("2", "8"), "Trae Young": ("8", "2")})

    def test_same_move_gets_the_same_key_in_every_snapshot(self):
        a = self.tx("X|0.3|Nov 8, 2:04 am|4|5013|Harrison Barnes|SAS - SF,PF|Free Agent")
        b = self.tx("X|7.11|Nov 8, 2:04 am|4|5013|Harrison Barnes|SAS - SF,PF|Free Agent")
        self.assertEqual(a[0]["key"], b[0]["key"])

    def test_draft(self):
        picks = web.parse_draft(web.seal([
            "#nbl-draft v1 base=/2025/nba/48698",
            "D|1|1|15|5352|Nikola Jokić|TERIE-DD-1",
            "D|17|2|10|5294|Joel Embiid|CHAN",
        ]))
        self.assertEqual(picks[1], {"pick": 17, "round": 2, "team": "10", "pid": "5294", "name": "Joel Embiid"})


class LoadTests(unittest.TestCase):
    """The whole real week 3 of last season (two matchups), end to end."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(db.SCHEMA)
        self.addCleanup(self.conn.close)
        self.problems = web.load(self.conn, REAL_WEEK, season=2025, tz="Asia/Seoul")
        self.sheet = factsheet.build_week(self.conn, 3)

    def test_real_week_loads_without_problems(self):
        self.assertEqual(self.problems, [])

    def test_our_sums_equal_yahoos_official_weekly_totals(self):
        self.assertEqual(self.sheet["checks"], [])

    def test_week_is_complete_and_dated(self):
        meta = self.sheet["meta"]
        self.assertEqual((meta["week_start"], meta["week_end"], meta["through"]), ("2025-11-03", "2025-11-09", "2025-11-09"))
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["league"], "NB League 2026")
        self.assertEqual(meta["season"], "2025-26")

    def test_matchup_score_and_categories(self):
        m = self.sheet["matchups"][0]
        self.assertEqual(m["teams"], ["Cho", "Kharami"])
        self.assertEqual(m["score"], ["5-5-0", "5-5-0"])
        self.assertIsNone(m["winner"])
        cats = {c["name"]: c for c in m["categories"]}
        self.assertEqual(cats["FG%"]["values"], [".499", ".446"])
        self.assertEqual(cats["FG%"]["made_attempted"], ["182/365", "206/462"])
        self.assertEqual(cats["FG%"]["winner"], "Cho")
        self.assertEqual(cats["TO"]["winner"], "Cho")   # 55 vs 80, fewer wins
        self.assertEqual(cats["PTS"]["winner"], "Kharami")

    def test_player_week_counts_only_started_days(self):
        cho = next(t for t in self.sheet["teams"] if t["team"] == "Cho")
        brunson = next(p for p in cho["players"] if p["name"] == "Jalen Brunson")
        self.assertEqual(brunson["games"], 3)
        self.assertEqual(brunson["line"]["PTS"], 58)
        self.assertEqual(brunson["line"]["FGM/A"], "21/51")
        # Jalen Green scored 29 from the IL slot on Nov 6: reported, not counted.
        green = next(p for p in cho["benched"] if p["name"] == "Jalen Green")
        self.assertEqual(green["line"]["PTS"], 29)

    def test_all_zero_line_is_not_a_game_played(self):
        scott = next(t for t in self.sheet["teams"] if t["team"] == "Team Scott")
        luka = next(p for p in scott["players"] if p["name"] == "Luka Dončić")
        self.assertEqual(luka["games"], 2)  # Nov 5 and Nov 8; Nov 3 was 0/0 with all zeros

    def test_standings_after_one_collected_week(self):
        rows = {s["team"]: s for s in self.sheet["standings"]}
        self.assertEqual(rows["Cho"]["record"], "5-5-0")
        self.assertEqual(rows["Cho"]["pct"], 0.5)

    def test_transactions_fall_in_the_week_by_pacific_time(self):
        moves = [m["player"] for x in self.sheet["transactions"] for m in x["moves"] if m["action"] == "add"]
        self.assertIn("Harrison Barnes", moves)
        cho = next(t for t in self.sheet["teams"] if t["team"] == "Cho")
        self.assertEqual(cho["adds"]["week"], 4)
        self.assertTrue(any(h["type"] == "adds_limit" and h["team"] == "Cho" for h in self.sheet["hooks"]))

    def test_official_score_disagreeing_with_categories_is_flagged(self):
        self.conn.execute("UPDATE matchup_scores SET wins_a=6 WHERE week=3 AND idx=0")
        checks = factsheet.build_week(self.conn, 3)["checks"]
        self.assertEqual(checks, [{"type": "score_mismatch", "teams": ["Cho", "Kharami"],
                                   "computed": "5-5", "yahoo": "6-5"}])

    def test_damaged_file_is_reported_and_that_day_is_left_out(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        root = Path(tmp) / "web"
        shutil.copytree(REAL_WEEK, root)
        f = root / "days" / "2025-11-05" / "teams.txt"
        f.write_text(f.read_text(encoding="utf-8").replace("9/20|2/2|3|23", "9/20|2/2|3|32"), encoding="utf-8")
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA)
        self.addCleanup(conn.close)
        problems = web.load(conn, root, season=2025, tz="Asia/Seoul")
        self.assertEqual(len(problems), 1)
        self.assertIn("2025-11-05", problems[0])
        self.assertIn("checksum", problems[0])
        checks = factsheet.build_week(conn, 3)["checks"]
        self.assertIn({"type": "missing_days", "days": ["2025-11-05"]}, checks)

    def test_day_whose_sums_disagree_with_yahoo_is_flagged_in_the_sheet(self):
        self.conn.execute(
            """UPDATE run_log SET warnings='["Cho: PTS started players sum to 91, Yahoo shows 95"]'
               WHERE date='2025-11-03'"""
        )
        checks = factsheet.build_week(self.conn, 3)["checks"]
        self.assertEqual(checks, [{"type": "collection_warning", "day": "2025-11-03",
                                   "detail": "Cho: PTS started players sum to 91, Yahoo shows 95"}])


if __name__ == "__main__":
    unittest.main()
