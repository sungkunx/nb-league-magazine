"""Decide what to fetch each day and save the raw responses.

A "stats day" D is a US Pacific calendar day. It is collected just after it
ends (00:05 PT on D+1): by then every game of D is over, and the roster each
manager locked in for D can no longer change.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import parse
from .yahoo import YahooError

PT = ZoneInfo("America/Los_Angeles")
CHUNK = 25  # Yahoo's limit on player keys per request
KEEP_ON_RECOLLECT = ("standings.xml", "transactions.xml")


def date_range(start, end):
    """Inclusive list of ISO dates."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _next_day(day):
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def plan_dates(now_pt, season_start, season_end, done, max_backfill=14):
    """Stats days to collect on this run: every finished, not-yet-collected day."""
    target = (now_pt.date() - timedelta(days=1)).isoformat()
    if not season_start or target < season_start:
        return [] if target in done else [target]
    last = min(target, season_end) if season_end else target
    missing = [d for d in date_range(season_start, last) if d not in done]
    return missing[:max_backfill]


def week_for(day, weeks):
    for week in weeks:
        if week["start"] <= day <= week["end"]:
            return week["week"]
    return None


def correction_dates(day, weeks):
    """On the first day of a week, the whole previous week is fetched again
    so that Yahoo's after-the-fact stat corrections are picked up."""
    by_number = {w["week"]: w for w in weeks}
    this_week = week_for(day, weeks)
    previous = by_number.get((this_week or 0) - 1)
    if previous is None or by_number[this_week]["start"] != day:
        return []
    return date_range(previous["start"], previous["end"])


def resolve_league_key(api, season, league_id):
    games = parse.games(parse.xml_root(api.get(f"games;game_codes=nba;seasons={season}")))
    if not games:
        raise YahooError(f"Yahoo has no NBA game for season {season}")
    return f"{games[0]['game_key']}.l.{league_id}"


def _chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def _team_id(team_key):
    return team_key.rsplit(".t.", 1)[1]


def _collect_rosters_and_stats(api, store, league_key, team_keys, day, in_season):
    """Save each team's roster for `day` and, in season, every rostered
    player's stats for `day`. Returns warnings."""
    warnings = []
    player_keys = []
    for team_key in team_keys:
        try:
            xml = api.get(f"team/{team_key}/roster;date={day}")
        except YahooError as error:
            if in_season:
                raise
            # Before the season a roster may not exist yet; nothing depends on it.
            warnings.append(f"preseason roster unavailable, skipped the rest: {error}")
            break
        store.save(f"days/{day}/roster_t{_team_id(team_key)}.xml", xml)
        roster = parse.roster(parse.xml_root(xml))
        if in_season and roster["date"] and roster["date"] != day:
            warnings.append(
                f"roster for t.{_team_id(team_key)} came back dated {roster['date']}, asked for {day}"
            )
        for player in roster["players"]:
            if player["player_key"] not in player_keys:
                player_keys.append(player["player_key"])
    if in_season:
        for i, chunk in enumerate(_chunks(player_keys, CHUNK), start=1):
            xml = api.get(
                f"league/{league_key}/players;player_keys={','.join(chunk)}"
                f"/stats;type=date;date={day}"
            )
            store.save(f"days/{day}/stats_{i:02d}.xml", xml)
    return warnings




def run(api, store, season, league_id, now=None, max_backfill=14):
    """One scheduled collection run. Safe to call repeatedly."""
    now = now or datetime.now(timezone.utc)
    now_pt = now.astimezone(PT)
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    league_key = resolve_league_key(api, season, league_id)

    if not store.exists("league/game_weeks.xml"):
        game_key = league_key.split(".l.")[0]
        store.save("league/game_weeks.xml", api.get(f"game/{game_key}/game_weeks"))
    weeks = parse.game_weeks(parse.xml_root(store.load("league/game_weeks.xml")))

    settings_xml = api.get(f"league/{league_key}/settings")
    meta = parse.league_meta(parse.xml_root(settings_xml))
    start, end = meta["start_date"], meta["end_date"]

    summary = {"league_key": league_key, "collected": [], "corrected": []}
    dates = plan_dates(now_pt, start, end, set(store.done_dates()), max_backfill)
    if not dates:
        return summary  # nothing new: leave every stored file as it is
    store.save("league/settings.xml", settings_xml)

    teams_xml = api.get(f"league/{league_key}/teams")
    store.save("league/teams.xml", teams_xml)
    team_keys = [t["team_key"] for t in parse.teams(parse.xml_root(teams_xml))]
    target = (now_pt.date() - timedelta(days=1)).isoformat()
    saved_weeks = set()

    def save_scoreboard(week):
        # Fetched before a day is marked done, so a failure here gets retried.
        if week is None or week in saved_weeks:
            return
        xml = api.get(f"league/{league_key}/scoreboard;week={week}")
        store.save(f"weeks/scoreboard_w{week:02d}.xml", xml)
        saved_weeks.add(week)

    # Corrections run first: if they fail, the target day stays unfinished and
    # the whole run is retried next time.
    if target in dates:
        for day in correction_dates(target, weeks):
            info = store.run_info(day) if store.is_done(day) else {"live": False}
            kept = {
                rel: store.load(rel)
                for rel in store.day_files(day)
                if rel.rsplit("/", 1)[1] in KEEP_ON_RECOLLECT
            }
            store.clear_day(day)
            for rel, data in kept.items():
                store.save(rel, data)
            warnings = _collect_rosters_and_stats(api, store, league_key, team_keys, day, True)
            save_scoreboard(week_for(day, weeks))
            info.update({"corrected_at": stamp, "league_key": league_key, "warnings": warnings})
            store.mark_done(day, info)
            summary["corrected"].append(day)
        dates = [d for d in dates if not store.is_done(d)]

    for day in dates:
        live = day == target
        in_season = bool(start) and start <= day <= (end or day)
        store.clear_day(day)
        warnings = _collect_rosters_and_stats(api, store, league_key, team_keys, day, in_season)
        if live:
            store.save(f"days/{day}/transactions.xml", api.get(f"league/{league_key}/transactions"))
            if in_season:
                store.save(f"days/{day}/standings.xml", api.get(f"league/{league_key}/standings"))
        if in_season:
            save_scoreboard(week_for(day, weeks))
            if live:
                save_scoreboard(week_for(_next_day(day), weeks))
        store.mark_done(day, {
            "fetched_at": stamp, "league_key": league_key, "live": live, "warnings": warnings,
        })
        summary["collected"].append(day)
    return summary


def collect_draft(api, store, league_key, prev_season):
    """Save draft results plus, for every drafted player, Yahoo's average
    draft position and last season's totals. Returns warnings."""
    xml = api.get(f"league/{league_key}/draftresults")
    picks = parse.draft_results(parse.xml_root(xml))
    if not picks:
        return ["No draft picks yet - run this again after the draft."]
    store.save("league/draftresults.xml", xml)
    warnings = []
    prev_stats_ok = True
    for i, chunk in enumerate(_chunks([p["player_key"] for p in picks], CHUNK), start=1):
        base = f"league/{league_key}/players;player_keys={','.join(chunk)}"
        store.save(f"league/draft_players_{i:02d}.xml", api.get(f"{base}/draft_analysis"))
        if not prev_stats_ok:
            continue
        try:
            xml = api.get(f"{base}/stats;type=season;season={prev_season}")
            store.save(f"league/draft_prev_stats_{i:02d}.xml", xml)
        except YahooError as error:
            prev_stats_ok = False
            warnings.append(f"Could not fetch {prev_season} season stats: {error}")
    return warnings
