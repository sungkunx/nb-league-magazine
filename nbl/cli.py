"""Command line: python -m nbl <command>.

  discover   list your Yahoo NBA leagues for every season (finds league keys)
  smoke      check the connection and save one sample of each response type
  collect    the daily run: collect finished days, then rebuild fact sheets
  draft      after the draft: save results and write the draft fact sheet
  sheets     rebuild fact sheets from data already collected (no network)

  blog       build the static site from posts/ (see config/site.json)
  publish    take a post out of review: python -m nbl publish <slug>

Browser collection (config "source": "web"; see docs/browser-collection.md):
  plan       list the days and weeks the next browser run should fetch
  verify     check a saved browser file: checksum, and that a day adds up
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from . import blog, collect, db, factsheet, parse, web
from .store import RawStore
from .yahoo import YahooClient, YahooError

SECRETS = ("YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET", "YAHOO_REFRESH_TOKEN")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path, data):
    _write(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _open_db(config, store, data_dir, out):
    """A fresh database from whichever source this league uses, or None."""
    path = data_dir / "league.db"
    if config.get("source") == "web":
        root = data_dir / "web"
        if not root.exists():
            return None
        path.unlink(missing_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript(db.SCHEMA)
        for problem in web.load(conn, root, config["season"], config.get("web_time_zone", "Asia/Seoul")):
            print(f"PROBLEM {problem}", file=out)
        return conn
    return db.rebuild(store, path) if store.root.exists() else None


def _sheets(config, store, data_dir, out, only_week=None):
    """Rebuild the database and write fact sheets under <data_dir>/facts."""
    conn = _open_db(config, store, data_dir, out)
    if conn is None:
        print("nothing collected yet", file=out)
        return
    facts = data_dir / "facts"
    try:
        weeks = [dict(r) for r in conn.execute("SELECT week, start, end FROM weeks ORDER BY week")]
        if only_week is not None:
            targets = [only_week]
        else:
            days = [r[0] for r in conn.execute("SELECT date FROM run_log")]
            touched = sorted({collect.week_for(d, weeks) for d in days} - {None})
            targets = touched[-2:]  # the week in progress and the one just corrected
        for week in targets:
            sheet = factsheet.build_week(conn, week)
            _write_json(facts / f"week-{week:02d}.json", sheet)
            _write(facts / f"week-{week:02d}.md", factsheet.render_md(sheet))
            print(f"week-{week:02d}: {len(sheet['checks'])} check(s) need attention", file=out)
        if db.meta(conn).get("start_date"):
            _write_json(facts / "preseason.json", factsheet.build_preseason(conn))
        if conn.execute("SELECT 1 FROM draft_results LIMIT 1").fetchone():
            sheet = factsheet.build_draft(conn)
            _write_json(facts / "draft.json", sheet)
            _write(facts / "draft.md", factsheet.render_draft_md(sheet))
            print(f"draft: {len(sheet['picks'])} picks", file=out)
    finally:
        conn.close()


def _verify(files, out):
    failed = False
    for name in files:
        try:
            text = Path(name).read_text(encoding="utf-8")
            header, lines = web.unseal(text)
            problems = web.day_problems(web.parse_day(text)) if header["kind"] == "day" else []
        except (OSError, web.WebDataError) as error:
            problems, header, lines = [str(error)], None, []
        if problems:
            failed = True
            for problem in problems:
                print(f"FAILED {name}: {problem}", file=out)
        else:
            print(f"OK {name}: {header['kind']}, {len(lines)} lines", file=out)
    return 1 if failed else 0


def _smoke(api, store, config, out):
    league_key = collect.resolve_league_key(api, config["season"], config["league_id"])
    print(f"league key: {league_key}", file=out)

    def sample(name, path, required=False):
        try:
            xml = api.get(path)
        except YahooError as error:
            if required:
                raise
            print(f"  (skipped {name}: {error})", file=out)
            return None
        store.save(f"samples/{name}.xml", xml)
        return parse.xml_root(xml)

    settings = sample("settings", f"league/{league_key}/settings", required=True)
    meta = parse.league_meta(settings)
    print(f"league: {meta['name']} ({meta['num_teams']} teams, {meta['scoring_type']}, "
          f"draft {meta['draft_status']})", file=out)
    print(f"season: {meta['start_date']} ~ {meta['end_date']}", file=out)
    cats = [c["display_name"] for c in parse.stat_categories(settings) if not c["is_display_only"]]
    print(f"categories ({len(cats)}): {', '.join(cats)}", file=out)
    limits = parse.settings(settings)
    print(f"limits: {limits}", file=out)

    teams = parse.teams(sample("teams", f"league/{league_key}/teams", required=True))
    print("teams: " + ", ".join(t["name"] for t in teams), file=out)

    sample("game_weeks", f"game/{league_key.split('.l.')[0]}/game_weeks")
    sample("standings", f"league/{league_key}/standings")
    sample("scoreboard", f"league/{league_key}/scoreboard;week=1")
    sample("transactions", f"league/{league_key}/transactions")
    if teams:
        today = datetime.now(collect.PT).date().isoformat()
        day = max(today, meta["start_date"] or today)
        roster = sample("roster", f"team/{teams[0]['team_key']}/roster;date={day}")
        keys = [p["player_key"] for p in parse.roster(roster)["players"]] if roster is not None else []
        if keys:
            sample("stats", f"league/{league_key}/players;player_keys={','.join(keys[:25])}"
                            f"/stats;type=date;date={day}")
        print(f"roster sample: {teams[0]['name']} has {len(keys)} players", file=out)
    print("OK", file=out)


def _discover(api, out):
    root = parse.xml_root(api.get("users;use_login=1/games;game_codes=nba/leagues"))
    for lg in parse.user_leagues(root):
        print(f"{lg['season']}  {lg['league_key']}  {lg['name']}", file=out)


def main(argv=None, env=None, api=None, out=None):
    out = out or sys.stdout
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="nbl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/league.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    sub.add_parser("smoke")
    p_collect = sub.add_parser("collect")
    p_collect.add_argument("--now", help="pretend it is this time (ISO 8601 with offset)")
    sub.add_parser("draft")
    p_sheets = sub.add_parser("sheets")
    p_sheets.add_argument("--week", type=int)
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--now", help="pretend it is this time (ISO 8601 with offset)")
    p_blog = sub.add_parser("blog")
    p_blog.add_argument("--site", default="config/site.json")
    p_publish = sub.add_parser("publish")
    p_publish.add_argument("slug")
    p_publish.add_argument("--site", default="config/site.json")
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("files", nargs="+")
    args = parser.parse_args(argv)

    if args.command == "blog":
        site = json.loads(Path(args.site).read_text(encoding="utf-8"))
        try:
            count = blog.build(site["posts_dir"], site["out_dir"], site, site["facts_dir"])
        except blog.BlogError as error:
            print(f"ERROR: {error}", file=out)
            return 1
        print(f"built {count} post(s) into {site['out_dir']}", file=out)
        for path, size in blog.heavy_images(site["posts_dir"]):
            print(f"WARNING: {path} is {size / 1024 / 1024:.1f} MB; shrink it to a JPG "
                  f"about 1200px wide before committing", file=out)
        for post in blog.load_posts(site["posts_dir"]):
            if post["status"] == "review":
                print(f"waiting for review: {site['url'].rstrip('/')}/posts/{post['slug']}/", file=out)
        return 0

    if args.command == "publish":
        site = json.loads(Path(args.site).read_text(encoding="utf-8"))
        path = Path(site["posts_dir"]) / f"{args.slug}.md"
        try:
            if not path.exists():
                raise blog.BlogError(f"{args.slug}: no such post in {site['posts_dir']}")
            blog.publish(path)
        except blog.BlogError as error:
            print(f"ERROR: {error}", file=out)
            return 1
        print(f"published {args.slug}", file=out)
        return 0

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    data_dir = Path(config["data_dir"])
    store = RawStore(data_dir / "raw")

    if args.command == "sheets":
        _sheets(config, store, data_dir, out, args.week)
        return 0
    if args.command == "verify":
        return _verify(args.files, out)
    if args.command == "plan":
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(collect.PT)
        if now.tzinfo is None:
            now = now.replace(tzinfo=collect.PT)
        p = web.plan(data_dir / "web", config["season"], config["season_start"], now,
                     season_end=config.get("season_end"))
        print(f"base: {config['web_base']}", file=out)
        print(f"teams: {' '.join(str(i) for i in range(1, config.get('num_teams', 16) + 1))}", file=out)
        print(f"days: {' '.join(p['days']) or '-'}", file=out)
        print(f"weeks: {' '.join(str(w) for w in p['weeks'])}", file=out)
        print(f"yesterday: {p['yesterday']}", file=out)
        print(f"lineup: {p['lineup'] or '-'}", file=out)
        if p["preseason"]:
            print("note: season has not started - collect settings and transactions only", file=out)
        if p["behind"]:
            print(f"note: {p['behind']} more day(s) are still missing after this run", file=out)
        return 0

    if config.get("source") == "web":
        print("this league is collected through the browser (docs/browser-collection.md); "
              "rebuilding fact sheets only", file=out)
        _sheets(config, store, data_dir, out)
        return 0

    if api is None:
        missing = [name for name in SECRETS if not (env.get(name) or "").strip()]
        if missing:
            print(f"Missing secret(s): {', '.join(missing)}", file=out)
            return 2
        extra = {"redirect_uri": config["redirect_uri"]} if config.get("redirect_uri") else {}
        api = YahooClient(*(env[name] for name in SECRETS), **extra)

    try:
        if args.command == "discover":
            _discover(api, out)
        elif args.command == "smoke":
            _smoke(api, store, config, out)
        elif args.command == "collect":
            now = datetime.fromisoformat(args.now) if args.now else None
            if now is not None and now.tzinfo is None:
                now = now.replace(tzinfo=collect.PT)
            summary = collect.run(api, store, config["season"], config["league_id"], now=now)
            print(f"collected: {summary['collected'] or 'nothing new'}", file=out)
            if summary["corrected"]:
                print(f"re-collected for stat corrections: {summary['corrected']}", file=out)
            for day in summary["collected"] + summary["corrected"]:
                for warning in store.run_info(day).get("warnings", []):
                    print(f"WARNING {day}: {warning}", file=out)
            _sheets(config, store, data_dir, out)
        elif args.command == "draft":
            league_key = collect.resolve_league_key(api, config["season"], config["league_id"])
            if not store.exists("league/settings.xml"):
                store.save("league/settings.xml", api.get(f"league/{league_key}/settings"))
            store.save("league/teams.xml", api.get(f"league/{league_key}/teams"))
            warnings = collect.collect_draft(api, store, league_key, prev_season=config["season"] - 1)
            for warning in warnings:
                print(f"WARNING: {warning}", file=out)
            if not store.exists("league/draftresults.xml"):
                return 1
            _sheets(config, store, data_dir, out)
    except YahooError as error:
        print(f"ERROR: {error}", file=out)
        return 1
    return 0
