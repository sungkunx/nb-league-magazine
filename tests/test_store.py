import tempfile
import unittest
from pathlib import Path

from nbl.store import RawStore


class RawStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = RawStore(self.root)

    def test_saved_response_reads_back_unchanged(self):
        self.store.save("league/settings.xml", b"<a>\xed\x95\x9c</a>")
        self.assertEqual(self.store.load("league/settings.xml"), b"<a>\xed\x95\x9c</a>")

    def test_files_are_gzip_compressed_on_disk(self):
        self.store.save("league/settings.xml", b"<a/>" * 1000)
        on_disk = (self.root / "league" / "settings.xml.gz").read_bytes()
        self.assertEqual(on_disk[:2], b"\x1f\x8b")
        self.assertLess(len(on_disk), 400)

    def test_same_content_saved_twice_is_byte_identical(self):
        # Keeps git history quiet when a day is re-collected and nothing changed.
        self.store.save("a.xml", b"<same/>")
        first = (self.root / "a.xml.gz").read_bytes()
        self.store.save("a.xml", b"<same/>")
        self.assertEqual((self.root / "a.xml.gz").read_bytes(), first)

    def test_exists(self):
        self.assertFalse(self.store.exists("a.xml"))
        self.store.save("a.xml", b"x")
        self.assertTrue(self.store.exists("a.xml"))

    def test_day_is_done_only_after_being_marked(self):
        self.store.save("days/2026-10-21/teams.xml", b"x")
        self.assertFalse(self.store.is_done("2026-10-21"))
        self.store.mark_done("2026-10-21", {"calls": 3, "warnings": ["w"]})
        self.assertTrue(self.store.is_done("2026-10-21"))
        self.assertEqual(self.store.run_info("2026-10-21")["warnings"], ["w"])

    def test_done_dates_are_sorted(self):
        for day in ("2026-10-22", "2026-10-21"):
            self.store.mark_done(day, {})
        self.store.save("days/2026-10-23/teams.xml", b"x")  # collected but not finished
        self.assertEqual(self.store.done_dates(), ["2026-10-21", "2026-10-22"])

    def test_day_files_lists_response_names_in_order(self):
        self.store.save("days/2026-10-21/stats_02.xml", b"x")
        self.store.save("days/2026-10-21/roster_t1.xml", b"x")
        self.store.mark_done("2026-10-21", {})
        self.assertEqual(
            self.store.day_files("2026-10-21"),
            ["days/2026-10-21/roster_t1.xml", "days/2026-10-21/stats_02.xml"],
        )

    def test_files_lists_one_folder_in_order(self):
        self.store.save("weeks/scoreboard_w02.xml", b"x")
        self.store.save("weeks/scoreboard_w01.xml", b"x")
        self.store.save("league/settings.xml", b"x")
        self.assertEqual(
            self.store.files("weeks"),
            ["weeks/scoreboard_w01.xml", "weeks/scoreboard_w02.xml"],
        )
        self.assertEqual(self.store.files("nothing-here"), [])

    def test_clear_day_removes_old_responses_and_done_mark(self):
        self.store.save("days/2026-10-21/roster_t9.xml", b"x")
        self.store.mark_done("2026-10-21", {})
        self.store.clear_day("2026-10-21")
        self.assertEqual(self.store.day_files("2026-10-21"), [])
        self.assertFalse(self.store.is_done("2026-10-21"))


if __name__ == "__main__":
    unittest.main()
