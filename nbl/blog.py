"""Static blog built from posts/*.md.

A post is a Markdown file with a short header:

    ---
    title: Week 1 최종 결과
    date: 2026-10-26T22:00+09:00
    kind: week-end            # week-start | week-mid | week-end | week-cartoon |
                              # draft | preseason | playoff | extra | feature | waiver | notice
    week: 1                   # weekly posts (optional for the others)
    summary: 카톡 미리보기에 뜨는 한 줄
    cover: images/w01-end.png # optional; lives in <posts>/images/
    status: review            # optional; the post waits for the editor's OK
    ---

A post in review gets its page (marked as a preview, hidden from search
engines) but is left off the index and out of the other posts' links.
"python -m nbl publish <slug>" removes the line.

In the body, a line holding only {{standings}} or {{matchups}} (optionally
"week=N") becomes a table taken from that week's fact sheet.

A week-cartoon post is three pictures, each followed by one line of comment.

Every league team named in the fact sheets gets a page (teams/<number>/)
listing the published posts whose text mentions it, with the passage. Team
names are found in the text; nothing is tagged by hand.

The index has a search box. It reads search.json (every published post as
plain text) in the browser; there is no server.
"""
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import markdown

EDITIONS = {"week-start": "시작", "week-mid": "중간", "week-end": "마지막", "week-cartoon": "만평"}
SPECIALS = {"draft": "드래프트", "preseason": "개막 전", "playoff": "플레이오프", "extra": "호외",
            "feature": "특집", "waiver": "웨이버", "notice": "안내", "guide": "가이드"}
OWN_COLOUR = ("extra", "waiver")  # specials painted in their own colour; the rest share --special
GUIDE = "guide"  # one standing page, linked from the legend instead of listed among the posts
CARTOON_PICTURES = 3
_PICTURE = re.compile(r"!\[[^\]]*\]\((images/[^)\s]+)\)")
KINDS = {**EDITIONS, **SPECIALS}
_SHORTCODE = re.compile(r"^\{\{\s*(standings|matchups|draft|teams)(?:\s+week=(\d+))?\s*\}\}$")
STYLE = Path(__file__).with_name("blog.css")
SEARCH = Path(__file__).with_name("search.js")


class BlogError(Exception):
    pass


def esc(value):
    return html.escape(str(value), quote=True)


def parse_post(text, slug):
    lines = text.replace("\r\n", "\n").split("\n")
    if lines[0].strip() != "---" or "---" not in [l.strip() for l in lines[1:]]:
        raise BlogError(f"{slug}: the post must start with a header between two '---' lines")
    end = [l.strip() for l in lines[1:]].index("---") + 1
    meta = {}
    for line in lines[1:end]:
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    for key in ("title", "date", "kind"):
        if not meta.get(key):
            raise BlogError(f"{slug}: header is missing '{key}'")
    if meta["kind"] not in KINDS:
        raise BlogError(f"{slug}: kind '{meta['kind']}' is not one of {', '.join(KINDS)}")
    try:
        date = datetime.fromisoformat(meta["date"])
    except ValueError:
        raise BlogError(f"{slug}: date '{meta['date']}' is not like 2026-10-26T22:00+09:00") from None
    week = None
    if meta.get("week"):
        if not meta["week"].isdigit():
            raise BlogError(f"{slug}: week '{meta['week']}' is not a number")
        week = int(meta["week"])
    if meta["kind"] in EDITIONS and week is None:
        raise BlogError(f"{slug}: a {meta['kind']} post needs 'week'")
    status = meta.get("status") or "published"
    if status not in ("published", "review"):
        raise BlogError(f"{slug}: status '{status}' is not 'review' (leave the line out to publish)")
    return {
        "status": status,
        "slug": slug, "title": meta["title"], "date": date, "kind": meta["kind"], "week": week,
        "summary": meta.get("summary", ""), "cover": meta.get("cover", ""),
        "body": "\n".join(lines[end + 1:]),
    }


def load_posts(posts_dir):
    posts = [parse_post(f.read_text(encoding="utf-8"), f.stem) for f in sorted(Path(posts_dir).glob("*.md"))]
    return sorted(posts, key=lambda p: (p["date"].timestamp(), p["slug"]))


def needs_review(site, kind):
    """Whether a new post of this kind waits for the editor (site "auto_publish")."""
    auto = site.get("auto_publish") or []
    return "all" not in auto and kind not in auto


