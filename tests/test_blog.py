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

    def test_index_shows_start_result_cartoon_slots_and_lists_the_rest_of_the_week(self):
        self.write("w01-end.md", post(title="결과 글", date="2026-10-26T22:00+09:00", kind="week-end"))
        self.write("w01-start.md", post(title="시작 글", date="2026-10-20T20:00+09:00", kind="week-start"))
        self.write("w01-mid.md", post(title="점검 글", date="2026-10-23T22:00+09:00", kind="week-mid"))
        self.build()
        html = self.page("index.html")
        slots = html[html.index('<ol class="editions">'):html.index("</ol>", html.index('<ol class="editions">'))]
        self.assertIn("시작 글", slots)
        self.assertIn("결과 글", slots)
        self.assertNotIn("점검 글", slots)
        self.assertNotIn("ed-mid", slots)
        self.assertIn('<span class="ed-name">결과</span>', slots)
        week = html[html.index('<ol class="inweek">'):]
        self.assertIn('<span class="tag tag-mid">점검</span>', week)
        self.assertIn("점검 글", week)
        self.assertEqual(html.count('href="posts/w01-'), 3)
        self.assertIn("Week 1", re.sub(r"<[^>]+>", "", html))

    def test_posts_of_a_week_are_listed_in_date_order_inside_it(self):
        self.write("w01-start.md", post(title="시작 글", kind="week-start", date="2026-10-20T20:00+09:00"))
        self.write("b.md", post(title="둘째", kind="feature", date="2026-10-23T20:00+09:00"))
        self.write("a.md", post(title="첫째", kind="extra", date="2026-10-21T20:00+09:00"))
        self.write("w02-start.md", post(title="이주차", kind="week-start", week=2, date="2026-10-27T20:00+09:00"))
        self.build()
        html = self.page("index.html")
        week1 = html[html.index("시작 글"):]
        self.assertLess(week1.index("첫째"), week1.index("둘째"))
        self.assertLess(html.index("이주차"), html.index("첫째"))
        self.assertIn("이번 주 기사 · 2편", html)
        self.assertNotIn('class="special', html)

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
        self.assertEqual(html.count("예정"), 2)

    def test_preseason_posts_form_week_zero_without_slots(self):
        self.write("draft.md", post(title="드래프트 평가", kind="draft", week=None, date="2026-10-19T20:00+09:00"))
        self.write("moves.md", post(title="전날 줍줍", kind="preseason", week=None, date="2026-10-20T23:50+09:00"))
        self.write("w01-end.md", post(title="일주차 결과", week=1))
        self.build()
        html = self.page("index.html")
        self.assertLess(html.index("일주차 결과"), html.index("드래프트 평가"))
        zero = html[html.index("Week</span> 0"):]
        self.assertIn('<span class="week-sub">개막 전</span>', zero)
        self.assertIn("개막 전 기사 · 2편", zero)
        self.assertLess(zero.index("드래프트 평가"), zero.index("전날 줍줍"))
        self.assertNotIn("editions", zero)
        self.assertIn('href="posts/draft/"', html)

    def test_feature_waiver_and_extra_need_a_week(self):
        for kind in ("feature", "waiver", "extra"):
            with self.assertRaisesRegex(blog.BlogError, f"a {kind} post needs 'week'"):
                blog.parse_post(post(kind=kind, week=None), "x")

    def test_preseason_kinds_default_to_week_zero(self):
        for kind in ("draft", "preseason", "notice"):
            self.assertEqual(blog.parse_post(post(kind=kind, week=None), "x")["week"], 0)

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

    def test_extra_is_listed_inside_its_week_and_labelled(self):
        self.write("w01-start.md", post(title="시작 글", kind="week-start", date="2026-10-20T20:00+09:00"))
        self.write("extra-1022.md", post(title="하루 4건의 트레이드", kind="extra",
                                         date="2026-10-22T18:00+09:00"))
        self.build()
        html = self.page("index.html")
        self.assertIn('<span class="tag tag-extra">호외</span>', html)
        self.assertLess(html.index("시작 글"), html.index("하루 4건의 트레이드"))
        page = self.page("posts/extra-1022/index.html")
        self.assertIn('class="post kind-extra"', page)
        self.assertIn('<p class="tag">호외</p>', page)

    def test_feature_and_waiver_have_their_own_tags(self):
        self.write("injury.md", post(title="부상전문가", kind="feature", week=0, date="2026-10-19T18:00+09:00"))
        self.write("waiver-w01.md", post(title="고민되십니까", kind="waiver", week=1, date="2026-10-22T18:00+09:00"))
        self.build()
        html = self.page("index.html")
        self.assertIn('<span class="tag tag-special">특집</span>', html)
        self.assertIn('<span class="tag tag-waiver">웨이버</span>', html)
        self.assertLess(html.index("고민되십니까"), html.index("부상전문가"))
        self.assertIn('class="post kind-special"', self.page("posts/injury/index.html"))
        page = self.page("posts/waiver-w01/index.html")
        self.assertIn('class="post kind-waiver"', page)
        self.assertIn('<p class="tag">웨이버</p>', page)

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


