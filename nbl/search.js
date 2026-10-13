// Search for the index page: filters search.json in the browser.
// Every space-separated word must appear in a post's title or text.
(function () {
  var box = document.getElementById("q");
  var list = document.getElementById("found");
  var board = document.querySelector(".board");
  if (!box || !list || !board) return;
  var posts = null;

  function load() {
    if (posts) return Promise.resolve(posts);
    return fetch("search.json").then(function (r) { return r.json(); }).then(function (data) {
      posts = data.map(function (p) {
        p.hay = (p.title + " " + p.text).toLowerCase();
        return p;
      });
      return posts;
    });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  // The words around the first hit, with the hit itself marked.
  function snippet(text, word) {
    var at = text.toLowerCase().indexOf(word);
    var span = el("span", "passage");
    if (at < 0) {
      span.textContent = text.slice(0, 90) + (text.length > 90 ? "…" : "");
      return span;
    }
    var from = Math.max(0, at - 40), to = Math.min(text.length, at + word.length + 60);
    span.appendChild(document.createTextNode((from ? "…" : "") + text.slice(from, at)));
    span.appendChild(el("mark", "", text.slice(at, at + word.length)));
    span.appendChild(document.createTextNode(text.slice(at + word.length, to) + (to < text.length ? "…" : "")));
    return span;
  }

  function show() {
    var words = box.value.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) {
      list.hidden = true;
      board.hidden = false;
      return;
    }
    load().then(function (all) {
      var hits = all.filter(function (p) {
        return words.every(function (w) { return p.hay.indexOf(w) >= 0; });
      });
      list.textContent = "";
      if (!hits.length) list.appendChild(el("li", "nothing", "찾는 글이 없습니다."));
      hits.forEach(function (p) {
        var item = el("li", "mention");
        var link = el("a");
        var at = p.text.toLowerCase().indexOf(words[0]);
        // A text fragment makes the browser jump to the word (ignored where unsupported).
        link.href = p.url + (at >= 0 ? "#:~:text=" + encodeURIComponent(p.text.substr(at, words[0].length)) : "");
        link.appendChild(el("span", "tag", p.label));
        link.appendChild(el("span", "ed-title", p.title));
        link.appendChild(el("time", "", p.date));
        link.appendChild(snippet(p.text, words[0]));
        item.appendChild(link);
        list.appendChild(item);
      });
      list.hidden = false;
      board.hidden = true;
    });
  }

  box.addEventListener("input", show);
  box.addEventListener("focus", load, { once: true });
  if (box.value) show();
})();