def publish(path):
    """Take a post out of review by removing its status line."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if parse_post(text, path.stem)["status"] != "review":
        raise BlogError(f"{path.stem}: is not waiting for review")
    lines = text.split("\n")
    end = [l.strip() for l in lines[1:]].index("---") + 1
    for i in range(1, end):
        if lines[i].split(":", 1)[0].strip() == "status":
            del lines[i]
            break
    path.write_text("\n".join(lines), encoding="utf-8")


# ---- league teams ---------------------------------------------------------

_LINK_TARGET = re.compile(r"\]\([^)\s]*\)")
_MARKS = re.compile(r"\*\*|\*|`|^\s*(?:[-*]|\d+\.|#{1,6}|>)\s+")
TEAMLESS = ("notice", GUIDE)  # kinds that are not about what teams did


def load_teams(facts_dir):
    """Teams from the weekly fact sheets, by league number: the current name,
    every name the team has had (older posts use older names), latest standing."""
    teams = {}
    for path in sorted(Path(facts_dir).glob("week-*.json")):
        sheet = json.loads(path.read_text(encoding="utf-8"))
        standing = {s["team"]: s for s in sheet.get("standings", [])}
        for t in sheet.get("teams", []):
            if t.get("team_id") is None:
                continue
            team = teams.setdefault(t["team_id"], {"id": t["team_id"], "names": []})
            team["name"] = t["team"]
            if t["team"] not in team["names"]:
                team["names"].append(t["team"])
            row = standing.get(t["team"], {})
            team["rank"], team["record"] = row.get("rank"), row.get("record")
    return sorted(teams.values(), key=lambda t: t["name"].casefold())


def _name_pattern(names, escape=lambda n: n):
    longest_first = sorted(names, key=len, reverse=True)
    return re.compile("(?<![A-Za-z0-9])(?:" + "|".join(re.escape(escape(n)) for n in longest_first)
                      + ")(?![A-Za-z0-9])")


def passage(body, team):
    """The first line of the post that names the team, as plain text; or None."""
    pattern = _name_pattern(team["names"])
    for line in body.split("\n"):
        if _SHORTCODE.match(line.strip()):
            continue
        text = _LINK_TARGET.sub("]", line)
        if pattern.search(text):
            text = _MARKS.sub("", text).replace("[", "").replace("]", "").strip()
            return text if len(text) <= 200 else text[:199].rstrip() + "…"
    return None


_PICTURE_ANY = re.compile(r"!\[[^\]]*\]\([^)\s]*\)")


def plain_text(body):
    """A post's words without Markdown marks, tables' rules, pictures or shortcodes."""
    words = []
    for line in body.split("\n"):
        line = line.strip()
        if not line or _SHORTCODE.match(line) or markdown._TABLE_RULE.match(line) or markdown._RULE.match(line):
            continue
        line = _LINK_TARGET.sub("]", _PICTURE_ANY.sub("", line))
        line = _MARKS.sub("", line).replace("[", "").replace("]", "").replace("|", " ")
        words.extend(line.split())
    return " ".join(words)


def search_entries(posts):
    return [{"title": p["title"], "url": f'posts/{p["slug"]}/', "label": _label(p), "date": _day(p["date"]),
             "text": plain_text(p["body"])} for p in reversed(posts)]


def _anchor(body_html, team):
    """Mark the first place the team is named in the text of the page."""
    pattern = _name_pattern(team["names"], lambda n: html.escape(n, quote=True))
    for m in pattern.finditer(body_html):
        if body_html.rfind("<", 0, m.start()) <= body_html.rfind(">", 0, m.start()):
            return f'{body_html[:m.start()]}<span id="team-{team["id"]}"></span>{body_html[m.start():]}'
    return body_html


# ---- tables from the fact sheet ------------------------------------------

def _pct(value):
    if value is None:
        return "–"
    text = f"{value:.3f}"
    return text[1:] if text.startswith("0") else text


def _change(value):
    if value is None:
        return ""
    if value == 0:
        return "–"
    return f"▲{value}" if value > 0 else f"▼{-value}"


def standings_html(sheet):
    rows = "\n".join(
        f'<tr><td class="num">{esc(s["rank"] if s["rank"] is not None else "–")}</td><td>{esc(s["team"])}</td>'
        f'<td class="num">{esc(s["record"])}</td><td class="num">{_pct(s.get("pct"))}</td>'
        f'<td class="num">{_change(s.get("change"))}</td></tr>'
        for s in sheet["standings"]
    )
    return ('<div class="table"><table class="standings">\n<thead><tr><th class="num">순위</th><th>팀</th>'
            '<th class="num">전적</th><th class="num">승률</th><th class="num">변동</th></tr></thead>\n'
            f"<tbody>\n{rows}\n</tbody>\n</table></div>")


def matchups_html(sheet):
    out = []
    for m in sheet["matchups"]:
        a, b = m["teams"]
        rows = []
        for c in m["categories"]:
            cells = []
            for team, value in zip((a, b), c["values"]):
                cls = "num tie" if c["winner"] == "tie" else "num win" if c["winner"] == team else "num"
                cells.append(f'<td class="{cls}">{esc(value if value is not None else "–")}</td>')
            rows.append(f"<tr><td>{esc(c['name'])}</td>{''.join(cells)}</tr>")
        out.append(
            f'<div class="table"><table class="matchup">\n<caption>{esc(a)} {esc(m["score"][0])} {esc(b)}</caption>\n'
            f'<thead><tr><th>카테고리</th><th class="num">{esc(a)}</th><th class="num">{esc(b)}</th></tr></thead>\n'
            "<tbody>\n" + "\n".join(rows) + "\n</tbody>\n</table></div>"
        )
    return "\n".join(out)


def _by_team(picks):
    """Teams in first-round order, each with its picks in order."""
    teams = {}
    for p in sorted(picks, key=lambda p: p["pick"]):
        teams.setdefault(p["team"], []).append(p)
    return teams


def teams_html(picks):
    rows = "\n".join(
        f'<tr><td class="num">{i}</td><td>{esc(team)}</td><td>{esc(mine[0]["player"])}</td></tr>'
        for i, (team, mine) in enumerate(_by_team(picks).items(), 1)
    )
    return ('<div class="table"><table class="roster">\n'
            '<thead><tr><th class="num">순번</th><th>팀</th><th>1라운드 지명</th></tr></thead>\n'
            f'<tbody>\n{rows}\n</tbody>\n</table></div>')


def draft_html(picks):
    blocks = []
    for team, mine in _by_team(picks).items():
        items = "\n".join(
            f'<li><span class="pick">{p["round"]}R · {p["pick"]}</span> {esc(p["player"])}'
            f' <span class="meta">{esc(p.get("nba_team") or "")} {esc(p.get("position") or "")}</span></li>'
            for p in mine
        )
        blocks.append(f'<details class="draft-team">\n<summary>{esc(team)}</summary>\n<ol>\n{items}\n</ol>\n</details>')
    return '<div class="draftboard">\n' + "\n".join(blocks) + "\n</div>"


def _body_html(post, facts_dir):
    """Markdown with fact-sheet tables dropped in where the post asks for them."""
    parts, chunk = [], []
    for line in post["body"].split("\n"):
        m = _SHORTCODE.match(line.strip())
        if not m:
            chunk.append(line)
            continue
        parts.append(markdown.render("\n".join(chunk)))
        chunk = []
        if m.group(1) in ("draft", "teams"):
            path = Path(facts_dir) / "draft.json"
            if not path.exists():
                raise BlogError(f"{post['slug']}: {{{{{m.group(1)}}}}} needs draft.json, which does not exist yet")
            picks = json.loads(path.read_text(encoding="utf-8"))["picks"]
            parts.append(draft_html(picks) if m.group(1) == "draft" else teams_html(picks))
            continue
        week = int(m.group(2)) if m.group(2) else post["week"]
        if week is None:
            raise BlogError(f"{post['slug']}: {{{{{m.group(1)}}}}} needs week=N in a post without a week")
        path = Path(facts_dir) / f"week-{week:02d}.json"
        if not path.exists():
            raise BlogError(f"{post['slug']}: {{{{{m.group(1)}}}}} needs {path.name}, which does not exist yet")
        sheet = json.loads(path.read_text(encoding="utf-8"))
        parts.append(standings_html(sheet) if m.group(1) == "standings" else matchups_html(sheet))
    parts.append(markdown.render("\n".join(chunk)))
    return "\n".join(p for p in parts if p)


# ---- pages ---------------------------------------------------------------

def _day(date):
    return f"{date.month}.{date.day}"


def _kind_class(post):
    if post["kind"] in EDITIONS:
        return post["kind"][5:]
    return post["kind"] if post["kind"] in OWN_COLOUR else "special"


def _label(post):
    if post["kind"] in EDITIONS:
        return f"Week {post['week']} {EDITIONS[post['kind']]}"
    return SPECIALS[post["kind"]]


_FLOAT_SCRIPT = ("(function(){var n=document.querySelector('.float-nav');"
                 "function s(){n.classList.toggle('shown',window.scrollY>400)}"
                 "window.addEventListener('scroll',s,{passive:true});s();"
                 "n.querySelector('.to-top').addEventListener('click',function(){"
                 "window.scrollTo({top:0,behavior:'smooth'})})})();")


def _float_nav(root):
    """Bottom-right buttons that appear once the reader has scrolled: home above, back-to-top below."""
    return (f'<nav class="float-nav" aria-label="바로가기">\n'
            f'<a class="float-home" href="{root or "./"}" aria-label="처음 화면">🏠</a>\n'
            f'<button type="button" class="to-top" aria-label="맨 위로">↑</button>\n'
            f'</nav>\n<script>{_FLOAT_SCRIPT}</script>')


def _page(site, title, description, root, body, url, image="", hidden=False, script=""):
    script = f'\n<script src="{script}" defer></script>' if script else ""
    robots = '\n<meta name="robots" content="noindex">' if hidden else ""
    og_image = f'\n<meta property="og:image" content="{esc(image)}">' if image else ""
    card = "summary_large_image" if image else "summary"
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">{robots}
<meta property="og:type" content="article">
<meta property="og:site_name" content="{esc(site['title'])}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(url)}">{og_image}
<meta name="twitter:card" content="{card}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=IBM+Plex+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}style.css">{script}
</head>
<body>
{body}
{_float_nav(root)}
</body>
</html>
"""


