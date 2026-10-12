import unittest
from pathlib import Path

from nbl import parse

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return parse.xml_root((FIX / name).read_bytes())


class LeagueTests(unittest.TestCase):
    def test_league_meta_has_key_dates_and_weeks(self):
        meta = parse.league_meta(load("settings.xml"))
        self.assertEqual(meta["league_key"], "470.l.80126")
        self.assertEqual(meta["name"], "NB League 2026")
        self.assertEqual(meta["season"], 2026)
        self.assertEqual(meta["start_date"], "2026-10-20")
        self.assertEqual(meta["end_date"], "2027-04-04")
        self.assertEqual(meta["num_teams"], 16)

    def test_settings_reads_limits_and_playoffs(self):
        s = parse.settings(load("settings.xml"))
        self.assertEqual(s["playoff_start_week"], 20)
        self.assertEqual(s["num_playoff_teams"], 8)
        self.assertEqual(s["max_weekly_adds"], 4)
        self.assertEqual(s["max_adds"], 100)
        self.assertEqual(s["trade_end_date"], "2027-03-04")

    def test_stat_categories_mark_display_only_and_direction(self):
        cats = {c["display_name"]: c for c in parse.stat_categories(load("settings.xml"))}
        self.assertTrue(cats["FGM/A"]["is_display_only"])
        self.assertFalse(cats["FG%"]["is_display_only"])
        self.assertTrue(cats["TO"]["lower_is_better"])
        self.assertFalse(cats["PTS"]["lower_is_better"])
        self.assertEqual(cats["PTS"]["stat_id"], "12")

    def test_roster_positions_know_which_slots_start(self):
        pos = {p["position"]: p for p in parse.roster_positions(load("settings.xml"))}
        self.assertEqual(pos["Util"]["count"], 3)
        self.assertTrue(pos["PG"]["is_starting"])
        self.assertFalse(pos["BN"]["is_starting"])
        self.assertFalse(pos["IL"]["is_starting"])

    def test_roster_position_without_starting_flag_is_unknown_not_bench(self):
        root = parse.xml_root(
            b"<fantasy_content><league><settings><roster_positions>"
            b"<roster_position><position>PG</position><count>1</count></roster_position>"
            b"</roster_positions></settings></league></fantasy_content>"
        )
        self.assertIsNone(parse.roster_positions(root)[0]["is_starting"])

    def test_game_weeks(self):
        weeks = parse.game_weeks(load("game_weeks.xml"))
        self.assertEqual(weeks[0], {"week": 1, "start": "2026-10-20", "end": "2026-10-25"})
        self.assertEqual(len(weeks), 2)

    def test_games_gives_game_key_per_season(self):
        self.assertEqual(parse.games(load("games.xml")), [{"game_key": "470", "season": 2026}])

    def test_user_leagues_lists_every_season(self):
        leagues = parse.user_leagues(load("user_leagues.xml"))
        self.assertEqual(
            [(l["season"], l["league_key"]) for l in leagues],
            [(2025, "466.l.12345"), (2026, "470.l.80126")],
        )
        self.assertEqual(leagues[0]["name"], "NB League 2025")


class TeamTests(unittest.TestCase):
    def test_teams_carry_manager_and_move_counters(self):
        teams = parse.teams(load("teams.xml"))
        self.assertEqual(len(teams), 2)
        cho = teams[0]
        self.assertEqual(cho["team_key"], "470.l.80126.t.1")
        self.assertEqual(cho["name"], "Cho")
        self.assertEqual(cho["manager"], "Chochi")
        self.assertEqual(cho["moves"], 5)
        self.assertEqual(cho["trades"], 1)
        self.assertEqual(cho["adds_week"], 1)
        self.assertEqual(cho["adds_used"], 2)
        self.assertEqual(teams[1]["name"], "YoungHun`s Team Bravo")

    def test_standings_rows(self):
        rows = parse.standings(load("standings.xml"))
        self.assertEqual(rows[0], {
            "team_key": "470.l.80126.t.2", "rank": 1, "wins": 6, "losses": 3,
            "ties": 1, "pct": 0.65, "playoff_seed": 1,
        })
        self.assertIsNone(rows[1]["playoff_seed"])

    def test_standings_before_season_have_no_rank(self):
        rows = parse.standings(load("standings_predraft.xml"))
        self.assertIsNone(rows[0]["rank"])
        self.assertIsNone(rows[0]["pct"])
        self.assertEqual(rows[0]["wins"], 0)


class ScoreboardTests(unittest.TestCase):
    def setUp(self):
        self.m = parse.scoreboard(load("scoreboard_w1.xml"))[0]

    def test_matchup_header(self):
        self.assertEqual(self.m["week"], 1)
        self.assertEqual(self.m["week_start"], "2026-10-20")
        self.assertEqual(self.m["week_end"], "2026-10-25")
        self.assertEqual(self.m["status"], "postevent")
        self.assertFalse(self.m["is_playoffs"])
        self.assertFalse(self.m["is_tied"])
        self.assertEqual(self.m["winner_team_key"], "470.l.80126.t.2")

    def test_matchup_team_stats_keep_raw_values(self):
        a, b = self.m["teams"]
        self.assertEqual(a["team_key"], "470.l.80126.t.1")
        self.assertEqual(a["stats"], {"9004003": "150/330", "5": ".455", "12": "410", "19": "40"})
        self.assertEqual(b["stats"]["5"], ".500")

    def test_stat_winners_include_ties(self):
        winners = {w["stat_id"]: w for w in self.m["stat_winners"]}
        self.assertEqual(winners["5"]["winner_team_key"], "470.l.80126.t.2")
        self.assertTrue(winners["12"]["is_tied"])
        self.assertIsNone(winners["12"]["winner_team_key"])
        self.assertFalse(winners["19"]["is_tied"])


