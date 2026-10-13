import unittest

from nbl.markdown import render


class MarkdownTests(unittest.TestCase):
    def test_paragraphs_are_separated_by_blank_lines(self):
        self.assertEqual(render("첫 문단\n이어지는 줄\n\n둘째 문단"), "<p>첫 문단<br>\n이어지는 줄</p>\n<p>둘째 문단</p>")

    def test_headings(self):
        self.assertEqual(render("## 이번 주 MVP"), "<h2>이번 주 MVP</h2>")
        self.assertEqual(render("#### 작은 제목"), "<h4>작은 제목</h4>")

    def test_bold_italic_and_code(self):
        self.assertEqual(render("**Cho**가 *겨우* `5-5`"), "<p><strong>Cho</strong>가 <em>겨우</em> <code>5-5</code></p>")

    def test_html_in_the_text_is_escaped(self):
        self.assertEqual(render("<script>alert(1)</script> & co"), "<p>&lt;script&gt;alert(1)&lt;/script&gt; &amp; co</p>")

    def test_team_names_with_backticks_and_apostrophes_survive(self):
        self.assertEqual(render("YoungHun`s Team Bravo와 hyun's Team"), "<p>YoungHun`s Team Bravo와 hyun&#x27;s Team</p>")

    def test_links_and_images(self):
        self.assertEqual(render("[순위](https://example.com/a?b=1&c=2)"),
                         '<p><a href="https://example.com/a?b=1&amp;c=2">순위</a></p>')
        self.assertEqual(render("![만평](images/w1-mid.png)"),
                         '<figure><img src="images/w1-mid.png" alt="만평" loading="lazy"></figure>')

    def test_script_urls_are_not_turned_into_links(self):
        self.assertNotIn("<a", render("[x](javascript:alert(1))"))

    def test_unordered_list_with_one_nested_level(self):
        html = render("- A 팀\n  - 세부\n- B 팀")
        self.assertEqual(html, "<ul>\n<li>A 팀\n<ul>\n<li>세부</li>\n</ul>\n</li>\n<li>B 팀</li>\n</ul>")

    def test_ordered_list(self):
        self.assertEqual(render("1. 하나\n2. 둘"), "<ol>\n<li>하나</li>\n<li>둘</li>\n</ol>")

    def test_blockquote_and_rule(self):
        self.assertEqual(render("> 한 줄 평\n> 둘째 줄\n\n---"), "<blockquote><p>한 줄 평<br>\n둘째 줄</p></blockquote>\n<hr>")

    def test_table_with_header_and_alignment(self):
        html = render("| 팀 | 승 |\n|---|--:|\n| Cho | 5 |")
        self.assertEqual(html, (
            '<div class="table"><table>\n<thead><tr><th>팀</th><th class="num">승</th></tr></thead>\n'
            '<tbody>\n<tr><td>Cho</td><td class="num">5</td></tr>\n</tbody>\n</table></div>'
        ))

    def test_inline_marks_work_inside_tables_and_lists(self):
        self.assertIn("<strong>Cho</strong>", render("| 팀 |\n|---|\n| **Cho** |"))
        self.assertIn("<strong>Cho</strong>", render("- **Cho**"))

    def test_asterisks_inside_code_are_left_alone(self):
        self.assertEqual(render("`FGM/A*`와 *강조*"), "<p><code>FGM/A*</code>와 <em>강조</em></p>")

    def test_empty_text(self):
        self.assertEqual(render(""), "")


if __name__ == "__main__":
    unittest.main()