class MastheadTests(Base):
    def test_index_title_keeps_its_last_word_on_its_own_line(self):
        self.build()
        self.assertIn('<span class="lead">NB League</span> <span>매거진</span>', self.page("index.html"))

    def test_byline_sits_beside_the_last_word_on_the_index_only(self):
        self.write("w01-end.md", post())
        blog.build(self.posts, self.out, dict(SITE, byline="by Cho <편집장>"), self.facts)
        self.assertIn('<span>매거진 <small class="by">by Cho &lt;편집장&gt;</small></span>', self.page("index.html"))
        self.assertNotIn('class="by"', self.page("posts/w01-end/index.html"))

    def test_one_word_title_is_left_alone(self):
        blog.build(self.posts, self.out, dict(SITE, title="매거진"), self.facts)
        self.assertIn('<a href="./">매거진</a>', self.page("index.html"))


class SearchTests(Base):
    """The index searches a list of every published post's text, in the browser."""

    def entries(self):
        return json.loads(self.page("search.json"))

    def test_search_list_holds_each_published_post_as_plain_text(self):
        self.write("w01-end.md", post(title="결산 글", body="## MVP\n\n**Jokić**가 [폭발](https://example.com/x)했습니다.\n\n- 둘째 줄"))
        self.write("w01-mid.md", post(title="검토 글", kind="week-mid", extra="status: review", body="비밀"))
        self.build()
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual((e["title"], e["url"], e["label"], e["date"]), ("결산 글", "posts/w01-end/", "Week 1 결과", "10.26"))
        self.assertEqual(e["text"], "MVP Jokić가 폭발했습니다. 둘째 줄")

    def test_newest_post_comes_first_in_the_search_list(self):
        self.write("a.md", post(title="먼저", kind="week-start", date="2026-10-20T20:00+09:00"))
        self.write("b.md", post(title="나중", date="2026-10-26T22:00+09:00"))
        self.build()
        self.assertEqual([e["title"] for e in self.entries()], ["나중", "먼저"])

    def test_table_shortcodes_and_picture_lines_are_not_search_text(self):
        (self.facts / "week-01.json").write_text(json.dumps({"standings": [], "matchups": []}), encoding="utf-8")
        (self.posts / "images").mkdir()
        (self.posts / "images" / "a.png").write_bytes(b"png")
        self.write("w01-end.md", post(body="앞\n\n{{standings}}\n\n![그림 설명](images/a.png)\n\n뒤"))
        self.build()
        self.assertEqual(self.entries()[0]["text"], "앞 뒤")

    def test_index_has_the_search_box_and_its_script(self):
        self.build()
        html = self.page("index.html")
        self.assertIn('<input type="search" id="q"', html)
        self.assertIn('<script src="search.js" defer></script>', html)
        self.assertTrue((self.out / "search.js").exists())

    def test_post_pages_do_not_load_the_search_script(self):
        self.write("w01-end.md", post())
        self.build()
        self.assertNotIn("search.js", self.page("posts/w01-end/index.html"))


class ImageSizeTests(unittest.TestCase):
    def test_heavy_images_lists_only_files_over_the_limit_largest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            images = Path(tmp) / "images"
            (images / "w01").mkdir(parents=True)
            (images / "a.png").write_bytes(b"x" * 300)
            (images / "w01" / "b.png").write_bytes(b"x" * 500)
            (images / "c.jpg").write_bytes(b"x" * 100)
            self.assertEqual(blog.heavy_images(tmp, limit=200),
                             [("images/w01/b.png", 500), ("images/a.png", 300)])

    def test_heavy_images_is_empty_without_an_images_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(blog.heavy_images(tmp), [])

    def test_the_default_limit_is_one_megabyte(self):
        self.assertEqual(blog.IMAGE_LIMIT, 1024 * 1024)


