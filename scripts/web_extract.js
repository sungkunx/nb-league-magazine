// Runs inside a logged-in Yahoo Fantasy tab. Defines NBL.* extractors that
// fetch league pages and return compact, checksummed text (see nbl/web.py).
//
// Every result is a block of pipe-delimited lines ending in "#crc=<hex> lines=<n>".
// The checksum lets the Python side prove the text was saved without a typo.
globalThis.NBL = (() => {
  // Invisible characters are dropped: they cannot be seen when the text is
  // copied by hand, so they would break the checksum for no visible reason.
  // (Written with code points, not \u escapes, so the script survives being
  // pasted through tools that expand escapes.)
  // Includes the private-use range: Yahoo draws some icons as private-use glyphs.
  const invisible = (c) =>
    c === 0xad || (c >= 0x200b && c <= 0x200f) || (c >= 0x2028 && c <= 0x202e) || (c >= 0x2060 && c <= 0x2064) ||
    c === 0xfeff || (c >= 0xe000 && c <= 0xf8ff) || (c < 32 && c !== 9 && c !== 10 && c !== 13);
  const clean = (s) =>
    [...(s || '')]
      .filter((ch) => !invisible(ch.codePointAt(0)))
      .join('')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\|/g, '/');
  const cellText = (c) => clean(c ? c.textContent : '');

  const get = async (url) => {
    const r = await fetch(url, { credentials: 'include' });
    if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
    if (!/fantasysports\.yahoo\.com/.test(r.url)) throw new Error(`redirected away (login?) for ${url}`);
    return new DOMParser().parseFromString(await r.text(), 'text/html');
  };

  const crc32 = (text) => {
    let c, crc = 0xffffffff;
    for (const b of new TextEncoder().encode(text)) {
      c = (crc ^ b) & 0xff;
      for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
      crc = (crc >>> 8) ^ c;
    }
    return ((crc ^ 0xffffffff) >>> 0).toString(16).padStart(8, '0');
  };
  const seal = (lines) => {
    const body = lines.join('\n');
    return `${body}\n#crc=${crc32(body)} lines=${lines.length}`;
  };

  const playerId = (el) => {
    const a = el && el.querySelector('a[href*="/nba/players/"]');
    const m = a && a.getAttribute('href').match(/players\/(\d+)/);
    return m ? m[1] : '';
  };
  const teamIdOf = (el, base) => {
    for (const a of el ? el.querySelectorAll('a[href]') : []) {
      const m = a.getAttribute('href').split('?')[0].match(new RegExp(`${base}/(\\d+)$`));
      if (m) return m[1];
    }
    return '';
  };
  const inChunks = async (items, size, fn) => {
    const out = [];
    for (let i = 0; i < items.length; i += size) {
      out.push(...(await Promise.all(items.slice(i, i + size).map(fn))));
    }
    return out;
  };
  // Stat columns start at the first shooting/score header and run to the last named header.
  // Percentage columns are skipped: they are recomputed from made/attempted.
  const statColumns = (headers) => {
    const first = headers.findIndex((h) => /^(FGM\/A|FG%|FTM\/A|FT%|3PTM|PTS)/.test(h));
    let last = headers.length - 1;
    while (last > first && !headers[last]) last--;
    return first < 0 ? [] : headers.map((h, i) => i).filter((i) => i >= first && i <= last && !/%$/.test(headers[i]));
  };
  // "-" when the player has no line at all that day (every cell is a dash).
  const statLine = (values) => (values.every((v) => v === '-' || v === '-/-') ? '-' : values.join('|'));

  // One stats day: every team's roster slots and each player's line for that date.
  async function day(base, date, teamIds) {
    const blocks = await inChunks(teamIds, 4, async (id) => {
      const doc = await get(`${base}/${id}/team?date=${date}&stat1=S&stat2=D`);
      const table = doc.querySelector('#statTable0');
      const name = clean((doc.title.split(' | ')[0] || '').replace(/^.*? - /, ''));
      const shown = [...doc.querySelectorAll('span, div, a')]
        .map((e) => clean(e.textContent))
        .find((t) => /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), [A-Z][a-z]{2} \d{1,2}$/.test(t)) || '';
      const lines = [`T|${id}|${name}|${shown}`];
      if (!table) return { lines: lines.concat(`E|${id}|no roster table`) };
      const rows = [...table.rows];
      const head = rows.find((r) => cellText(r.cells[0]) === 'Pos');
      if (!head) return { lines: lines.concat(`E|${id}|no header row`) };
      const headers = [...head.cells].map((c) => cellText(c).replace(/\*$/, ''));
      const cols = statColumns(headers);
      const nameCol = headers.findIndex((h) => /^Players?$/.test(h));
      const columns = cols.map((i) => headers[i]).join('|');
      for (const r of rows) {
        const cells = [...r.cells];
        const label = cellText(cells[nameCol]);
        const stats = statLine(cols.map((i) => cellText(cells[i])));
        if (/^Starting Lineup Totals/.test(label)) {
          lines.push(`S|${stats}`);
          continue;
        }
        const pid = playerId(cells[nameCol]);
        if (!pid) continue;
        const link = cells[nameCol].querySelector('a[href*="/nba/players/"]');
        const pname = clean(link.textContent);
        const box = link.parentElement;
        const info = clean(box.textContent).slice(pname.length).trim(); // "SAS - PG,SG" and/or status
        lines.push(`P|${cellText(cells[0])}|${pid}|${pname}|${info}|${stats}`);
      }
      return { lines, columns };
    });
    const columns = [...new Set(blocks.map((b) => b.columns).filter(Boolean))];
    const body = blocks.flatMap((b) => b.lines);
    if (columns.length > 1) body.push(`E|0|teams disagree on stat columns`);
    return seal([`#nbl-day v2 base=${base} date=${date} teams=${teamIds.length}`, `C|${columns[0] || ''}`, ...body]);
  }

  // One scoring week: each matchup's official team totals and category score.
  async function week(base, weekNo, teamIds) {
    const lines = [];
    const seen = new Set();
    let span = '';
    for (const id of teamIds) {
      if (seen.has(id)) continue;
      const doc = await get(`${base}/matchup?week=${weekNo}&mid1=${id}`);
      const table = [...doc.querySelectorAll('table')].find(
        (t) => t.rows.length >= 3 && cellText(t.rows[0].cells[0]) === 'Team'
      );
      if (!table) {
        lines.push(`E|${id}|no matchup`);
        seen.add(id);
        continue;
      }
      if (!span) {
        const days = [...doc.querySelectorAll('a[href*="week="]')]
          .map((a) => clean(a.textContent))
          .filter((t) => /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2}\/\d{1,2}$/.test(t));
        span = days.length ? `${days[0]}|${days[days.length - 1]}|${days.length}` : '||0';
      }
      const headers = [...table.rows[0].cells].map((c) => cellText(c).replace(/\*$/, ''));
      const cols = statColumns(headers);
      if (!lines.some((l) => l.startsWith('C|'))) lines.push(`C|${cols.map((i) => headers[i]).join('|')}`);
      const sides = [1, 2].map((n) => {
        const cells = [...table.rows[n].cells];
        return {
          id: teamIdOf(table.rows[n], base),
          name: cellText(cells[0]),
          stats: cols.map((i) => cellText(cells[i])).join('|'),
          score: cellText(cells[cells.length - 1]),
        };
      });
      sides.forEach((s) => seen.add(s.id));
      seen.add(id);
      lines.push(`M|${sides[0].id}|${sides[1].id}|${sides[0].score}|${sides[1].score}`);
      sides.forEach((s) => lines.push(`A|${s.id}|${s.name}|${s.stats}`));
    }
    return seal([`#nbl-week v2 base=${base} week=${weekNo}`, `W|${weekNo}|${span}`, ...lines]);
  }

  async function standings(base) {
    const doc = await get(`${base}?lhst=stand`);
    const table = doc.querySelector('#standingstable');
    if (!table) return seal([`#nbl-standings v1 base=${base}`, 'E|0|no standings table']);
    const rows = [...table.rows];
    const headers = [...rows[0].cells].map(cellText);
    const col = (name) => headers.indexOf(name);
    const lines = [];
    for (const r of rows.slice(1)) {
      const id = teamIdOf(r, base);
      if (!id) continue;
      const c = [...r.cells].map(cellText);
      lines.push(`R|${c[col('Rank')].replace(/\D/g, '')}|${id}|${c[col('Team')]}|${c[col('W-L-T')]}|${c[col('Pct')]}|${c[col('Moves')] || ''}`);
    }
    return seal([`#nbl-standings v1 base=${base}`, ...lines]);
  }

  // Transactions, newest first: `pages` x 25 rows, one line per player moved.
  // Times are shown in the viewer's own time zone, without a year.
  async function transactions(base, pages) {
    const lines = [];
    let url = new URL(`${base}/transactions`, location.origin).href;
    for (let p = 0; p < pages && url; p++) {
      const doc = await get(url);
      const table = doc.querySelector('table');
      if (!table) break;
      [...table.rows].forEach((r, i) => {
        const cells = [...r.cells];
        const last = cells[cells.length - 1];
        const when = cellText(last).match(/[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [ap]m/);
        const team = teamIdOf(last, base);
        const traded = cells.some((c) => /^Traded to$/.test(cellText(c)));
        const moves = [...r.querySelectorAll('td div, td p')].filter((d) =>
          d.querySelector(':scope > a[href*="/nba/players/"]')
        );
        moves.forEach((d) => {
          const a = d.querySelector('a[href*="/nba/players/"]');
          const detail = traded ? 'Traded to' : clean((d.querySelector('h6') || {}).textContent);
          lines.push(
            `X|${p}.${i}|${when ? when[0] : ''}|${team}|${playerId(d)}|${clean(a.textContent)}|${clean((d.querySelector('span') || {}).textContent)}|${detail}`
          );
        });
        if (!moves.length) lines.push(`E|${p}.${i}|${cellText(r).slice(0, 80)}`);
      });
      const next = [...doc.querySelectorAll('a')].find((a) => /^Next 25/.test(clean(a.textContent)));
      url = next ? new URL(next.getAttribute('href'), url).href : '';
    }
    return seal([`#nbl-transactions v2 base=${base} pages=${pages}`, ...lines]);
  }

  async function draft(base) {
    const doc = await get(`${base}/draftresults`);
    const lines = [];
    let pick = 0;
    for (const table of doc.querySelectorAll('table')) {
      const round = (cellText(table.rows[0] && table.rows[0].cells[0]).match(/^Round (\d+)/) || [])[1];
      if (!round) continue;
      for (const r of [...table.rows].slice(1)) {
        const pid = playerId(r);
        if (!pid) continue;
        pick += 1;
        lines.push(`D|${pick}|${round}|${teamIdOf(r, base)}|${pid}|${cellText(r.cells[1])}|${cellText(r.cells[2])}`);
      }
    }
    return seal([`#nbl-draft v1 base=${base}`, ...lines]);
  }

  async function settings(base) {
    const doc = await get(`${base}/settings`);
    const lines = [];
    for (const r of doc.querySelectorAll('table tr')) {
      if (r.cells.length !== 2) continue;
      const key = cellText(r.cells[0]).replace(/:$/, '');
      if (key && key !== 'Setting') lines.push(`K|${key}|${cellText(r.cells[1])}`);
    }
    return seal([`#nbl-settings v1 base=${base}`, ...lines]);
  }

  // The tool that reads results back shows at most 100 array items, so a
  // result is stored and read in pages: run() returns the page count,
  // page(n) returns up to PAGE lines.
  const PAGE = 90;
  let stored = [];
  async function run(promise) {
    stored = (await promise).split('\n');
    return { lines: stored.length, pages: Math.ceil(stored.length / PAGE) };
  }
  const page = (n) => stored.slice(n * PAGE, (n + 1) * PAGE);

  return { day, week, standings, transactions, draft, settings, crc32, run, page };
})();
'NBL ready';
