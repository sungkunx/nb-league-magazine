// Bell at the top right of every page: counts and lists the posts of the last three days.
// The site is rebuilt only when a post goes up, so "the last three days" is worked out here, in the browser.
(function () {
  var DAYS = 3;
  var bell = document.querySelector(".bell");
  if (!bell) return;
  var root = bell.getAttribute("data-root") || "./";
  var button = bell.querySelector(".bell-button");
  var count = bell.querySelector(".bell-count");
  var panel = bell.querySelector(".bell-panel");
  var list = bell.querySelector(".bell-list");

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  // 오늘 / 어제 / 2일 전, by the reader's calendar day.
  function when(date, now) {
    var a = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    var b = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var days = Math.round((b - a) / 86400000);
    return days <= 0 ? "오늘" : days === 1 ? "어제" : days + "일 전";
  }

  function fill(posts) {
    var now = new Date();
    var since = now.getTime() - DAYS * 86400000;
    var recent = posts.filter(function (p) {
      var t = new Date(p.date).getTime();
      return t >= since && t <= now.getTime() + 3600000;
    });
    list.textContent = "";
    if (recent.length) {
      count.textContent = recent.length > 9 ? "9+" : String(recent.length);
      count.hidden = false;
      button.setAttribute("aria-label", "최근 3일 새 글 " + recent.length + "편");
    }
    if (!recent.length) list.appendChild(el("li", "bell-none", "최근 3일 동안 올라온 글이 없습니다."));
    recent.forEach(function (p) {
      var item = el("li", "kind-" + p.kind);
      var link = el("a");
      link.href = root + p.url;
      link.appendChild(el("span", "tag", p.label));
      link.appendChild(el("span", "bell-title", p.title));
      var time = el("time", "", when(new Date(p.date), now));
      time.setAttribute("datetime", p.date);
      link.appendChild(time);
      item.appendChild(link);
      list.appendChild(item);
    });
  }

  function toggle(open) {
    panel.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }

  button.addEventListener("click", function (e) {
    e.stopPropagation();
    toggle(panel.hidden);
  });
  document.addEventListener("click", function (e) {
    if (!panel.hidden && !bell.contains(e.target)) toggle(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !panel.hidden) { toggle(false); button.focus(); }
  });

  fetch(root + "updates.json", { cache: "no-cache" })
    .then(function (r) { return r.json(); })
    .then(fill)
    .catch(function () { fill([]); });
})();
