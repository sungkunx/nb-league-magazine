import json
import re
import tempfile
import unittest
from pathlib import Path

from nbl import blog

SITE = {"title": "NB League 매거진", "season": "2026-27", "url": "https://example.github.io/mag"}


def post(title="제목", date="2026-10-26T22:00+09:00", kind="week-end", week=1, extra="", body="본문입니다."):
    lines = ["---", f"title: {title}", f"date: {date}", f"kind: {kind}"]
    if week is not None:
        lines.append(f"week: {week}")
    if extra:
        lines.append(extra)
    return "\n".join(lines + ["---", "", body, ""])


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.posts = self.root / "posts"
        self.posts.mkdir()
        self.facts = self.root / "facts"
        self.facts.mkdir()
        self.out = self.root / "site"

    def write(self, name, text):
        (self.posts / name).write_text(text, encoding="utf-8")

    def build(self):
        return blog.build(self.posts, self.out, SITE, self.facts)

    def page(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")


class PostTests(Base):
    def test_front_matter_and_body_are_separated(self):
        p = blog.parse_post(post(title="Week 1 최종 결과", extra="summary: 무승부의 역습"), "w01-end")
        self.assertEqual((p["title"], p["kind"], p["week"], p["summary"]), ("Week 1 최종 결과", "week-end", 1, "무승부의 역습"))
        self.assertEqual(p["slug"], "w01-end")
        self.assertEqual(p["body"].strip(), "본문입니다.")

    def test_title_may_contain_a_colon(self):
        self.assertEqual(blog.parse_post(post(title="Week 2: 운명의 갈림길"), "x")["title"], "Week 2: 운명의 갈림길")

    def test_missing_title_names_the_file(self):
        with self.assertRaises(blog.BlogError) as ctx:
            blog.parse_post("---\ndate: 2026-10-26T22:00+09:00\nkind: notice\n---\n본문", "broken-post")
        self.assertIn("broken-post", str(ctx.exception))
        self.assertIn("title", str(ctx.exception))

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(blog.BlogError):
            blog.parse_post(post(kind="weekly"), "x")

    def test_weekly_post_needs_a_week_number(self):
        with self.assertRaises(blog.BlogError) as ctx:
            blog.parse_post(post(kind="week-mid", week=None), "x")
        self.assertIn("week", str(ctx.exception))

    def test_bad_date_is_rejected(self):
        with self.assertRaises(blog.BlogError):
            blog.parse_post(post(date="어제"), "x")

    def test_text_without_front_matter_is_rejected(self):
        with self.assertRaises(blog.BlogError):
            blog.parse_post("그냥 글", "x")


class BuildTests(Base):
    def test_each_post_gets_its_own_page(self):
        self.write("w01-end.md", post(title="Week 1 최종 결과", body="## MVP\n\n**Jokić**"))
        self.build()
        html = self.page("posts/w01-end/index.html")
        self.assertIn("<h1>Week 1 최종 결과</h1>", html)
        self.assertIn("<h2>MVP</h2>", html)
        self.assertIn("<strong>Jokić</strong>", html)
        self.assertIn('<html lang="ko">', html)

    def test_index_groups_the_three_editions_of_a_week_in_order(self):
        self.write("w01-end.md", post(title="마지막 글", date="2026-10-26T22:00+09:00", kind="week-end"))
        self.write("w01-start.md", post(title="시작 글", date="2026-10-20T20:00+09:00", kind="week-start"))
        self.write("w01-mid.md", post(title="중간 글", date="2026-10-23T22:00+09:00", kind="week-mid"))
        self.build()
        html = self.page("index.html")
        self.assertLess(html.index("시작 글"), html.index("중간 글"))
        self.assertLess(html.index("중간 글"), html.index("마지막 글"))
        self.assertEqual(html.count('href="posts/w01-'), 3)
        self.assertIn("Week 1", re.sub(r"<[^>]+>", "", html))

    def test_newer_weeks_come_first(self):
        self.write("w01-end.md", post(title="일주차", week=1))
        self.write("w02-end.md", post(title="이주차", week=2, date="2026-11-02T22:00+09:00"))
        self.build()
        html = self.page("index.html")
        self.assertLess(html.index("이주차"), html.index("일주차"))

    def test_edition_not_written_yet_is_shown_as_upcoming(self):
        self.write("w01-start.md", post(title="시작 글", kind="week-start"))
        self.build()
        html = self.page("index.html")
        self.assertEqual(html.count("예정"), 3)

    def test_special_posts_sit_among_the_weeks_by_date(self):
        self.write("draft.md", post(title="드래프트 평가", kind="draft", week=None, date="2026-10-19T20:00+09:00"))
        self.write("w01-end.md", post(title="일주차 결과", week=1))
        self.build()
        html = self.page("index.html")
        self.assertLess(html.index("일주차 결과"), html.index("드래프트 평가"))
        self.assertIn('href="posts/draft/"', html)

    def test_empty_blog_says_so(self):
        self.build()
        self.assertIn("아직 발행된 글이 없습니다", self.page("index.html"))

    def test_post_page_links_to_neighbours_and_home(self):
        self.write("a.md", post(title="첫 글", date="2026-10-20T20:00+09:00", kind="week-start"))
        self.write("b.md", post(title="둘째 글", date="2026-10-23T20:00+09:00", kind="week-mid"))
        self.build()
        html = self.page("posts/b/index.html")
        self.assertIn('href="../a/"', html)
        self.assertIn("첫 글", html)
        self.assertIn('href="../../"', html)
        self.assertNotIn("둘째 글</a>", self.page("posts/b/index.html").split("</article>")[1])

    def test_sharing_tags_use_absolute_addresses(self):
        self.write("w01-mid.md", post(title="중간 점검", kind="week-mid",
                                      extra="summary: Cho가 4장을 다 썼다\ncover: images/w01-mid.png"))
        (self.posts / "images").mkdir()
        (self.posts / "images" / "w01-mid.png").write_bytes(b"\x89PNG fake")
        self.build()
        html = self.page("posts/w01-mid/index.html")
        self.assertIn('<meta property="og:title" content="중간 점검">', html)
        self.assertIn('<meta property="og:description" content="Cho가 4장을 다 썼다">', html)
        self.assertIn('<meta property="og:image" content="https://example.github.io/mag/images/w01-mid.png">', html)
        self.assertIn('<meta property="og:url" content="https://example.github.io/mag/posts/w01-mid/">', html)
        self.assertEqual((self.out / "images" / "w01-mid.png").read_bytes(), b"\x89PNG fake")
        self.assertIn('src="../../images/w01-mid.png"', html)

    def test_image_paths_in_the_body_are_fixed_for_the_post_page(self):
        self.write("a.md", post(body="![만평](images/a.png)"))
        (self.posts / "images").mkdir()
        (self.posts / "images" / "a.png").write_bytes(b"png")
        self.build()
        self.assertIn('src="../../images/a.png"', self.page("posts/a/index.html"))

    def test_cover_that_does_not_exist_stops_the_build(self):
        self.write("a.md", post(extra="cover: images/missing.png"))
        with self.assertRaises(blog.BlogError) as ctx:
            self.build()
        self.assertIn("missing.png", str(ctx.exception))

    def test_titles_are_escaped(self):
        self.write("a.md", post(title="A <b> & B"))
        self.build()
        self.assertIn("A &lt;b&gt; &amp; B", self.page("index.html"))
        self.assertNotIn("<b>", self.page("posts/a/index.html"))

    def test_rebuild_removes_pages_of_deleted_posts(self):
        self.write("a.md", post())
        self.build()
        (self.posts / "a.md").unlink()
        self.build()
        self.assertFalse((self.out / "posts" / "a").exists())

    def test_build_returns_the_number_of_posts_and_writes_supporting_files(self):
        self.write("a.md", post())
        self.assertEqual(self.build(), 1)
        self.assertTrue((self.out / "style.css").exists())
        self.assertTrue((self.out / ".nojekyll").exists())


class TableTests(Base):
    def sheet(self):
        (self.facts / "week-01.json").write_text(json.dumps({
            "standings": [
                {"rank": 1, "team": "Kharami", "record": "7-3-0", "pct": 0.7, "change": 2},
                {"rank": 2, "team": "Cho", "record": "5-4-1", "pct": 0.55, "change": -1},
                {"rank": 3, "team": "CHAN", "record": "3-7-0", "pct": 0.3, "change": None},
            ],
            "matchups": [{
                "teams": ["Cho", "Kharami"], "score": ["5-4-1", "4-5-1"], "winner": "Cho",
                "categories": [
                    {"name": "FG%", "values": [".499", ".446"], "made_attempted": ["182/365", "206/462"], "winner": "Cho"},
                    {"name": "PTS", "values": ["472", "472"], "winner": "tie"},
                ],
            }],
        }), encoding="utf-8")

    def test_standings_table_comes_from_the_fact_sheet(self):
        self.sheet()
        self.write("w01-end.md", post(body="순위입니다.\n\n{{standings}}\n\n끝."))
        self.build()
        html = self.page("posts/w01-end/index.html")
        self.assertIn("<td>Kharami</td>", html)
        self.assertIn("7-3-0", html)
        self.assertIn(".700", html)
        self.assertIn("▲2", html)
        self.assertIn("▼1", html)
        self.assertLess(html.index("순위입니다."), html.index("Kharami"))
        self.assertLess(html.index("Kharami"), html.index("끝."))

    def test_matchup_table_shows_score_and_marks_category_winners(self):
        self.sheet()
        self.write("w01-end.md", post(body="{{matchups}}"))
        self.build()
        html = self.page("posts/w01-end/index.html")
        self.assertIn("Cho 5-4-1 Kharami", html)
        self.assertIn('<td class="num win">.499</td>', html)
        self.assertIn('<td class="num">.446</td>', html)
        self.assertEqual(html.count('class="num tie"'), 2)

    def test_table_can_name_another_week(self):
        self.sheet()
        self.write("w02-start.md", post(kind="week-start", week=2, body="{{standings week=1}}"))
        self.build()
        self.assertIn("Kharami", self.page("posts/w02-start/index.html"))

    def test_table_without_its_fact_sheet_stops_the_build(self):
        self.write("w03-end.md", post(week=3, body="{{standings}}"))
        with self.assertRaises(blog.BlogError) as ctx:
            self.build()
        self.assertIn("week-03.json", str(ctx.exception))
        self.assertIn("w03-end", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class ReviewTests(Base):
    """A post with 'status: review' is built for reading but not listed yet."""

    def test_status_is_published_unless_the_header_says_review(self):
        self.assertEqual(blog.parse_post(post(), "a")["status"], "published")
        self.assertEqual(blog.parse_post(post(extra="status: review"), "a")["status"], "review")

    def test_unknown_status_is_rejected(self):
        with self.assertRaisesRegex(blog.BlogError, "a: status 'later'"):
            blog.parse_post(post(extra="status: later"), "a")

    def test_post_in_review_has_a_page_but_is_not_on_the_index(self):
        self.write("w01-end.md", post(title="검토 중인 글", extra="status: review"))
        self.assertEqual(self.build(), 0)
        self.assertNotIn("검토 중인 글", self.page("index.html"))
        self.assertIn("아직 발행된 글이 없습니다", self.page("index.html"))
        html = self.page("posts/w01-end/index.html")
        self.assertIn("<h1>검토 중인 글</h1>", html)
        self.assertIn('<meta name="robots" content="noindex">', html)
        self.assertIn('class="preview"', html)

    def test_published_page_has_no_preview_marks(self):
        self.write("w01-end.md", post())
        self.build()
        html = self.page("posts/w01-end/index.html")
        self.assertNotIn("noindex", html)
        self.assertNotIn('class="preview"', html)

    def test_published_posts_do_not_link_to_a_post_in_review(self):
        self.write("a.md", post(title="첫 글", date="2026-10-20T20:00+09:00", kind="week-start"))
        self.write("b.md", post(title="검토 글", date="2026-10-23T20:00+09:00", kind="week-mid", extra="status: review"))
        self.write("c.md", post(title="셋째 글", date="2026-10-26T20:00+09:00", kind="week-end"))
        self.build()
        self.assertNotIn("검토 글", self.page("posts/a/index.html"))
        self.assertIn('href="../c/"', self.page("posts/a/index.html"))
        self.assertIn('href="../a/"', self.page("posts/c/index.html"))
        self.assertIn("예정", self.page("index.html"))

    def test_publish_removes_the_review_line_and_nothing_else(self):
        text = post(title="검토 글", extra="status: review\nsummary: 한 줄", body="status: review 라는 본문")
        self.write("a.md", text)
        blog.publish(self.posts / "a.md")
        self.assertEqual((self.posts / "a.md").read_text(encoding="utf-8"), text.replace("status: review\n", "", 1))
        self.assertEqual(self.build(), 1)

    def test_publishing_a_post_that_is_not_in_review_is_an_error(self):
        self.write("a.md", post())
        with self.assertRaisesRegex(blog.BlogError, "a: is not waiting for review"):
            blog.publish(self.posts / "a.md")

    def test_kinds_need_review_unless_the_site_lists_them_as_automatic(self):
        self.assertTrue(blog.needs_review(SITE, "week-end"))
        site = dict(SITE, auto_publish=["week-start", "week-mid"])
        self.assertFalse(blog.needs_review(site, "week-start"))
        self.assertTrue(blog.needs_review(site, "week-end"))
        self.assertFalse(blog.needs_review(dict(SITE, auto_publish=["all"]), "playoff"))


class CartoonTests(Base):
    """The weekly cartoon is its own post: three pictures, a line under each."""

    def cartoon(self, pictures=3, **kw):
        (self.posts / "images").mkdir(exist_ok=True)
        body = []
        for n in range(1, pictures + 1):
            (self.posts / "images" / f"w01-cartoon-{n}.png").write_bytes(b"png")
            body += [f"![{n}번 만평](images/w01-cartoon-{n}.png)", "", f"{n}번 코멘트", ""]
        return post(title="1주차 만평", kind="week-cartoon", body="\n".join(body), **kw)

    def test_cartoon_is_the_fourth_slot_of_its_week(self):
        self.write("w01-end.md", post(title="결산 글"))
        self.write("w01-cartoon.md", self.cartoon(date="2026-10-26T22:30+09:00"))
        self.build()
        html = self.page("index.html")
        self.assertIn('class="ed ed-cartoon"', html)
        self.assertLess(html.index("결산 글"), html.index("1주차 만평"))
        self.assertEqual(html.count("<h2>"), 1)

    def test_cartoon_needs_a_week(self):
        with self.assertRaisesRegex(blog.BlogError, "needs 'week'"):
            blog.parse_post(post(kind="week-cartoon", week=None), "w01-cartoon")

    def test_cartoon_page_shows_each_picture_with_its_comment(self):
        self.write("w01-cartoon.md", self.cartoon())
        self.build()
        html = self.page("posts/w01-cartoon/index.html")
        self.assertIn('class="post kind-cartoon"', html)
        self.assertIn("Week 1 만평", html)
        self.assertEqual(html.count("<figure>"), 3)
        self.assertLess(html.index("w01-cartoon-2.png"), html.index("2번 코멘트"))
        self.assertLess(html.index("2번 코멘트"), html.index("w01-cartoon-3.png"))

    def test_first_picture_is_the_sharing_image_when_there_is_no_cover(self):
        self.write("w01-cartoon.md", self.cartoon())
        self.build()
        self.assertIn('<meta property="og:image" content="https://example.github.io/mag/images/w01-cartoon-1.png">',
                      self.page("posts/w01-cartoon/index.html"))

    def test_cartoon_with_the_wrong_number_of_pictures_stops_the_build(self):
        self.write("w01-cartoon.md", self.cartoon(pictures=2))
        with self.assertRaisesRegex(blog.BlogError, "w01-cartoon: a cartoon post has 3 pictures, this one has 2"):
            self.build()

    def test_picture_that_does_not_exist_stops_the_build(self):
        self.write("w01-end.md", post(body="![그림](images/nope.png)"))
        with self.assertRaisesRegex(blog.BlogError, "w01-end: images/nope.png does not exist"):
            self.build()


class ExtraTests(Base):
    """호외: an unscheduled special, with or without a week."""

    def test_extra_is_listed_among_the_weeks_and_labelled(self):
        self.write("w01-start.md", post(title="시작 글", kind="week-start", date="2026-10-20T20:00+09:00"))
        self.write("extra-1022.md", post(title="하루 4건의 트레이드", kind="extra", week=None,
                                         date="2026-10-22T18:00+09:00"))
        self.build()
        html = self.page("index.html")
        self.assertIn('<section class="special special-extra">', html)
        self.assertIn('<span class="tag">호외</span>', html)
        self.assertLess(html.index("하루 4건의 트레이드"), html.index("시작 글"))
        page = self.page("posts/extra-1022/index.html")
        self.assertIn('class="post kind-extra"', page)
        self.assertIn('<p class="tag">호외</p>', page)

    def test_extra_may_name_a_week_for_its_tables(self):
        self.assertEqual(blog.parse_post(post(kind="extra", week=3), "extra-1105")["week"], 3)


class TeamTests(Base):
    """Each league team gets a page gathering the posts that talk about it."""

    def sheet(self, week=1, teams=((4, "Cho"), (11, "Kharami"), (6, "CHAN"))):
        (self.facts / f"week-{week:02d}.json").write_text(json.dumps({
            "teams": [{"team_id": k, "team": n} for k, n in teams],
            "standings": [{"rank": i + 1, "team": n, "record": f"{9 - i}-{i}-0", "pct": 0.5, "change": None}
                          for i, (_, n) in enumerate(teams)],
            "matchups": [],
        }), encoding="utf-8")

    def test_index_links_to_every_team(self):
        self.sheet()
        self.write("w01-end.md", post(body="Cho가 이겼습니다."))
        self.build()
        html = self.page("index.html")
        self.assertIn('<details class="teams">', html)
        self.assertNotIn("<details class=\"teams\" open", html)
        self.assertIn("<summary>팀별로 보기</summary>", html)
        for number, name in (("4", "Cho"), ("11", "Kharami"), ("6", "CHAN")):
            self.assertIn(f'href="teams/{number}/"', html)
            self.assertIn(f">{name}<", html)
        self.assertLess(html.index(">CHAN<"), html.index(">Cho<"))
        self.assertLess(html.index(">Cho<"), html.index(">Kharami<"))

    def test_no_team_row_before_any_fact_sheet_names_teams(self):
        self.write("w01-end.md", post())
        self.build()
        self.assertNotIn('class="teams"', self.page("index.html"))
        self.assertFalse((self.out / "teams").exists())

    def test_team_page_lists_posts_that_mention_it_newest_first_with_the_passage(self):
        self.sheet()
        self.write("w01-start.md", post(title="시작 글", kind="week-start", date="2026-10-20T20:00+09:00",
                                        body="## 대진\n\n- **Cho** vs Kharami: 무난한 한 주가 될까요?\n\n다른 문단."))
        self.write("w01-end.md", post(title="결산 글", body="CHAN만 나오는 문단.\n\n그리고 **Cho**가 5-4-1로 이겼습니다!"))
        self.build()
        html = self.page("teams/4/index.html")
        self.assertIn("<h1>Cho</h1>", html)
        self.assertLess(html.index("결산 글"), html.index("시작 글"))
        self.assertIn('href="../../posts/w01-end/#team-4"', html)
        self.assertIn("그리고 Cho가 5-4-1로 이겼습니다!", html)
        self.assertIn("Cho vs Kharami: 무난한 한 주가 될까요?", html)
        self.assertNotIn("CHAN만 나오는", html)
        chan = self.page("teams/6/index.html")
        self.assertIn("결산 글", chan)
        self.assertNotIn("시작 글", chan)

    def test_post_gets_an_anchor_at_the_first_mention(self):
        self.sheet()
        self.write("w01-end.md", post(body="첫 문단.\n\n여기서 Cho가 처음 나오고 Cho가 또 나옵니다."))
        self.build()
        html = self.page("posts/w01-end/index.html")
        self.assertEqual(html.count('id="team-4"'), 1)
        self.assertIn('<span id="team-4"></span>Cho가 처음', html)

    def test_name_inside_a_longer_word_or_a_link_address_is_not_a_mention(self):
        self.sheet()
        self.write("w01-end.md", post(body="Chosen one. [기사](https://example.com/Cho) 그리고 CHANCE."))
        self.build()
        self.assertNotIn("team-4", self.page("posts/w01-end/index.html"))
        self.assertIn("아직 이 팀이 나온 글이 없습니다", self.page("teams/4/index.html"))
        self.assertIn("아직 이 팀이 나온 글이 없습니다", self.page("teams/6/index.html"))

    def test_name_followed_by_korean_particle_counts(self):
        self.sheet()
        self.write("w01-end.md", post(body="Kharami는 강했습니다."))
        self.build()
        self.assertIn("Kharami는 강했습니다.", self.page("teams/11/index.html"))

    def test_notices_and_posts_in_review_are_left_out(self):
        self.sheet()
        self.write("notice.md", post(title="안내 글", kind="notice", week=None, body="편집장 Cho에게 알려주세요."))
        self.write("w01-mid.md", post(title="검토 글", kind="week-mid", extra="status: review", body="Cho 이야기."))
        self.build()
        html = self.page("teams/4/index.html")
        self.assertNotIn("안내 글", html)
        self.assertNotIn("검토 글", html)

    def test_renamed_team_keeps_its_page_and_its_older_posts(self):
        self.sheet(1, teams=((4, "Cho"),))
        self.sheet(2, teams=((4, "Cho Dynasty"),))
        self.write("w01-end.md", post(title="일주차", week=1, body="Cho가 이겼습니다."))
        self.write("w02-end.md", post(title="이주차", week=2, date="2026-11-02T22:00+09:00", body="Cho Dynasty가 또 이겼습니다."))
        self.build()
        html = self.page("teams/4/index.html")
        self.assertIn("<h1>Cho Dynasty</h1>", html)
        self.assertIn("일주차", html)
        self.assertIn("이주차", html)
        self.assertEqual(self.page("index.html").count('href="teams/4/"'), 1)

    def test_team_page_shows_the_latest_record_when_there_is_a_rank(self):
        self.sheet()
        self.build()
        self.assertIn("1위", self.page("teams/4/index.html"))
        self.assertIn("9-0-0", self.page("teams/4/index.html"))

    def test_chip_shows_how_many_posts_a_team_has(self):
        self.sheet()
        self.write("w01-end.md", post(body="Cho가 이겼습니다."))
        self.build()
        html = self.page("index.html")
        self.assertRegex(html, r'href="teams/4/"[^>]*>Cho<span class="count">1</span>')
        self.assertRegex(html, r'href="teams/6/" class="none">CHAN<')
