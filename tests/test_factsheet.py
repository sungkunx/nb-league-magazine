import unittest

from nbl import factsheet
from nbl.collect import date_range
from tests.league import League

W1 = date_range("2026-10-20", "2026-10-25")
W2 = date_range("2026-10-26", "2026-11-01")
W3 = date_range("2026-11-02", "2026-11-08")


class Base(unittest.TestCase):
    def league(self, **kwargs):
        lg = League(**kwargs)
        self.addCleanup(lg.close)
        return lg

    @staticmethod
    def build(lg, week, **kwargs):
        return factsheet.build_week(lg.conn, week, **kwargs)

    @staticmethod
    def team(sheet, name):
        return next(t for t in sheet["teams"] if t["team"] == name)

    def player(self, sheet, team, name):
        return next(p for p in self.team(sheet, team)["players"] if p["name"] == name)


class MatchupTests(Base):
    def test_score_counts_category_wins_losses_and_ties(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 6, 3, 1)
        m = self.build(lg, 1)["matchups"][0]
        self.assertEqual(m["teams"], ["Alpha", "Bravo"])
        self.assertEqual(m["score"], ["6-3-1", "3-6-1"])
        self.assertEqual(m["winner"], "Alpha")

    def test_each_team_carries_its_league_number(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 6, 3, 1)
        sheet = self.build(lg, 1)
        self.assertEqual(self.team(sheet, "Alpha")["team_id"], 1)
        self.assertEqual(self.team(sheet, "Delta")["team_id"], 4)

    def test_even_category_score_has_no_winner(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 5, 5, 0)
        self.assertIsNone(self.build(lg, 1)["matchups"][0]["winner"])

    def test_categories_show_official_values_and_winner(self):
        lg = self.league().days(*W1).matchup(
            1, "Alpha", "Bravo",
            stats_a={"FGM/A": "150/330", "FG%": ".455", "PTS": "410", "TO": "40"},
            stats_b={"FGM/A": "160/320", "FG%": ".500", "PTS": "410", "TO": "52"},
            winners={"FG%": "b", "PTS": "tie", "TO": "a"},
        )
        cats = {c["name"]: c for c in self.build(lg, 1)["matchups"][0]["categories"]}
        self.assertEqual(cats["FG%"], {
            "name": "FG%", "values": [".455", ".500"],
            "made_attempted": ["150/330", "160/320"], "winner": "Bravo",
        })
        self.assertEqual(cats["PTS"], {"name": "PTS", "values": ["410", "410"], "winner": "tie"})
        self.assertEqual(cats["TO"]["winner"], "Alpha")

    def test_display_only_stats_are_not_scoring_categories(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 6, 3, 1)
        names = [c["name"] for c in self.build(lg, 1)["matchups"][0]["categories"]]
        self.assertEqual(names, ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO", "DD"])

    def test_without_official_winners_they_are_worked_out_from_values(self):
        lg = self.league().days("2026-10-20").matchup(
            1, "Alpha", "Bravo", status="midevent",
            stats_a={"PTS": "100", "TO": "10", "REB": "50"},
            stats_b={"PTS": "90", "TO": "12", "REB": "50"},
        )
        m = self.build(lg, 1)["matchups"][0]
        cats = {c["name"]: c["winner"] for c in m["categories"]}
        self.assertEqual(cats["PTS"], "Alpha")
        self.assertEqual(cats["TO"], "Alpha")  # fewer turnovers wins
        self.assertEqual(cats["REB"], "tie")
        self.assertIsNone(cats["AST"])  # no values yet
        self.assertEqual(m["score"], ["2-0-1", "0-2-1"])

    def test_shooting_winner_uses_exact_ratio_not_rounded_display(self):
        lg = self.league().days("2026-10-20").matchup(
            1, "Alpha", "Bravo", status="midevent",
            stats_a={"FGM/A": "5/11", "FG%": ".455"},     # .4545
            stats_b={"FGM/A": "455/1000", "FG%": ".455"},  # .4550
        )
        cats = {c["name"]: c["winner"] for c in self.build(lg, 1)["matchups"][0]["categories"]}
        self.assertEqual(cats["FG%"], "Bravo")


class StandingsTests(Base):
    def two_weeks(self):
        return (
            self.league().days(*W1, *W2)
            .result(1, "Alpha", "Bravo", 6, 3, 1).result(1, "Cobra", "Delta", 5, 5, 0)
            .result(2, "Alpha", "Cobra", 2, 8, 0).result(2, "Bravo", "Delta", 5, 4, 1)
        )

    def rows(self, sheet):
        return {s["team"]: s for s in sheet["standings"]}

    def test_tie_counts_as_half_a_win(self):
        alpha = self.rows(self.build(self.two_weeks(), 1))["Alpha"]
        self.assertEqual((alpha["w"], alpha["l"], alpha["t"]), (6, 3, 1))
        self.assertEqual(alpha["pct"], 0.65)

    def test_records_accumulate_across_weeks(self):
        rows = self.rows(self.build(self.two_weeks(), 2))
        self.assertEqual(rows["Alpha"]["record"], "8-11-1")
        self.assertEqual(rows["Cobra"]["record"], "13-7-0")
        self.assertEqual(rows["Bravo"]["pct"], 0.45)

    def test_ranked_by_win_percentage(self):
        sheet = self.build(self.two_weeks(), 2)
        self.assertEqual([s["team"] for s in sheet["standings"]], ["Cobra", "Delta", "Bravo", "Alpha"])
        self.assertEqual([s["rank"] for s in sheet["standings"]], [1, 2, 3, 4])

    def test_rank_change_is_measured_against_previous_week(self):
        rows = self.rows(self.build(self.two_weeks(), 2))
        self.assertEqual((rows["Cobra"]["prev_rank"], rows["Cobra"]["change"]), (2, 1))
        self.assertEqual((rows["Alpha"]["prev_rank"], rows["Alpha"]["change"]), (1, -3))

    def test_first_week_has_no_previous_rank(self):
        rows = self.rows(self.build(self.two_weeks(), 1))
        self.assertIsNone(rows["Alpha"]["prev_rank"])
        self.assertIsNone(rows["Alpha"]["change"])

    def test_playoff_matchups_do_not_change_standings(self):
        lg = self.two_weeks().days(*W3).result(3, "Alpha", "Bravo", 10, 0, 0, playoffs=True)
        self.assertEqual(self.rows(self.build(lg, 3))["Alpha"]["record"], "8-11-1")

    def test_week_in_progress_is_left_out_of_standings(self):
        lg = (
            self.league().days(*W1, "2026-10-26", "2026-10-27")
            .result(1, "Alpha", "Bravo", 6, 3, 1).result(1, "Cobra", "Delta", 5, 5, 0)
            .result(2, "Alpha", "Cobra", 2, 8, 0, status="midevent")
        )
        sheet = self.build(lg, 2)
        self.assertEqual(self.rows(sheet)["Alpha"]["record"], "6-3-1")
        self.assertEqual(sheet["meta"]["standings_through_week"], 1)

    def test_before_any_week_finishes_there_is_no_ranking(self):
        lg = self.league().days("2026-10-20").result(1, "Alpha", "Bravo", 6, 3, 1, status="midevent")
        sheet = self.build(lg, 1)
        alpha = self.rows(sheet)["Alpha"]
        self.assertEqual(alpha["record"], "0-0-0")
        self.assertIsNone(alpha["rank"])
        self.assertIsNone(alpha["pct"])
        self.assertEqual(sheet["meta"]["standings_through_week"], 0)

    def test_disagreement_with_yahoo_standings_is_flagged(self):
        lg = self.two_weeks()
        lg.conn.execute("INSERT INTO standings VALUES ('2026-10-25','Alpha',1,7,2,1,.75,NULL)")
        checks = self.build(lg, 1)["checks"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["type"], "standings_mismatch")
        self.assertEqual(checks[0]["team"], "Alpha")
        self.assertEqual((checks[0]["computed"], checks[0]["yahoo"]), ("6-3-1", "7-2-1"))

    def test_yahoo_standings_not_yet_updated_are_not_compared(self):
        lg = self.two_weeks()
        lg.conn.execute("INSERT INTO standings VALUES ('2026-10-25','Alpha',NULL,0,0,0,NULL,NULL)")
        self.assertEqual(self.build(lg, 1)["checks"], [])


class PlayerWeekTests(Base):
    def star_week(self, official=None):
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo", stats_a=official or {})
        lg.play("2026-10-20", "Alpha", "Star", "PG", PTS=30, REB=5, AST=10, FG="10/20", FT="8/10",
                ST=1, BLK=0, TO=4, DD=1, **{"3PTM": 2})
        lg.play("2026-10-21", "Alpha", "Star", "BN", PTS=50, REB=10, AST=10, FG="20/30", FT="5/5",
                ST=0, BLK=0, TO=1, DD=1, **{"3PTM": 5})
        lg.play("2026-10-22", "Alpha", "Star", "Util", PTS=20, REB=7, AST=6, FG="8/16", FT="2/4",
                ST=2, BLK=1, TO=2, DD=0, **{"3PTM": 1})
        lg.play("2026-10-23", "Alpha", "Star", "PG")  # in the lineup, team had no game
        return lg

    def test_only_days_in_a_starting_slot_count(self):
        line = self.player(self.build(self.star_week(), 1), "Alpha", "Star")["line"]
        self.assertEqual(line["PTS"], 50)
        self.assertEqual(line["REB"], 12)
        self.assertEqual(line["AST"], 16)
        self.assertEqual(line["TO"], 6)
        self.assertEqual(line["3PTM"], 3)

    def test_games_counts_started_days_actually_played(self):
        self.assertEqual(self.player(self.build(self.star_week(), 1), "Alpha", "Star")["games"], 2)

    def test_shooting_percentages_come_from_summed_makes_and_attempts(self):
        line = self.player(self.build(self.star_week(), 1), "Alpha", "Star")["line"]
        self.assertEqual(line["FGM/A"], "18/36")
        self.assertEqual(line["FG%"], 0.5)
        self.assertEqual(line["FTM/A"], "10/14")
        self.assertEqual(line["FT%"], 0.714)

    def test_bench_days_are_reported_separately(self):
        benched = self.team(self.build(self.star_week(), 1), "Alpha")["benched"]
        self.assertEqual(len(benched), 1)
        self.assertEqual((benched[0]["name"], benched[0]["games"], benched[0]["line"]["PTS"]), ("Star", 1, 50))

    def test_injured_list_days_do_not_count_as_started(self):
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        lg.play("2026-10-20", "Alpha", "Hurt", "IL", PTS=12, FG="5/9")
        team = self.team(self.build(lg, 1), "Alpha")
        self.assertEqual(team["players"], [])
        self.assertEqual(team["benched"][0]["name"], "Hurt")

    def test_slot_missing_from_league_settings_still_counts_as_started(self):
        # Only slots the league marks as non-starting (BN, IL) are excluded.
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        lg.play("2026-10-20", "Alpha", "Swing", "G", PTS=14, FG="6/11")
        team = self.team(self.build(lg, 1), "Alpha")
        self.assertEqual([p["name"] for p in team["players"]], ["Swing"])
        self.assertEqual(team["benched"], [])

    def test_injured_plus_slot_is_never_a_starter_even_if_settings_omit_it(self):
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        lg.play("2026-10-20", "Alpha", "Hurt", "IL+", PTS=12, FG="5/9")
        self.assertEqual(self.team(self.build(lg, 1), "Alpha")["players"], [])

    def test_slots_with_unknown_starting_flag_count_as_started(self):
        # Older Yahoo responses omit is_starting_position altogether.
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        lg.conn.execute("UPDATE roster_positions SET is_starting=NULL")
        lg.play("2026-10-20", "Alpha", "Starter", "PG", PTS=14, FG="6/11")
        lg.play("2026-10-20", "Alpha", "Sub", "BN", PTS=9, FG="4/7")
        team = self.team(self.build(lg, 1), "Alpha")
        self.assertEqual([p["name"] for p in team["players"]], ["Starter"])
        self.assertEqual([p["name"] for p in team["benched"]], ["Sub"])

    def test_player_moved_midweek_is_split_between_teams(self):
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        lg.play("2026-10-20", "Alpha", "Mover", "PG", PTS=30, FG="10/20")
        lg.play("2026-10-22", "Bravo", "Mover", "SG", PTS=20, FG="8/16")
        sheet = self.build(lg, 1)
        self.assertEqual(self.player(sheet, "Alpha", "Mover")["line"]["PTS"], 30)
        self.assertEqual(self.player(sheet, "Bravo", "Mover")["line"]["PTS"], 20)

    def test_days_outside_the_week_are_ignored(self):
        lg = self.league().days(*W1, *W2).matchup(1, "Alpha", "Bravo")
        lg.play("2026-10-25", "Alpha", "Star", "PG", PTS=10, FG="4/8")
        lg.play("2026-10-26", "Alpha", "Star", "PG", PTS=99, FG="40/50")
        self.assertEqual(self.player(self.build(lg, 1), "Alpha", "Star")["line"]["PTS"], 10)

    def test_totals_matching_official_numbers_raise_no_check(self):
        lg = self.star_week(official={"PTS": "50", "REB": "12", "FGM/A": "18/36", "FG%": ".500"})
        self.assertEqual(self.build(lg, 1)["checks"], [])

    def test_counting_total_that_differs_from_official_is_flagged(self):
        lg = self.star_week(official={"PTS": "55", "REB": "12"})
        checks = self.build(lg, 1)["checks"]
        self.assertEqual(checks, [{
            "type": "total_mismatch", "team": "Alpha", "category": "PTS", "official": "55", "computed": "50",
        }])

    def test_shooting_total_that_differs_from_official_is_flagged(self):
        lg = self.star_week(official={"FGM/A": "19/36", "FG%": ".528"})
        checks = self.build(lg, 1)["checks"]
        self.assertEqual(checks, [{
            "type": "total_mismatch", "team": "Alpha", "category": "FG%", "official": "19/36", "computed": "18/36",
        }])

    def test_uncollected_day_inside_the_week_is_flagged(self):
        lg = self.league().days("2026-10-20", "2026-10-22").matchup(1, "Alpha", "Bravo", status="midevent")
        checks = self.build(lg, 1)["checks"]
        self.assertEqual(checks, [{"type": "missing_days", "days": ["2026-10-21"]}])


class CandidateTests(Base):
    BASE = dict(PTS=20, REB=5, AST=5, FG="8/16", FT="4/5", ST=1, BLK=1, TO=2, DD=0, **{"3PTM": 2})

    def league_of(self, lines, games=2):
        """lines: {player: overrides}; each on their own team, `games` identical games."""
        lg = self.league(teams=tuple(f"T-{p}" for p in lines)).days(*W1)
        for player, overrides in lines.items():
            for day in W1[:overrides.pop("games", games)]:
                lg.play(day, f"T-{player}", player, "PG", **{**self.BASE, **overrides})
        return lg

    def scores(self, sheet):
        return {p["name"]: p["score"] for t in sheet["teams"] for p in t["players"]}

    def test_best_week_leads_the_mvp_candidates(self):
        sheet = self.build(self.league_of({"Big": {"PTS": 45}, "Mid": {}, "Avg": {}, "Low": {"PTS": 8}}), 1)
        self.assertEqual(sheet["mvp_candidates"][0]["name"], "Big")
        self.assertEqual(sheet["mvp_candidates"][0]["team"], "T-Big")
        self.assertEqual(sheet["lvp_candidates"][0]["name"], "Low")

    def test_identical_weeks_score_the_same(self):
        scores = self.scores(self.build(self.league_of({"A": {}, "B": {}, "C": {"PTS": 30}}), 1))
        self.assertEqual(scores["A"], scores["B"])

    def test_turnovers_count_against_a_player(self):
        scores = self.scores(self.build(self.league_of({"Safe": {"TO": 1}, "Loose": {"TO": 6}, "Avg": {}}), 1))
        self.assertGreater(scores["Safe"], scores["Avg"])
        self.assertGreater(scores["Avg"], scores["Loose"])

    def test_better_shooting_on_same_volume_scores_higher(self):
        scores = self.scores(self.build(
            self.league_of({"Hot": {"FG": "12/16"}, "Cold": {"FG": "4/16"}, "Avg": {}}), 1))
        self.assertGreater(scores["Hot"], scores["Avg"])
        self.assertGreater(scores["Avg"], scores["Cold"])

    def test_lvp_needs_a_minimum_number_of_games(self):
        lines = {"Cameo": {"PTS": 0, "games": 1}, "Reg1": {"games": 4}, "Reg2": {"games": 4, "PTS": 12},
                 "Reg3": {"games": 4, "PTS": 25}}
        sheet = self.build(self.league_of(lines), 1)
        names = [p["name"] for p in sheet["lvp_candidates"]]
        self.assertNotIn("Cameo", names)
        self.assertEqual(names[0], "Reg2")

    def test_candidates_carry_their_stat_line(self):
        sheet = self.build(self.league_of({"Big": {"PTS": 45}, "Mid": {}, "Low": {"PTS": 8}}), 1)
        top = sheet["mvp_candidates"][0]
        self.assertEqual(top["games"], 2)
        self.assertEqual(top["line"]["PTS"], 90)

    def test_at_most_five_candidates_each(self):
        lines = {f"P{i}": {"PTS": 10 + i} for i in range(8)}
        sheet = self.build(self.league_of(lines), 1)
        self.assertEqual(len(sheet["mvp_candidates"]), 5)
        self.assertEqual(len(sheet["lvp_candidates"]), 5)


class TransactionTests(Base):
    def moves(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 6, 3, 1)
        lg.tx("t0", "2026-10-19T10:00", "add", [("Early", "add", "freeagents", "Alpha")])
        lg.tx("t1", "2026-10-21T10:00", "add/drop",
              [("New Guy", "add", "freeagents", "Alpha"), ("Old Guy", "drop", "Alpha", "waivers")])
        lg.tx("t3", "2026-10-25T23:30", "trade",
              [("Star", "trade", "Alpha", "Bravo"), ("Other", "trade", "Bravo", "Alpha")])
        lg.tx("t2", "2026-10-26T00:30", "add", [("Late", "add", "waivers", "Alpha")])
        lg.tx("t4", "2026-10-22T10:00", "trade", [("Nope", "trade", "Alpha", "Bravo")], status="vetoed")
        return lg

    def test_only_successful_moves_inside_the_week_oldest_first(self):
        tx = self.build(self.moves(), 1)["transactions"]
        self.assertEqual([t["type"] for t in tx], ["add/drop", "trade"])

    def test_move_shows_korean_time_and_direction(self):
        first = self.build(self.moves(), 1)["transactions"][0]
        self.assertEqual(first["time_kst"], "2026-10-22 02:00")
        self.assertEqual(first["moves"], [
            {"player": "New Guy", "action": "add", "from": "FA", "to": "Alpha"},
            {"player": "Old Guy", "action": "drop", "from": "Alpha", "to": "Waivers"},
        ])

    def test_trade_shows_both_directions(self):
        trade = self.build(self.moves(), 1)["transactions"][1]
        self.assertEqual(trade["moves"], [
            {"player": "Star", "action": "trade", "from": "Alpha", "to": "Bravo"},
            {"player": "Other", "action": "trade", "from": "Bravo", "to": "Alpha"},
        ])

    def test_team_add_counters_cover_week_and_season_to_date(self):
        alpha = self.team(self.build(self.moves(), 1), "Alpha")
        self.assertEqual(alpha["adds"], {"week": 1, "week_limit": 4, "season": 2, "season_limit": 100})
        bravo = self.team(self.build(self.moves(), 1), "Bravo")
        self.assertEqual(bravo["adds"]["week"], 0)

    def test_preseason_moves_are_collected_separately(self):
        pre = factsheet.build_preseason(self.moves().conn)
        self.assertEqual([t["moves"][0]["player"] for t in pre["transactions"]], ["Early"])


class HookTests(Base):
    def hooks(self, sheet, kind):
        return [h for h in sheet["hooks"] if h["type"] == kind]

    def test_tied_matchup_is_a_hook(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 5, 5, 0).result(1, "Cobra", "Delta", 6, 4, 0)
        ties = self.hooks(self.build(lg, 1), "tie")
        self.assertEqual(len(ties), 1)
        self.assertEqual(ties[0]["teams"], ["Alpha", "Bravo"])

    def test_blowout_needs_eight_category_wins(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 9, 1, 0).result(1, "Cobra", "Delta", 7, 3, 0)
        blowouts = self.hooks(self.build(lg, 1), "blowout")
        self.assertEqual(len(blowouts), 1)
        self.assertEqual((blowouts[0]["winner"], blowouts[0]["loser"], blowouts[0]["score"]),
                         ("Alpha", "Bravo", "9-1-0"))

    def test_lower_ranked_team_winning_is_an_upset(self):
        lg = (
            self.league().days(*W1, *W2)
            .result(1, "Alpha", "Bravo", 9, 1, 0).result(1, "Cobra", "Delta", 6, 4, 0)
            .result(2, "Alpha", "Bravo", 4, 6, 0).result(2, "Cobra", "Delta", 6, 4, 0)
        )
        upsets = self.hooks(self.build(lg, 2, upset_gap=2), "upset")
        self.assertEqual(len(upsets), 1)
        self.assertEqual((upsets[0]["winner"], upsets[0]["winner_prev_rank"]), ("Bravo", 4))
        self.assertEqual((upsets[0]["loser"], upsets[0]["loser_prev_rank"]), ("Alpha", 1))

    def test_small_rank_gap_is_not_an_upset(self):
        lg = (
            self.league().days(*W1, *W2)
            .result(1, "Alpha", "Bravo", 9, 1, 0).result(1, "Cobra", "Delta", 6, 4, 0)
            .result(2, "Alpha", "Bravo", 4, 6, 0).result(2, "Cobra", "Delta", 4, 6, 0)
        )
        upsets = self.hooks(self.build(lg, 2, upset_gap=2), "upset")
        self.assertEqual([u["winner"] for u in upsets], ["Bravo"])  # Delta (3rd) over Cobra (2nd) is not

    def three_weeks(self):
        return (
            self.league().days(*W1, *W2, *W3)
            .result(1, "Alpha", "Bravo", 6, 4, 0).result(1, "Cobra", "Delta", 6, 4, 0)
            .result(2, "Alpha", "Cobra", 6, 4, 0).result(2, "Delta", "Bravo", 6, 4, 0)
            .result(3, "Alpha", "Delta", 6, 4, 0).result(3, "Bravo", "Cobra", 6, 4, 0)
        )

    def test_three_straight_matchup_wins_is_a_streak(self):
        streaks = self.hooks(self.build(self.three_weeks(), 3), "streak")
        self.assertEqual(streaks, [{"id": streaks[0]["id"], "type": "streak", "team": "Alpha",
                                    "kind": "win", "length": 3}])

    def test_two_straight_wins_is_not_yet_a_streak(self):
        self.assertEqual(self.hooks(self.build(self.three_weeks(), 2), "streak"), [])

    def test_using_every_weekly_add_is_a_hook(self):
        lg = self.league().days(*W1).result(1, "Alpha", "Bravo", 6, 3, 1)
        for i in range(4):
            lg.tx(f"t{i}", f"2026-10-2{i + 1}T10:00", "add", [(f"Guy{i}", "add", "freeagents", "Alpha")])
        limits = self.hooks(self.build(lg, 1), "adds_limit")
        self.assertEqual([h["team"] for h in limits], ["Alpha"])


class LineupChangeTests(Base):
    def week(self):
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        # Night before: Star starts, Sub on the bench. By game time they were swapped.
        lg.pre("2026-10-20", "Alpha", "Star", "PG").pre("2026-10-20", "Alpha", "Sub", "BN")
        lg.play("2026-10-20", "Alpha", "Star", "BN", PTS=31, FG="11/20")
        lg.play("2026-10-20", "Alpha", "Sub", "PG", PTS=4, FG="2/9")
        return lg

    def changes(self, lg):
        return self.build(lg, 1)["lineup_changes"]

    def test_player_benched_after_the_night_snapshot_is_listed_with_his_line(self):
        benched = next(c for c in self.changes(self.week()) if c["player"] == "Star")
        self.assertEqual(benched["id"][0], "C")
        self.assertEqual((benched["date"], benched["team"]), ("2026-10-20", "Alpha"))
        self.assertEqual((benched["from"], benched["to"], benched["change"]), ("PG", "BN", "benched"))
        self.assertTrue(benched["played"])
        self.assertEqual(benched["line"]["PTS"], "31")
        self.assertEqual(benched["line"]["FGM/A"], "11/20")

    def test_player_moved_into_the_lineup_is_listed(self):
        started = next(c for c in self.changes(self.week()) if c["player"] == "Sub")
        self.assertEqual((started["from"], started["to"], started["change"]), ("BN", "PG", "started"))

    def test_moving_between_two_starting_slots_is_not_a_change(self):
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        lg.pre("2026-10-20", "Alpha", "Star", "PG").play("2026-10-20", "Alpha", "Star", "Util", PTS=20, FG="8/15")
        self.assertEqual(self.changes(lg), [])

    def test_benched_player_who_did_not_play_has_no_line(self):
        lg = self.league().days(*W1).matchup(1, "Alpha", "Bravo")
        lg.pre("2026-10-20", "Alpha", "Hurt", "C").play("2026-10-20", "Alpha", "Hurt", "IL")
        (change,) = self.changes(lg)
        self.assertEqual(change["change"], "benched")
        self.assertFalse(change["played"])
        self.assertNotIn("line", change)

    def test_day_without_final_roster_yet_is_skipped(self):
        lg = self.league().days("2026-10-20").matchup(1, "Alpha", "Bravo", status="midevent")
        lg.pre("2026-10-21", "Alpha", "Star", "PG")
        self.assertEqual(self.changes(lg), [])

    def test_meta_lists_days_that_have_a_night_snapshot(self):
        self.assertEqual(self.build(self.week(), 1)["meta"]["lineup_snapshot_days"], ["2026-10-20"])

    def test_markdown_shows_the_change(self):
        text = factsheet.render_md(self.build(self.week(), 1))
        self.assertIn("C1", text)
        self.assertIn("Star: PG → BN", text)
        self.assertIn("31", text)


class SheetTests(Base):
    def full(self):
        lg = (
            self.league().days(*W1)
            .result(1, "Alpha", "Bravo", 9, 1, 0).result(1, "Cobra", "Delta", 5, 5, 0)
            .matchup(2, "Alpha", "Cobra", status="preevent").matchup(2, "Bravo", "Delta", status="preevent")
        )
        lg.play("2026-10-20", "Alpha", "Star", "PG", PTS=30, FG="10/20")
        lg.play("2026-10-20", "Bravo", "Role", "PG", PTS=10, FG="4/10")
        lg.tx("t1", "2026-10-21T10:00", "add", [("New Guy", "add", "freeagents", "Alpha")])
        return lg

    def test_meta_describes_the_week_and_how_far_data_goes(self):
        meta = self.build(self.full(), 1)["meta"]
        self.assertEqual(meta["league"], "NB League")
        self.assertEqual(meta["season"], "2026-27")
        self.assertEqual((meta["week"], meta["week_start"], meta["week_end"]), (1, "2026-10-20", "2026-10-25"))
        self.assertEqual(meta["through"], "2026-10-25")
        self.assertTrue(meta["complete"])
        self.assertFalse(meta["is_playoffs"])

    def test_meta_marks_a_week_in_progress(self):
        lg = self.league().days("2026-10-20", "2026-10-21").result(1, "Alpha", "Bravo", 6, 3, 1, status="midevent")
        meta = self.build(lg, 1)["meta"]
        self.assertEqual(meta["through"], "2026-10-21")
        self.assertFalse(meta["complete"])

    def test_next_week_lists_pairings_with_current_rank_and_record(self):
        nxt = self.build(self.full(), 1)["next_week"]
        self.assertEqual(nxt[0]["teams"], ["Alpha", "Cobra"])
        self.assertEqual(nxt[0]["ranks"], [1, 2])
        self.assertEqual(nxt[0]["records"], ["9-1-0", "5-5-0"])
        self.assertEqual(len(nxt), 2)

    def test_every_fact_has_a_unique_id(self):
        sheet = self.build(self.full(), 1)
        ids = [
            item["id"]
            for section in ("matchups", "standings", "teams", "mvp_candidates", "lvp_candidates",
                            "transactions", "lineup_changes", "hooks", "next_week")
            for item in sheet[section]
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sheet["matchups"][0]["id"], "M1")
        self.assertEqual(sheet["standings"][0]["id"], "S1")
        self.assertEqual(sheet["transactions"][0]["id"], "X1")

    def test_unknown_week_is_an_error(self):
        with self.assertRaises(ValueError):
            self.build(self.full(), 9)

    def test_markdown_shows_ids_names_and_numbers(self):
        text = factsheet.render_md(self.build(self.full(), 1))
        self.assertIn("NB League 2026-27", text)
        self.assertIn("Week 1", text)
        self.assertIn("M1", text)
        self.assertIn("Alpha 9-1-0 Bravo", text)
        self.assertIn("S1", text)
        self.assertIn("Star", text)
        self.assertIn("New Guy", text)
        self.assertIn("X1", text)

    def test_markdown_lists_data_checks_prominently(self):
        lg = self.league().days("2026-10-20", "2026-10-22").matchup(1, "Alpha", "Bravo", status="midevent")
        text = factsheet.render_md(self.build(lg, 1))
        self.assertIn("missing_days", text)
        self.assertIn("2026-10-21", text)

    def test_markdown_says_when_no_week_has_finished_yet(self):
        lg = self.league().days("2026-10-20").matchup(1, "Alpha", "Bravo", status="midevent")
        text = factsheet.render_md(self.build(lg, 1))
        self.assertIn("순위 기준: 아직 끝난 주 없음", text)
        self.assertNotIn("Week 0", text)


if __name__ == "__main__":
    unittest.main()


class EmptySideTests(unittest.TestCase):
    """Yahoo gives a category to the team that has a value when the other has none (seen in week 1, 2026)."""
    FT = {"stat_id": "FT%", "source_id": "FTM/A", "lower": False}
    TO = {"stat_id": "TO", "source_id": None, "lower": True}

    def test_no_free_throws_attempted_loses_ft_percent(self):
        self.assertEqual(factsheet._compare(self.FT, {"FTM/A": "9/10"}, {"FTM/A": "0/0", "FT%": "-"}), "a")
        self.assertEqual(factsheet._compare(self.FT, {"FTM/A": "0/0"}, {"FTM/A": "9/10"}), "b")

    def test_a_team_with_no_games_loses_every_category_even_turnovers(self):
        self.assertEqual(factsheet._compare(self.TO, {"TO": "3"}, {"TO": "-"}), "a")

    def test_both_empty_is_still_undecided(self):
        self.assertIsNone(factsheet._compare(self.TO, {"TO": "-"}, {"TO": "-"}))
        self.assertIsNone(factsheet._compare(self.FT, {"FTM/A": "0/0"}, {"FTM/A": "-/-"}))