def _masthead(site, root, compact=False):
    tag = "p" if compact else "h1"
    lead, _, last = site["title"].rpartition(" ")
    # On the index the last word drops to its own line, so a phone shows two tidy lines.
    by = f' <small class="by">{esc(site["byline"])}</small>' if site.get("byline") and not compact else ""
    name = (f'<span class="lead">{esc(lead)}</span> <span>{esc(last)}{by}</span>' if lead and not compact
            else esc(site["title"]) + by)
    return (f'<header class="masthead{" compact" if compact else ""}">\n'
            f'<{tag} class="name"><a href="{root or "./"}">{name}</a></{tag}>\n'
            f'<p class="season">{esc(site["season"])} 시즌</p>\n</header>')


def _slot(kind, posts):
    name = EDITIONS[kind]
    if not posts:
        return (f'<li class="ed ed-{kind[5:]} empty"><span class="ed-name">{name}</span>'
                '<span class="ed-title">예정</span></li>')
    links = "".join(
        f'<a href="posts/{esc(p["slug"])}/"><span class="ed-title">{esc(p["title"])}</span>'
        f'<time datetime="{p["date"].isoformat()}">{_day(p["date"])}</time></a>'
        for p in posts
    )
    return f'<li class="ed ed-{kind[5:]}"><span class="ed-name">{name}</span>{links}</li>'


