import unittest

from nbl import factsheet
from tests.league import League


class DraftSheetTests(unittest.TestCase):
    def setUp(self):
        self.lg = League(teams=("Alpha", "Bravo"))
        self.addCleanup(self.lg.close)
        (self.lg
         .draft(1, 1, "Alpha", "Top Pick", adp=1.4, PTS=2000, REB=900, TO=250, FG="700/1300")
         .draft(2, 1, "Bravo", "Reach Guy", adp=9.0, PTS=1500, REB=300, TO=120, FG="500/1100")
         .draft(3, 2, "Bravo", "Steal Guy", adp=1.9, PTS=1800, REB=500, TO=200, FG="650/1400")
         .draft(4, 2, "Alpha", "Mystery", adp=None, PTS=400, REB=100, TO=60, FG="150/400"))
        self.sheet = factsheet.build_draft(self.lg.conn)

    def test_picks_are_listed_in_draft_order_with_names(self):
        picks = self.sheet["picks"]
        self.assertEqual([(p["pick"], p["round"], p["team"], p["player"]) for p in picks], [
            (1, 1, "Alpha", "Top Pick"), (2, 1, "Bravo", "Reach Guy"),
            (3, 2, "Bravo", "Steal Guy"), (4, 2, "Alpha", "Mystery"),
        ])
        self.assertEqual(picks[0]["id"], "D1")

    def test_value_is_how_much_later_than_average_a_player_went(self):
        value = {p["player"]: p["vs_adp"] for p in self.sheet["picks"]}
        self.assertEqual(value["Reach Guy"], -7.0)  # taken 7 picks earlier than usual
        self.assertEqual(value["Steal Guy"], 1.1)   # lasted 1.1 picks longer than usual
        self.assertIsNone(value["Mystery"])

    def test_steals_and_reaches_rank_the_extremes(self):
        self.assertEqual(self.sheet["steals"][0]["player"], "Steal Guy")
        self.assertEqual(self.sheet["reaches"][0]["player"], "Reach Guy")
        everyone = [p["player"] for p in self.sheet["steals"] + self.sheet["reaches"]]
        self.assertNotIn("Mystery", everyone)

    def test_steals_only_include_players_who_fell(self):
        self.assertEqual([p["player"] for p in self.sheet["steals"]], ["Steal Guy"])
        self.assertEqual([p["player"] for p in self.sheet["reaches"]], ["Reach Guy", "Top Pick"])

    def test_team_totals_add_up_last_seasons_numbers(self):
        teams = {t["team"]: t for t in self.sheet["teams"]}
        self.assertEqual(teams["Alpha"]["prev_season"]["PTS"], 2400)
        self.assertEqual(teams["Bravo"]["prev_season"]["PTS"], 3300)
        self.assertEqual(teams["Alpha"]["prev_season"]["FGM/A"], "850/1700")
        self.assertEqual(teams["Alpha"]["prev_season"]["FG%"], 0.5)
        self.assertEqual([p["player"] for p in teams["Alpha"]["picks"]], ["Top Pick", "Mystery"])

    def test_category_ranks_respect_direction(self):
        teams = {t["team"]: t for t in self.sheet["teams"]}
        self.assertEqual(teams["Bravo"]["category_ranks"]["PTS"], 1)
        self.assertEqual(teams["Alpha"]["category_ranks"]["PTS"], 2)
        # Alpha's 310 turnovers beat Bravo's 320: fewer is better.
        self.assertEqual(teams["Alpha"]["category_ranks"]["TO"], 1)
        self.assertEqual(teams["Alpha"]["category_ranks"]["FG%"], 1)  # .500 vs .460

    def test_before_the_draft_the_sheet_is_empty(self):
        lg = League()
        self.addCleanup(lg.close)
        sheet = factsheet.build_draft(lg.conn)
        self.assertEqual(sheet["picks"], [])
        self.assertEqual(sheet["steals"], [])

    def test_markdown_lists_picks_and_team_tables(self):
        text = factsheet.render_draft_md(self.sheet)
        self.assertIn("D1", text)
        self.assertIn("Top Pick", text)
        self.assertIn("Alpha", text)
        self.assertIn("850/1700", text)


if __name__ == "__main__":
    unittest.main()