DRAFT = {
    "picks": [
        {"pick": 1, "round": 1, "team": "Alpha", "player": "Nikola Jokić", "nba_team": "DEN", "position": "C"},
        {"pick": 2, "round": 1, "team": "Bravo", "player": "Victor Wembanyama", "nba_team": "SAS", "position": "C"},
        {"pick": 3, "round": 2, "team": "Bravo", "player": "Luka Dončić", "nba_team": "LAL", "position": "PG,SG"},
        {"pick": 4, "round": 2, "team": "Alpha", "player": "Kyrie Irving", "nba_team": "DAL", "position": "PG"},
    ],
}


class GuideTests(Base):
    def guide(self, extra="", body="## 규칙\n\n{{teams}}\n\n{{draft}}"):
        self.write("guide.md", post(title="26-27 NB 리그 가이드", kind="guide", week=None, extra=extra, body=body))
        (self.facts / "draft.json").write_text(json.dumps(DRAFT, ensure_ascii=False), encoding="utf-8")

    def test_published_guide_is_linked_from_the_legend_and_not_listed_as_a_post(self):
        self.guide()
        self.write("w01-end.md", post(title="결산"))
        self.assertEqual(self.build(), 1)
        html = self.page("index.html")
        legend = html[html.index('class="legend"'):html.index("</p>", html.index('class="legend"'))]
        self.assertIn('href="posts/guide/"', legend)
        self.assertIn("26-27 NB 리그 가이드", legend)
        self.assertNotIn("special-guide", html)
        self.assertNotIn("guide", self.page("posts/w01-end/index.html").split('class="neighbours"')[1])

    def test_guide_is_reached_only_through_its_link_not_search(self):
        self.guide()
        self.build()
        self.assertNotIn("posts/guide/", self.page("search.json"))

    def test_guide_in_review_is_not_linked(self):
        self.guide(extra="status: review")
        self.build()
        self.assertNotIn("posts/guide/", self.page("index.html"))
        self.assertIn("미리보기", self.page("posts/guide/index.html"))

    def test_teams_lists_every_team_in_first_round_order(self):
        self.guide()
        self.build()
        html = self.page("posts/guide/index.html")
        teams = html[html.index('class="roster"'):]
        self.assertLess(teams.index("Alpha"), teams.index("Bravo"))

    def test_draft_shows_each_team_with_its_picks_in_order(self):
        self.guide()
        self.build()
        html = self.page("posts/guide/index.html")
        board = html[html.index('class="draftboard"'):]
        self.assertIn("Nikola Jokić", board)
        alpha = board[board.index("Alpha"):board.index("Bravo")]
        self.assertLess(alpha.index("Nikola Jokić"), alpha.index("Kyrie Irving"))
        self.assertIn("DAL", alpha)

    def test_draft_shortcode_without_a_draft_sheet_fails_clearly(self):
        self.write("guide.md", post(title="가이드", kind="guide", week=None, body="{{draft}}"))
        with self.assertRaises(blog.BlogError) as ctx:
            self.build()
        self.assertIn("draft.json", str(ctx.exception))

    def test_guide_does_not_count_as_a_team_mention(self):
        self.guide()
        week = {"teams": [{"team_id": 1, "team": "Alpha"}]}
        (self.facts / "week-01.json").write_text(json.dumps(week), encoding="utf-8")
        self.build()
        self.assertIn("아직 이 팀이 나온 글이 없습니다", self.page("teams/1/index.html"))


class FloatNavTests(Base):
    def test_every_page_has_home_and_back_to_top_buttons(self):
        self.write("w01-end.md", post(title="결산"))
        self.build()
        for rel, home in [("index.html", "./"), ("posts/w01-end/index.html", "../../")]:
            html = self.page(rel)
            nav = html[html.index('class="float-nav"'):]
            self.assertIn(f'href="{home}"', nav[:400])
            self.assertIn('class="to-top"', nav[:600])
            self.assertLess(nav.index("float-home"), nav.index("to-top"))  # home sits above the top button
