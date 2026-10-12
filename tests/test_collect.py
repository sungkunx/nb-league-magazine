import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nbl import collect, parse
from nbl.store import RawStore
from nbl.yahoo import YahooError
from tests.fakes import LEAGUE, FakeYahoo

PT = ZoneInfo("America/Los_Angeles")
WEEKS = [
    {"week": 1, "start": "2026-10-20", "end": "2026-10-25"},
    {"week": 2, "start": "2026-10-26", "end": "2026-11-01"},
]


def pt(text):
    return datetime.fromisoformat(text).replace(tzinfo=PT)


class PlanDatesTests(unittest.TestCase):
    def plan(self, now, done=()):
        return collect.plan_dates(pt(now), "2026-10-20", "2027-04-04", set(done))

    def test_just_after_midnight_collects_the_day_that_ended(self):
        self.assertEqual(self.plan("2026-10-22T00:05"), ["2026-10-20", "2026-10-21"])

    def test_days_already_done_are_skipped(self):
        self.assertEqual(self.plan("2026-10-22T00:05", done=["2026-10-20"]), ["2026-10-21"])
        self.assertEqual(self.plan("2026-10-22T00:05", done=["2026-10-20", "2026-10-21"]), [])

    def test_late_evening_run_does_not_touch_the_unfinished_day(self):
        # The second daily trigger lands at 23:05 PT in winter; that day is not over.
        self.assertEqual(self.plan("2026-11-10T23:05", done=self._all_before("2026-11-10")), [])

    def test_missed_days_are_filled_oldest_first(self):
        done = ["2026-10-20", "2026-10-22"]
        self.assertEqual(self.plan("2026-10-25T00:05", done), ["2026-10-21", "2026-10-23", "2026-10-24"])

    def test_before_the_season_only_yesterday_is_snapshotted(self):
        self.assertEqual(self.plan("2026-10-19T09:00"), ["2026-10-18"])
        self.assertEqual(self.plan("2026-10-19T09:00", done=["2026-10-18"]), [])

    def test_nothing_is_planned_past_the_last_day_of_the_season(self):
        done = self._all_before("2027-04-05")
        self.assertEqual(self.plan("2027-04-10T00:05", done), [])

    def test_backfill_is_capped_per_run(self):
        dates = collect.plan_dates(pt("2026-12-01T00:05"), "2026-10-20", "2027-04-04", set(), max_backfill=5)
        self.assertEqual(dates, ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"])

    @staticmethod
    def _all_before(day):
        return collect.date_range("2026-10-20", day)[:-1]


class WeekTests(unittest.TestCase):
    def test_week_for_finds_the_week_containing_a_day(self):
        self.assertEqual(collect.week_for("2026-10-20", WEEKS), 1)
        self.assertEqual(collect.week_for("2026-10-25", WEEKS), 1)
        self.assertEqual(collect.week_for("2026-10-26", WEEKS), 2)

    def test_week_for_outside_the_season_is_none(self):
        self.assertIsNone(collect.week_for("2026-10-19", WEEKS))

    def test_first_day_of_a_week_triggers_recollecting_the_previous_week(self):
        self.assertEqual(
            collect.correction_dates("2026-10-26", WEEKS),
            ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"],
        )

    def test_other_days_trigger_no_recollection(self):
        self.assertEqual(collect.correction_dates("2026-10-27", WEEKS), [])
        self.assertEqual(collect.correction_dates("2026-10-20", WEEKS), [])


class RunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = RawStore(Path(tmp.name))
        self.api = FakeYahoo()

    def run_at(self, now, api=None):
        return collect.run(api or self.api, self.store, season=2026, league_id="80126", now=pt(now))

    def test_league_key_comes_from_the_season_game_key(self):
        self.assertEqual(collect.resolve_league_key(self.api, 2026, "80126"), LEAGUE)
        self.assertIn("games;game_codes=nba;seasons=2026", self.api.paths)

    def test_in_season_day_saves_rosters_stats_and_snapshots(self):
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05")
        day = "2026-10-21"
        self.assertEqual(self.store.day_files(day), [
            f"days/{day}/roster_t1.xml",
            f"days/{day}/roster_t2.xml",
            f"days/{day}/standings.xml",
            f"days/{day}/stats_01.xml",
            f"days/{day}/transactions.xml",
        ])
        self.assertTrue(self.store.is_done(day))
        self.assertTrue(self.store.exists("league/settings.xml"))
        self.assertTrue(self.store.exists("league/teams.xml"))
        self.assertTrue(self.store.exists("league/game_weeks.xml"))
        self.assertTrue(self.store.exists("weeks/scoreboard_w01.xml"))

    def test_rosters_and_stats_are_requested_for_the_stats_day(self):
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05")
        self.assertIn(f"team/{LEAGUE}.t.1/roster;date=2026-10-21", self.api.paths)
        self.assertIn(f"team/{LEAGUE}.t.2/roster;date=2026-10-21", self.api.paths)
        self.assertIn(
            f"league/{LEAGUE}/players;player_keys=470.p.1,470.p.2,470.p.3/stats;type=date;date=2026-10-21",
            self.api.paths,
        )

    def test_saved_stats_cover_every_rostered_player(self):
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05")
        rows = parse.player_stats(parse.xml_root(self.store.load("days/2026-10-21/stats_01.xml")))
        self.assertEqual([r["player_key"] for r in rows], ["470.p.1", "470.p.2", "470.p.3"])

    def test_player_stats_are_requested_25_players_at_a_time(self):
        big = {f"{LEAGUE}.t.1": [(f"470.p.{i}", f"P{i}", "BN") for i in range(30)], f"{LEAGUE}.t.2": []}
        api = FakeYahoo(rosters=big)
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05", api)
        self.assertEqual(api.count("/stats;type=date"), 2)
        self.assertTrue(self.store.exists("days/2026-10-21/stats_02.xml"))

    def test_second_run_for_the_same_day_makes_no_roster_calls(self):
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05")
        again = FakeYahoo()
        self.run_at("2026-10-22T01:05", again)
        self.assertEqual(again.count("/roster;"), 0)
        self.assertEqual(again.count("/stats;"), 0)

    def test_run_with_nothing_new_leaves_stored_files_untouched(self):
        # Yahoo stamps every response with a timing attribute; rewriting files on
        # a no-op run would create a pointless commit twice a day.
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05")
        self.store.save("league/settings.xml", b"<previous/>")
        self.run_at("2026-10-22T01:05", FakeYahoo())
        self.assertEqual(self.store.load("league/settings.xml"), b"<previous/>")

    def test_run_info_records_live_collection_and_call_count(self):
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05")
        info = self.store.run_info("2026-10-21")
        self.assertTrue(info["live"])
        self.assertEqual(info["league_key"], LEAGUE)
        self.assertEqual(info["warnings"], [])
        self.assertIn("fetched_at", info)

    def test_backfilled_day_is_not_live_and_gets_no_standings_snapshot(self):
        self.run_at("2026-10-22T00:05")  # 10-20 was missed, 10-21 is the live day
        self.assertFalse(self.store.run_info("2026-10-20")["live"])
        self.assertFalse(self.store.exists("days/2026-10-20/standings.xml"))
        self.assertTrue(self.store.exists("days/2026-10-20/roster_t1.xml"))
        self.assertTrue(self.store.exists("days/2026-10-21/standings.xml"))

    def test_roster_for_a_different_date_is_reported_as_a_warning(self):
        api = FakeYahoo(roster_date="2026-10-22")
        self.store.mark_done("2026-10-20", {})
        self.run_at("2026-10-22T00:05", api)
        warnings = self.store.run_info("2026-10-21")["warnings"]
        self.assertEqual(len(warnings), 2)
        self.assertIn("2026-10-22", warnings[0])
        self.assertIn("t.1", warnings[0])

    def test_preseason_day_saves_rosters_and_transactions_but_no_stats(self):
        self.run_at("2026-10-19T09:00")
        self.assertTrue(self.store.exists("days/2026-10-18/roster_t1.xml"))
        self.assertTrue(self.store.exists("days/2026-10-18/transactions.xml"))
        self.assertEqual(self.api.count("/stats;"), 0)
        self.assertEqual(self.api.count("/scoreboard"), 0)
        self.assertEqual(self.api.count("/standings"), 0)

    def test_preseason_roster_failure_is_a_warning_and_moves_are_still_saved(self):
        # Before the draft (or for dates Yahoo will not serve) rosters may be refused.
        self.run_at("2026-10-19T09:00", FakeYahoo(fail=("/roster;",)))
        self.assertTrue(self.store.is_done("2026-10-18"))
        self.assertTrue(self.store.exists("days/2026-10-18/transactions.xml"))
        warnings = self.store.run_info("2026-10-18")["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("roster", warnings[0])

    def test_in_season_roster_failure_stops_the_run(self):
        self.store.mark_done("2026-10-20", {})
        with self.assertRaises(YahooError):
            self.run_at("2026-10-22T00:05", FakeYahoo(fail=("/roster;",)))
        self.assertFalse(self.store.is_done("2026-10-21"))

    def test_first_day_of_new_week_recollects_previous_week(self):
        for day in collect.date_range("2026-10-20", "2026-10-25"):
            self.store.mark_done(day, {"live": True})
        self.run_at("2026-10-27T00:05")  # stats day 10-26 = first day of week 2
        for day in collect.date_range("2026-10-20", "2026-10-25"):
            self.assertIn(f"team/{LEAGUE}.t.1/roster;date={day}", self.api.paths)
            self.assertTrue(self.store.exists(f"days/{day}/stats_01.xml"))
        self.assertTrue(self.store.exists("weeks/scoreboard_w01.xml"))
        self.assertTrue(self.store.exists("weeks/scoreboard_w02.xml"))

    def test_recollected_day_keeps_its_live_flag_and_notes_the_correction(self):
        for day in collect.date_range("2026-10-20", "2026-10-25"):
            self.store.mark_done(day, {"live": True})
        self.run_at("2026-10-27T00:05")
        info = self.store.run_info("2026-10-25")
        self.assertTrue(info["live"])
        self.assertIn("corrected_at", info)

    def test_failed_scoreboard_leaves_day_unfinished_so_next_run_retries(self):
        self.store.mark_done("2026-10-20", {})
        with self.assertRaises(YahooError):
            self.run_at("2026-10-22T00:05", FakeYahoo(fail=("/scoreboard",)))
        self.assertFalse(self.store.is_done("2026-10-21"))
        self.run_at("2026-10-22T01:05")
        self.assertTrue(self.store.is_done("2026-10-21"))
        self.assertTrue(self.store.exists("weeks/scoreboard_w01.xml"))

    def test_failed_week_correction_is_retried_on_the_next_run(self):
        for day in collect.date_range("2026-10-20", "2026-10-25"):
            self.store.mark_done(day, {"live": True})
        with self.assertRaises(YahooError):
            self.run_at("2026-10-27T00:05", FakeYahoo(fail=("roster;date=2026-10-24",)))
        self.assertFalse(self.store.is_done("2026-10-26"))
        summary = self.run_at("2026-10-27T01:05")
        self.assertIn("2026-10-25", summary["corrected"])
        self.assertTrue(self.store.is_done("2026-10-26"))

    def test_run_returns_summary_of_days_collected(self):
        self.store.mark_done("2026-10-20", {})
        summary = self.run_at("2026-10-22T00:05")
        self.assertEqual(summary["collected"], ["2026-10-21"])
        self.assertEqual(summary["corrected"], [])


class DraftTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = RawStore(Path(tmp.name))

    def test_draft_saves_results_and_player_details(self):
        api = FakeYahoo()
        collect.collect_draft(api, self.store, LEAGUE, prev_season=2025)
        self.assertTrue(self.store.exists("league/draftresults.xml"))
        self.assertTrue(self.store.exists("league/draft_players_01.xml"))
        self.assertTrue(self.store.exists("league/draft_prev_stats_01.xml"))
        self.assertIn(
            f"league/{LEAGUE}/players;player_keys=470.p.5352,470.p.6030/draft_analysis", api.paths
        )
        self.assertIn(
            f"league/{LEAGUE}/players;player_keys=470.p.5352,470.p.6030/stats;type=season;season=2025",
            api.paths,
        )

    def test_missing_previous_season_stats_is_a_warning_not_a_failure(self):
        api = FakeYahoo(fail=("/stats;type=season",))
        warnings = collect.collect_draft(api, self.store, LEAGUE, prev_season=2025)
        self.assertTrue(self.store.exists("league/draft_players_01.xml"))
        self.assertFalse(self.store.exists("league/draft_prev_stats_01.xml"))
        self.assertEqual(len(warnings), 1)

    def test_draft_before_it_happened_reports_no_picks(self):
        class Empty(FakeYahoo):
            def get(self, path):
                if path.endswith("/draftresults"):
                    self.paths.append(path)
                    return b'<fantasy_content><league><draft_results count="0"/></league></fantasy_content>'
                return super().get(path)

        api = Empty()
        warnings = collect.collect_draft(api, self.store, LEAGUE, prev_season=2025)
        self.assertEqual(api.count("/draft_analysis"), 0)
        self.assertIn("no draft picks", warnings[0].lower())


if __name__ == "__main__":
    unittest.main()