def _team_nav(teams, counts):
    if not teams:
        return ""
    chips = []
    for t in teams:
        n = counts.get(t["id"], 0)
        if n:
            chips.append(f'<li><a href="teams/{t["id"]}/">{esc(t["name"])}<span class="count">{n}</span></a></li>')
        else:
            chips.append(f'<li><a href="teams/{t["id"]}/" class="none">{esc(t["name"])}</a></li>')
    # Folded by default: sixteen chips would push the first post down on a phone.
    return ('\n<details class="teams">\n<summary>팀별로 보기</summary>\n<ul>\n'
            + "\n".join(chips) + "\n</ul>\n</details>")


def _team_page(site, team, entries):
    """entries: (post, passage), newest first."""
    root = "../../"
    standing = ""
    if team.get("rank"):
        standing = f'\n<p class="standing">현재 {esc(team["rank"])}위 · {esc(team["record"])}</p>'
    if entries:
        items = "\n".join(
            f'<li class="mention kind-{_kind_class(p)}"><a href="{root}posts/{esc(p["slug"])}/#team-{team["id"]}">'
            f'<span class="tag">{esc(_label(p))}</span><span class="ed-title">{esc(p["title"])}</span>'
            f'<time datetime="{p["date"].isoformat()}">{_day(p["date"])}</time>'
            f'<span class="passage">{markdown.inline(text)}</span></a></li>'
            for p, text in entries
        )
        listing = f'<ol class="mentions">\n{items}\n</ol>'
    else:
        listing = '<p class="nothing">아직 이 팀이 나온 글이 없습니다.</p>'
    body = (
        _masthead(site, root, compact=True)
        + f'\n<main class="team">\n<header>\n<p class="tag">팀</p>\n<h1>{esc(team["name"])}</h1>{standing}\n'
          f'</header>\n{listing}\n</main>\n'
        + f'<nav class="neighbours">\n<a class="home" href="{root}">전체 목록</a>\n</nav>'
    )
    base = site["url"].rstrip("/")
    description = f'{team["name"]} 팀이 나온 {site["title"]} 글 모음'
    return _page(site, f'{team["name"]} · {site["title"]}', description, root, body, f'{base}/teams/{team["id"]}/')


