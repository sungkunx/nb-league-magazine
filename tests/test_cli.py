import io
import json
import tempfile
import unittest
from pathlib import Path

from nbl.cli import main
from tests.fakes import FakeYahoo

ENV = {"YAHOO_CLIENT_ID": "id", "YAHOO_CLIENT_SECRET": "secret", "YAHOO_REFRESH_TOKEN": "refresh"}


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"
        self.config = self.root / "league.json"
        self.config.write_text(json.dumps({"season": 2026, "league_id": "80126", "data_dir": str(self.data)}))
        self.api = FakeYahoo()

    def run_cli(self, *args, env=ENV, api=None):
        out = io.StringIO()
        code = main(["--config", str(self.config), *args], env=env, api=api or self.api, out=out)
        return code, out.getvalue()

    def test_smoke_prints_league_teams_and_categories(self):
        code, text = self.run_cli("smoke")
        self.assertEqual(code, 0)
        self.assertIn("470.l.80126", text)
        self.assertIn("NB League 2026", text)
        self.assertIn("Cho", text)
        self.assertIn("FG%", text)

    def test_smoke_saves_sample_responses_for_inspection(self):
        self.run_cli("smoke")
        saved = sorted(p.name for p in (self.data / "raw" / "samples").iterdir())
        self.assertEqual(saved, [
            "game_weeks.xml.gz", "roster.xml.gz", "scoreboard.xml.gz", "settings.xml.gz",
            "standings.xml.gz", "stats.xml.gz", "teams.xml.gz", "transactions.xml.gz",
        ])

    def test_discover_lists_leagues_of_every_season(self):
        code, text = self.run_cli("discover")
        self.assertEqual(code, 0)
        self.assertIn("2025  466.l.12345  NB League 2025", text)
        self.assertIn("2026  470.l.80126  NB League 2026", text)

    def test_collect_saves_the_finished_day(self):
        code, text = self.run_cli("collect", "--now", "2026-10-22T00:05-07:00")
        self.assertEqual(code, 0)
        self.assertTrue((self.data / "raw" / "days" / "2026-10-21" / "run.json").exists())
        self.assertIn("2026-10-21", text)

    def test_collect_also_writes_fact_sheets(self):
        self.run_cli("collect", "--now", "2026-10-22T00:05-07:00")
        sheet = json.loads((self.data / "facts" / "week-01.json").read_text(encoding="utf-8"))
        self.assertEqual(sheet["meta"]["week"], 1)
        self.assertEqual(sheet["meta"]["through"], "2026-10-21")
        self.assertIn("Week 1", (self.data / "facts" / "week-01.md").read_text(encoding="utf-8"))

    def test_sheets_can_rebuild_one_named_week(self):
        self.run_cli("collect", "--now", "2026-10-22T00:05-07:00")
        (self.data / "facts" / "week-01.md").unlink()
        code, text = self.run_cli("sheets", "--week", "1")
        self.assertEqual(code, 0)
        self.assertTrue((self.data / "facts" / "week-01.md").exists())
        self.assertIn("week-01", text)

    def test_sheets_reports_how_many_data_checks_failed(self):
        self.run_cli("collect", "--now", "2026-10-22T00:05-07:00")
        _, text = self.run_cli("sheets", "--week", "1")
        self.assertRegex(text, r"week-01: \d+ check")

    def test_sheets_before_anything_is_collected_succeeds_quietly(self):
        code, text = self.run_cli("sheets")
        self.assertEqual(code, 0)
        self.assertIn("nothing collected yet", text)

    def test_preseason_moves_get_their_own_sheet(self):
        self.run_cli("collect", "--now", "2026-10-22T00:05-07:00")
        pre = json.loads((self.data / "facts" / "preseason.json").read_text(encoding="utf-8"))
        self.assertEqual(pre["transactions"], [])  # fixture moves are all in season

    def test_draft_saves_results_and_writes_the_draft_sheet(self):
        code, _ = self.run_cli("draft")
        self.assertEqual(code, 0)
        text = (self.data / "facts" / "draft.md").read_text(encoding="utf-8")
        self.assertIn("Nikola Jokic", text)

    def test_draft_before_it_happened_explains_and_fails(self):
        class NoDraft(FakeYahoo):
            def get(self, path):
                if path.endswith("/draftresults"):
                    return b"<fantasy_content><league><draft_results/></league></fantasy_content>"
                return super().get(path)

        code, text = self.run_cli("draft", api=NoDraft())
        self.assertEqual(code, 1)
        self.assertIn("No draft picks yet", text)
        self.assertFalse((self.data / "facts" / "draft.md").exists())

    def test_blog_builds_the_site_from_posts_without_any_secret(self):
        posts = self.root / "posts"
        posts.mkdir()
        (posts / "hello.md").write_text(
            "---\ntitle: 첫 글\ndate: 2026-10-19T20:00+09:00\nkind: notice\n---\n\n안녕하세요.\n", encoding="utf-8")
        site = self.root / "site.json"
        site.write_text(json.dumps({
            "title": "NB League 매거진", "season": "2026-27", "url": "https://example.github.io/mag",
            "posts_dir": str(posts), "facts_dir": str(self.data / "facts"), "out_dir": str(self.root / "out"),
        }))
        out = io.StringIO()
        code = main(["--config", str(self.config), "blog", "--site", str(site)], env={}, out=out)
        self.assertEqual(code, 0)
        self.assertIn("1 post", out.getvalue())
        self.assertIn("첫 글", (self.root / "out" / "index.html").read_text(encoding="utf-8"))

    def test_blog_reports_a_broken_post_and_fails(self):
        posts = self.root / "posts"
        posts.mkdir()
        (posts / "bad.md").write_text("---\ntitle: 제목만\n---\n", encoding="utf-8")
        site = self.root / "site.json"
        site.write_text(json.dumps({
            "title": "t", "season": "s", "url": "https://example.github.io/mag",
            "posts_dir": str(posts), "facts_dir": str(self.data / "facts"), "out_dir": str(self.root / "out"),
        }))
        out = io.StringIO()
        code = main(["--config", str(self.config), "blog", "--site", str(site)], env={}, out=out)
        self.assertEqual(code, 1)
        self.assertIn("bad", out.getvalue())

    def _review_site(self, header_extra="status: review\n"):
        posts = self.root / "posts"
        posts.mkdir()
        (posts / "w01-end.md").write_text(
            "---\ntitle: 결산\ndate: 2026-10-26T22:00+09:00\nkind: week-end\nweek: 1\n" + header_extra
            + "---\n\n본문.\n", encoding="utf-8")
        site = self.root / "site.json"
        site.write_text(json.dumps({
            "title": "t", "season": "s", "url": "https://example.github.io/mag",
            "posts_dir": str(posts), "facts_dir": str(self.data / "facts"), "out_dir": str(self.root / "out"),
        }))
        return posts, site

    def test_blog_names_posts_waiting_for_review(self):
        _, site = self._review_site()
        out = io.StringIO()
        code = main(["--config", str(self.config), "blog", "--site", str(site)], env={}, out=out)
        self.assertEqual(code, 0)
        self.assertIn("built 0 post(s)", out.getvalue())
        self.assertIn("waiting for review: https://example.github.io/mag/posts/w01-end/", out.getvalue())

    def test_blog_warns_about_images_over_the_size_limit(self):
        posts, site = self._review_site(header_extra="")
        (posts / "images").mkdir()
        (posts / "images" / "big.png").write_bytes(b"x" * (1024 * 1024 + 1))
        (posts / "images" / "small.jpg").write_bytes(b"x" * 1000)
        out = io.StringIO()
        code = main(["--config", str(self.config), "blog", "--site", str(site)], env={}, out=out)
        self.assertEqual(code, 0)
        self.assertIn("WARNING: images/big.png is 1.0 MB", out.getvalue())
        self.assertNotIn("small.jpg", out.getvalue())

    def test_publish_takes_a_post_out_of_review(self):
        posts, site = self._review_site()
        out = io.StringIO()
        code = main(["--config", str(self.config), "publish", "w01-end", "--site", str(site)], env={}, out=out)
        self.assertEqual(code, 0)
        self.assertNotIn("status", (posts / "w01-end.md").read_text(encoding="utf-8"))
        self.assertIn("published w01-end", out.getvalue())

    def test_publish_fails_for_a_post_that_is_not_in_review_or_missing(self):
        _, site = self._review_site(header_extra="")
        for slug in ("w01-end", "nope"):
            out = io.StringIO()
            code = main(["--config", str(self.config), "publish", slug, "--site", str(site)], env={}, out=out)
            self.assertEqual(code, 1)
            self.assertIn(slug, out.getvalue())

    def test_missing_secret_is_named_without_calling_yahoo(self):
        env = {k: v for k, v in ENV.items() if k != "YAHOO_REFRESH_TOKEN"}
        out = io.StringIO()
        code = main(["--config", str(self.config), "collect"], env=env, out=out)
        self.assertEqual(code, 2)
        self.assertIn("YAHOO_REFRESH_TOKEN", out.getvalue())

    def test_yahoo_failure_is_reported_as_an_error_exit(self):
        code, text = self.run_cli("smoke", api=FakeYahoo(fail=("/settings",)))
        self.assertEqual(code, 1)
        self.assertIn("HTTP 400", text)


if __name__ == "__main__":
    unittest.main()