class RosterTests(unittest.TestCase):
    def setUp(self):
        self.r = parse.roster(load("roster_t1.xml"))

    def test_roster_identifies_team_and_date(self):
        self.assertEqual(self.r["team_key"], "470.l.80126.t.1")
        self.assertEqual(self.r["date"], "2026-10-21")

    def test_roster_players_have_slot_and_status(self):
        players = {p["name"]: p for p in self.r["players"]}
        self.assertEqual(players["Nikola Jokic"]["slot"], "C")
        self.assertEqual(players["Nikola Jokic"]["player_key"], "470.p.5352")
        self.assertEqual(players["Nikola Jokic"]["nba_team"], "DEN")
        self.assertEqual(players["Nikola Jokic"]["status"], "")
        self.assertEqual(players["Tyrese Maxey"]["slot"], "BN")
        self.assertEqual(players["Tyrese Maxey"]["status"], "GTD")
        self.assertEqual(players["Tyrese Maxey"]["position"], "PG,SG")
        self.assertEqual(players["Kawhi Leonard"]["slot"], "IL")


class PlayerStatsTests(unittest.TestCase):
    def setUp(self):
        self.rows = {r["name"]: r for r in parse.player_stats(load("stats_01.xml"))}

    def test_stats_keep_date_and_raw_values(self):
        jokic = self.rows["Nikola Jokic"]
        self.assertEqual(jokic["date"], "2026-10-21")
        self.assertEqual(jokic["stats"], {"9004003": "10/18", "5": ".556", "12": "27", "19": "3"})

    def test_player_who_did_not_play_is_flagged(self):
        self.assertFalse(self.rows["Tyrese Maxey"]["played"])
        self.assertTrue(self.rows["Nikola Jokic"]["played"])

    def test_scoreless_game_still_counts_as_played(self):
        self.assertTrue(self.rows["Kawhi Leonard"]["played"])


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tx = {t["transaction_key"]: t for t in parse.transactions(load("transactions.xml"))}

    def test_add_drop_lists_both_players_with_direction(self):
        t = self.tx["470.l.80126.tr.2"]
        self.assertEqual(t["type"], "add/drop")
        self.assertEqual(t["status"], "successful")
        self.assertEqual(t["timestamp"], 1792627200)
        add, drop = t["players"]
        self.assertEqual((add["action"], add["name"]), ("add", "Dylan Harper"))
        self.assertEqual(add["source_type"], "freeagents")
        self.assertEqual(add["destination_team_key"], "470.l.80126.t.1")
        self.assertIsNone(add["source_team_key"])
        self.assertEqual((drop["action"], drop["name"]), ("drop", "Kawhi Leonard"))
        self.assertEqual(drop["source_team_key"], "470.l.80126.t.1")
        self.assertEqual(drop["destination_type"], "waivers")

    def test_trade_names_both_teams(self):
        t = self.tx["470.l.80126.tr.3"]
        self.assertEqual(t["type"], "trade")
        self.assertEqual(t["trader_team_key"], "470.l.80126.t.1")
        self.assertEqual(t["tradee_team_key"], "470.l.80126.t.2")
        self.assertEqual(t["players"][0]["destination_team_key"], "470.l.80126.t.2")


class DraftTests(unittest.TestCase):
    def test_draft_results(self):
        picks = parse.draft_results(load("draftresults.xml"))
        self.assertEqual(picks[0], {
            "pick": 1, "round": 1, "team_key": "470.l.80126.t.2", "player_key": "470.p.5352",
        })
        self.assertEqual(len(picks), 2)

    def test_players_meta_reads_average_draft_position(self):
        players = {p["name"]: p for p in parse.players_meta(load("players_draft.xml"))}
        self.assertEqual(players["Nikola Jokic"]["average_pick"], 1.2)
        self.assertEqual(players["Nikola Jokic"]["nba_team"], "DEN")
        self.assertIsNone(players["Tyrese Maxey"]["average_pick"])


class ValueTests(unittest.TestCase):
    def test_number_parses_plain_and_percent_values(self):
        self.assertEqual(parse.number("27"), 27.0)
        self.assertEqual(parse.number(".556"), 0.556)

    def test_number_treats_dash_and_blank_as_missing(self):
        self.assertIsNone(parse.number("-"))
        self.assertIsNone(parse.number(""))
        self.assertIsNone(parse.number(None))

    def test_ratio_splits_made_and_attempted(self):
        self.assertEqual(parse.ratio("10/18"), (10.0, 18.0))
        self.assertEqual(parse.ratio("0/4"), (0.0, 4.0))

    def test_ratio_of_no_game_is_missing(self):
        self.assertIsNone(parse.ratio("-/-"))
        self.assertIsNone(parse.ratio("-"))
        self.assertIsNone(parse.ratio(None))


if __name__ == "__main__":
    unittest.main()