def _index(site, posts, team_nav="", guide=None):
    weeks = {}
    items = []  # (sort time, html)
    for p in posts:
        if p["kind"] in EDITIONS:
            weeks.setdefault(p["week"], []).append(p)
        else:
            items.append((p["date"].timestamp(), (
                f'<section class="special special-{p["kind"]}">\n<a href="posts/{esc(p["slug"])}/">'
                f'<span class="tag">{SPECIALS[p["kind"]]}</span>'
                f'<span class="ed-title">{esc(p["title"])}</span>'
                f'<time datetime="{p["date"].isoformat()}">{_day(p["date"])}</time></a>\n</section>'
            )))
    for week, group in weeks.items():
        slots = "\n".join(_slot(kind, [p for p in group if p["kind"] == kind]) for kind in EDITIONS)
        items.append((max(p["date"].timestamp() for p in group), (
            f'<section class="week">\n<h2><span>Week</span> {week}</h2>\n'
            f'<ol class="editions">\n{slots}\n</ol>\n</section>'
        )))
    listing = "\n".join(block for _, block in sorted(items, key=lambda item: -item[0]))
    if not posts:
        listing = '<p class="nothing">아직 발행된 글이 없습니다. 드래프트가 끝나면 첫 글이 올라옵니다.</p>'
    body = (
        _masthead(site, "")
        + '\n<p class="legend"><span>매주 세 번 발행합니다. '
          '<span class="key key-start">시작</span> 대진 미리보기, '
          '<span class="key key-mid">중간</span> 주중 점검, '
          '<span class="key key-end">마지막</span> 주간 결산. '
          '주마다 <span class="key key-cartoon">만평</span> 한 편, 큰일이 나면 호외.</span>'
        + (f'<a class="guide-link" href="posts/{esc(guide["slug"])}/">{esc(guide["title"])} →</a>' if guide else "")
        + '</p>'
        + '\n<div class="tools">' + team_nav
        + '\n<input type="search" id="q" placeholder="글 검색: 팀, 선수, 단어" aria-label="글 검색" autocomplete="off">'
          '\n<ol id="found" class="found" hidden></ol>\n</div>\n'
        + f'<main class="board">\n{listing}\n</main>'
    )
    description = site.get("description") or f"{site['season']} 시즌 판타지 농구 리그 매거진"
    return _page(site, site["title"], description, "", body, site["url"].rstrip("/") + "/", script="search.js")


