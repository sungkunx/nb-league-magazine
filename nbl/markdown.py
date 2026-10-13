"""Small Markdown renderer for magazine posts (standard library only).

Supports what the articles use: headings, paragraphs, bold, italic, inline
code, links, images, lists (one nested level), blockquotes, rules and tables.
All text is HTML-escaped; raw HTML in a post is shown as text, not run.
"""
import html
import re

_SAFE_URL = re.compile(r"^(https?://|mailto:|/|\.{0,2}/|#|[A-Za-z0-9_][^:]*$)")
_LIST = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_TABLE_RULE = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")
_IMAGE_LINE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)$")


def _url(raw):
    return raw if _SAFE_URL.match(html.unescape(raw)) else None


def inline(text):
    """Escape, then apply code, image, link, bold and italic marks."""
    text = html.escape(text, quote=True)
    codes = []

    def keep_code(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep_code, text)

    def image(m):
        src = _url(m.group(2))
        return f'<img src="{src}" alt="{m.group(1)}" loading="lazy">' if src else m.group(0)

    def link(m):
        href = _url(m.group(2))
        return f'<a href="{href}">{m.group(1)}</a>' if href else m.group(1)

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", image, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _table(header, rule, rows):
    right = [c.endswith(":") and not c.startswith(":") for c in _cells(rule)]

    def row(cells, tag):
        out = []
        for i, cell in enumerate(cells):
            cls = ' class="num"' if i < len(right) and right[i] else ""
            out.append(f"<{tag}{cls}>{inline(cell)}</{tag}>")
        return "<tr>" + "".join(out) + "</tr>"

    body = "\n".join(row(_cells(r), "td") for r in rows)
    return (f'<div class="table"><table>\n<thead>{row(_cells(header), "th")}</thead>\n'
            f"<tbody>\n{body}\n</tbody>\n</table></div>")


def _list(items):
    """items: (indent, ordered, text). Indented items nest under the one above."""
    def wrap(ordered, parts):
        tag = "ol" if ordered else "ul"
        return f"<{tag}>\n" + "\n".join(parts) + f"\n</{tag}>"

    top = []  # [text, ordered, [(ordered, text), ...]]
    for indent, ordered, text in items:
        if indent >= 2 and top:
            top[-1][2].append((ordered, text))
        else:
            top.append([text, ordered, []])
    parts = []
    for text, _, children in top:
        if children:
            nested = wrap(children[0][0], [f"<li>{inline(t)}</li>" for _, t in children])
            parts.append(f"<li>{inline(text)}\n{nested}\n</li>")
        else:
            parts.append(f"<li>{inline(text)}</li>")
    return wrap(top[0][1], parts)


def _paragraph(lines):
    return "<p>" + "<br>\n".join(inline(l) for l in lines) + "</p>"


def render(text):
    lines = text.replace("\r\n", "\n").split("\n")
    out, para = [], []

    def flush():
        if para:
            out.append(_paragraph(para))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if _RULE.match(stripped):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{_paragraph(quote)}</blockquote>")
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1].strip()):
            flush()
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(lines[j])
                j += 1
            out.append(_table(stripped, lines[i + 1].strip(), rows))
            i = j
            continue
        if _LIST.match(line):
            flush()
            items = []
            while i < len(lines) and _LIST.match(lines[i].rstrip()):
                m = _LIST.match(lines[i].rstrip())
                items.append((len(m.group(1)), m.group(2)[0].isdigit(), m.group(3)))
                i += 1
            out.append(_list(items))
            continue
        image = _IMAGE_LINE.match(stripped)
        if image and not para and _url(html.escape(image.group(2))):
            out.append(f"<figure>{inline(stripped)}</figure>")
            i += 1
            continue
        para.append(stripped)
        i += 1
    flush()
    return "\n".join(out)
