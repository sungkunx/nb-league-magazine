import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nbl import web
from nbl.cli import main

REAL = Path(__file__).parent.parent / "data" / "2025" / "web"
PT = ZoneInfo("America/Los_Angeles")


def pt(text):
    return datetime.fromisoformat(text).replace(tzinfo=PT)


class PlanTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        self.root = Path(tmp) / "web"
        self.root.mkdir()

    def day(self, name, good=True):
        d = self.root / "days" / name
        d.mkdir(parents=True)
        text = web.seal([f"#nbl-day v2 base=/nba/1 date={name} teams=0", "C|PTS"])
        (d / "teams.txt").write_text(text if good else text.replace("PTS", "PTX"), encoding="utf-8")

    def week(self, number, start, end):
        d = self.root / "weeks"
        d.mkdir(exist_ok=True)
        s, e = (datetime.fromisoformat(x) for x in (start, end))
        (d / f"week-{number:02d}.txt").write_text(web.seal([
            f"#nbl-week v2 base=/nba/1 week={number}",
            f"W|{number}|{s:%a} {s.month}/{s.day}|{e:%a} {e.month}/{e.day}|7", "C|PTS",
        ]), encoding="utf-8")

    def plan(self, now, **kwargs):
        return web.plan(self.root, season=2026, season_start="2026-10-20", now=pt(now), **kwargs)

    def lineup(self, name):
        d = self.root / "days" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "lineup-pre.txt").write_text(
            web.seal([f"#nbl-day v2 base=/nba/1 date={name} teams=0", "C|PTS"]), encoding="utf-8")

    def test_plan_names_the_days_a_run_writes_to(self):
        p = self.plan("2026-10-22T07:00")
        self.assertEqual(p["yesterday"], "2026-10-21")
        self.assertEqual(p["lineup"], "2026-10-22")

    def test_no_night_lineup_before_opening_day_or_after_the_last_day(self):
        self.assertIsNone(self.plan("2026-10-19T07:00")["lineup"])
        self.assertEqual(self.plan("2026-10-20T07:00")["lineup"], "2026-10-20")
        self.assertIsNone(self.plan("2027-04-05T07:00", season_end="2027-04-04", max_days=0)["lineup"])

    def test_night_lineup_already_saved_is_not_asked_for_again(self):
        self.lineup("2026-10-22")
        self.assertIsNone(self.plan("2026-10-22T07:00")["lineup"])

    def test_days_after_the_season_are_not_collected(self):
        p = self.plan("2027-04-10T00:05", season_end="2027-04-04", max_days=400)
        self.assertEqual(p["days"][-1], "2027-04-04")

    def test_before_the_season_there_are_no_days_to_collect(self):
        p = self.plan("2026-10-19T09:00")
        self.assertEqual(p["days"], [])
        self.assertEqual(p["weeks"], [1])
        self.assertTrue(p["preseason"])

    def test_first_morning_collects_opening_day_and_weeks_one_and_two(self):
        p = self.plan("2026-10-21T00:05")
        self.assertEqual(p["days"], ["2026-10-20"])
        self.assertEqual(p["weeks"], [1, 2])
        self.assertFalse(p["preseason"])

    def test_days_already_saved_are_skipped(self):
        self.day("2026-10-20")
        self.assertEqual(self.plan("2026-10-22T00:05")["days"], ["2026-10-21"])

    def test_damaged_day_is_collected_again(self):
        self.day("2026-10-20", good=False)
        self.assertEqual(self.plan("2026-10-22T00:05")["days"], ["2026-10-20", "2026-10-21"])

    def test_missed_days_are_filled_oldest_first_up_to_the_limit(self):
        p = self.plan("2026-10-30T00:05", max_days=3)
        self.assertEqual(p["days"], ["2026-10-20", "2026-10-21", "2026-10-22"])
        self.assertEqual(p["behind"], 7)

    def test_day_still_in_progress_is_not_collected(self):
        self.day("2026-10-20")
        self.assertEqual(self.plan("2026-10-21T23:05")["days"], [])

    def test_week_numbers_come_from_saved_week_files(self):
        self.week(1, "2026-10-20", "2026-10-25")
        self.week(2, "2026-10-26", "2026-11-01")
        for d in ("20", "21", "22", "23", "24", "25", "26", "27"):
            self.day(f"2026-10-{d}")
        p = self.plan("2026-10-29T00:05")  # collecting Wed Oct 28, in week 2
        self.assertEqual(p["days"], ["2026-10-28"])
        self.assertEqual(p["weeks"], [2, 3])

    def test_finished_week_is_fetched_again_for_two_days_to_catch_corrections(self):
        self.week(1, "2026-10-20", "2026-10-25")
        self.week(2, "2026-10-26", "2026-11-01")
        for d in range(20, 26):
            self.day(f"2026-10-{d}")
        self.assertEqual(self.plan("2026-10-27T00:05")["weeks"], [1, 2, 3])  # target Mon Oct 26
        self.day("2026-10-26")
        self.assertEqual(self.plan("2026-10-28T00:05")["weeks"], [1, 2, 3])  # target Tue Oct 27
        self.day("2026-10-27")
        self.assertEqual(self.plan("2026-10-29T00:05")["weeks"], [2, 3])

    def test_week_after_the_last_known_one_is_estimated_in_seven_day_steps(self):
        self.week(1, "2026-10-20", "2026-10-25")
        p = self.plan("2026-11-04T00:05", max_days=20)  # target Nov 3 = estimated week 3
        self.assertIn(3, p["weeks"])
        self.assertIn(4, p["weeks"])


class CommandTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        self.data = Path(tmp) / "data"
        shutil.copytree(REAL, self.data / "web")
        self.config = Path(tmp) / "league.json"
        self.config.write_text(json.dumps({
            "season": 2025, "league_id": "48698", "data_dir": str(self.data), "source": "web",
            "web_base": "/2025/nba/48698", "web_time_zone": "Asia/Seoul", "season_start": "2025-10-21",
        }))

    def run_cli(self, *args):
        out = io.StringIO()
        code = main(["--config", str(self.config), *args], env={}, out=out)
        return code, out.getvalue()

    def test_verify_accepts_a_correct_file(self):
        code, text = self.run_cli("verify", str(self.data / "web" / "weeks" / "week-03.txt"))
        self.assertEqual(code, 0)
        self.assertIn("OK", text)

    def test_verify_rejects_a_miscopied_file_and_says_so(self):
        f = self.data / "web" / "weeks" / "week-03.txt"
        f.write_text(f.read_text(encoding="utf-8").replace("472", "427"), encoding="utf-8")
        code, text = self.run_cli("verify", str(f))
        self.assertEqual(code, 1)
        self.assertIn("checksum mismatch", text)

    def test_verify_reports_a_day_that_does_not_add_up(self):
        f = self.data / "web" / "days" / "2025-11-03" / "teams.txt"
        lines = f.read_text(encoding="utf-8").rstrip("\n").split("\n")[:-1]
        f.write_text(web.seal([l.replace("S|37/75|10/15|7|91|", "S|37/75|10/15|7|95|") for l in lines]),
                     encoding="utf-8")
        code, text = self.run_cli("verify", str(f))
        self.assertEqual(code, 1)
        self.assertIn("Yahoo shows 95", text)

    def test_sheets_builds_the_week_from_browser_data_without_any_secret(self):
        code, text = self.run_cli("sheets")
        self.assertEqual(code, 0)
        self.assertIn("week-03: 0 check(s)", text)
        sheet = json.loads((self.data / "facts" / "week-03.json").read_text(encoding="utf-8"))
        self.assertEqual(sheet["matchups"][0]["score"], ["5-5-0", "5-5-0"])
        self.assertIn("Jalen Brunson", (self.data / "facts" / "week-03.md").read_text(encoding="utf-8"))

    def test_sheets_prints_problems_found_while_loading(self):
        f = self.data / "web" / "days" / "2025-11-05" / "teams.txt"
        f.write_text(f.read_text(encoding="utf-8").replace("9/20", "9/21"), encoding="utf-8")
        _, text = self.run_cli("sheets")
        self.assertIn("PROBLEM 2025-11-05: checksum mismatch", text)

    def test_week_that_has_not_started_builds_a_sheet_with_pairings_only(self):
        # This season's real week 1 as collected before the draft: every value is a dash.
        this_year = Path(__file__).parent.parent / "data" / "2026" / "web"
        shutil.rmtree(self.data / "web")
        shutil.copytree(this_year, self.data / "web", ignore=shutil.ignore_patterns("days"))
        self.config.write_text(json.dumps({
            "season": 2026, "league_id": "80126", "data_dir": str(self.data), "source": "web",
            "web_base": "/nba/80126", "web_time_zone": "Asia/Seoul", "season_start": "2026-10-20",
        }))
        code, text = self.run_cli("sheets", "--week", "1")
        self.assertEqual(code, 0)
        self.assertIn("week-01: 0 check(s)", text)
        sheet = json.loads((self.data / "facts" / "week-01.json").read_text(encoding="utf-8"))
        self.assertEqual(sheet["meta"]["week_start"], "2026-10-20")
        self.assertEqual(len(sheet["matchups"]), 8)
        self.assertEqual(sheet["matchups"][3]["teams"], ["Cho", "Kharami"])
        self.assertEqual(sheet["matchups"][3]["score"], ["0-0-0", "0-0-0"])
        self.assertEqual(len(sheet["standings"]), 16)

    def test_collect_on_a_browser_league_does_not_call_the_api(self):
        # The nightly GitHub job still runs `collect`; it must not fail every night.
        code, text = self.run_cli("collect")
        self.assertEqual(code, 0)
        self.assertIn("browser", text)
        self.assertIn("week-03: 0 check(s)", text)

    def test_compact_script_is_the_readable_script_minus_comments_and_indentation(self):
        scripts = Path(__file__).parent.parent / "scripts"
        full = (scripts / "web_extract.js").read_text(encoding="utf-8").split("\n")
        want = [l.strip() for l in full if l.strip() and not l.strip().startswith("//")]
        got = (scripts / "web_extract.min.js").read_text(encoding="utf-8").rstrip("\n").split("\n")
        self.assertEqual(got, want)

    def test_plan_prints_what_to_collect(self):
        code, text = self.run_cli("plan", "--now", "2025-11-11T00:05-08:00")
        self.assertEqual(code, 0)
        self.assertIn("base: /2025/nba/48698", text)
        self.assertIn("days: 2025-10-21", text)
        self.assertIn("weeks:", text)
        self.assertIn("yesterday: 2025-11-10", text)
        self.assertIn("lineup: 2025-11-11", text)

    def test_night_lineup_file_is_loaded_and_compared_with_the_final_roster(self):
        # Pretend that on the night before Nov 5, Cho had Brunson on the bench and Bane starting.
        final = (self.data / "web" / "days" / "2025-11-05" / "teams.txt").read_text(encoding="utf-8")
        lines = [l for l in final.rstrip("\n").split("\n")[:-1] if not l.startswith("S|")]
        lines = [("|".join(l.split("|")[:5]) + "|-") if l.startswith("P|") else l for l in lines]
        lines = [l.replace("P|PG|6044|", "P|BN|6044|").replace("P|BN|6422|", "P|PG|6422|") for l in lines]
        pre = self.data / "web" / "days" / "2025-11-05" / "lineup-pre.txt"
        pre.write_text(web.seal(lines), encoding="utf-8")
        code, text = self.run_cli("verify", str(pre))
        self.assertEqual(code, 0, text)
        self.run_cli("sheets")
        sheet = json.loads((self.data / "facts" / "week-03.json").read_text(encoding="utf-8"))
        changes = {c["player"]: c for c in sheet["lineup_changes"]}
        self.assertEqual(set(changes), {"Jalen Brunson", "Desmond Bane"})
        self.assertEqual(changes["Jalen Brunson"]["change"], "started")
        self.assertEqual(changes["Jalen Brunson"]["line"]["PTS"], "23")
        self.assertEqual(changes["Desmond Bane"]["change"], "benched")
        self.assertEqual(sheet["checks"], [])


if __name__ == "__main__":
    unittest.main()