def _post_page(site, post, body_html, older, newer):
    base = site["url"].rstrip("/")
    root = "../../"
    pictures = _PICTURE.findall(post["body"])
    share = post["cover"] or (pictures[0] if pictures else "")
    cover = f"{base}/{share}" if share else ""
    figure = (f'<figure class="cover"><img src="{root}{esc(post["cover"])}" alt="{esc(post["title"])} 만평"></figure>\n'
              if post["cover"] else "")
    kind_class = _kind_class(post)

    def neighbour(p, word):
        if not p:
            return ""
        return f'<a class="{word}" href="../{esc(p["slug"])}/"><span>{"이전 글" if word == "older" else "다음 글"}</span>{esc(p["title"])}</a>'

    review = post["status"] == "review"
    notice = ('\n<p class="preview">미리보기입니다. 아직 발행되지 않아 목록에는 보이지 않습니다.</p>'
              if review else "")
    body = (
        _masthead(site, root, compact=True) + notice
        + f'\n<article class="post kind-{kind_class}">\n<header>\n'
          f'<p class="tag">{esc(_label(post))}</p>\n<h1>{esc(post["title"])}</h1>\n'
          f'<time datetime="{post["date"].isoformat()}">{post["date"].year}년 {post["date"].month}월 {post["date"].day}일</time>\n'
          f'</header>\n{figure}<div class="prose">\n{body_html}\n</div>\n</article>\n'
        + f'<nav class="neighbours">\n{neighbour(older, "older")}\n{neighbour(newer, "newer")}\n'
          f'<a class="home" href="{root}">전체 목록</a>\n</nav>'
    )
    description = post["summary"] or site.get("description") or f"{site['title']} {site['season']}"
    return _page(site, post["title"], description, root, body, f"{base}/posts/{post['slug']}/", cover, hidden=review)


IMAGE_LIMIT = 1024 * 1024  # every image is kept in the repository's history forever


def heavy_images(posts_dir, limit=IMAGE_LIMIT):
    """Images under <posts>/images larger than limit, as (relative path, bytes), largest first."""
    posts_dir = Path(posts_dir)
    found = [(path.relative_to(posts_dir).as_posix(), path.stat().st_size)
             for path in (posts_dir / "images").rglob("*") if path.is_file()]
    return sorted([f for f in found if f[1] > limit], key=lambda f: -f[1])


def build(posts_dir, out_dir, site, facts_dir):
    """Write the whole site into out_dir (replacing it). Returns the number of
    published posts; posts in review get a page but are not counted or listed."""
    posts_dir, out_dir = Path(posts_dir), Path(out_dir)
    everything = load_posts(posts_dir)
    posts = [p for p in everything if p["status"] == "published" and p["kind"] != GUIDE]
    guide = next((p for p in everything if p["status"] == "published" and p["kind"] == GUIDE), None)
    teams = load_teams(facts_dir)
    mentions = {t["id"]: [] for t in teams}
    pages = {}
    for post in everything:
        if post["cover"] and not (posts_dir / post["cover"]).exists():
            raise BlogError(f"{post['slug']}: cover {post['cover']} does not exist under {posts_dir}")
        pictures = _PICTURE.findall(post["body"])
        for picture in pictures:
            if not (posts_dir / picture).exists():
                raise BlogError(f"{post['slug']}: {picture} does not exist under {posts_dir}")
        if post["kind"] == "week-cartoon" and len(pictures) != CARTOON_PICTURES:
            raise BlogError(f"{post['slug']}: a cartoon post has {CARTOON_PICTURES} pictures, "
                            f"this one has {len(pictures)}")
        body = _body_html(post, facts_dir).replace('src="images/', 'src="../../images/')
        if post in posts and post["kind"] not in TEAMLESS:
            for team in teams:
                text = passage(post["body"], team)
                if text:
                    mentions[team["id"]].append((post, text))
                    body = _anchor(body, team)
        i = posts.index(post) if post in posts else None
        older = posts[i - 1] if i else None
        newer = posts[i + 1] if i is not None and i + 1 < len(posts) else None
        pages[post["slug"]] = _post_page(site, post, body, older, newer)

    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    shutil.copyfile(STYLE, out_dir / "style.css")
    shutil.copyfile(SEARCH, out_dir / "search.js")
    (out_dir / "search.json").write_text(json.dumps(search_entries(posts), ensure_ascii=False), encoding="utf-8")
    if (posts_dir / "images").exists():
        shutil.copytree(posts_dir / "images", out_dir / "images")
    counts = {team_id: len(found) for team_id, found in mentions.items()}
    (out_dir / "index.html").write_text(_index(site, posts, _team_nav(teams, counts), guide), encoding="utf-8")
    for team in teams:
        target = out_dir / "teams" / str(team["id"])
        target.mkdir(parents=True)
        (target / "index.html").write_text(_team_page(site, team, mentions[team["id"]][::-1]), encoding="utf-8")
    for slug, page in pages.items():
        target = out_dir / "posts" / slug
        target.mkdir(parents=True)
        (target / "index.html").write_text(page, encoding="utf-8")
    return len(posts)
