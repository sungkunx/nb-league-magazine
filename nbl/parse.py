"""Yahoo Fantasy XML -> plain rows.

Every function takes the root element of one API response (see xml_root) and
returns dicts/lists of plain values. Stat values are kept as the raw strings
Yahoo sent ("27", ".556", "10/18", "-"); use number() / ratio() to read them.
"""
import xml.etree.ElementTree as ET


def xml_root(data: bytes) -> ET.Element:
    """Parse a response and drop the XML namespace so tags are plain names."""
    root = ET.fromstring(data)
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


# ---- value helpers -------------------------------------------------------

def _text(el, path):
    """Text of a child, or None when the child is missing or empty."""
    if el is None:
        return None
    value = el.findtext(path)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int(el, path):
    value = _text(el, path)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(el, path):
    return _text(el, path) == "1"


def number(value):
    """'27' -> 27.0, '.556' -> 0.556, '-' / '' / None -> None."""
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def ratio(value):
    """'10/18' -> (10.0, 18.0); '-/-' or anything else -> None."""
    if not value or "/" not in value:
        return None
    made, attempted = (number(part) for part in value.split("/", 1))
    if made is None or attempted is None:
        return None
    return made, attempted


def _stats(el):
    """<stats><stat><stat_id/><value/></stat>... -> {stat_id: raw value}."""
    out = {}
    if el is None:
        return out
    for stat in el.findall("stats/stat"):
        out[_text(stat, "stat_id")] = _text(stat, "value") or ""
    return out


# ---- league --------------------------------------------------------------

def league_meta(root):
    lg = root.find("league")
    return {
        "league_key": _text(lg, "league_key"),
        "league_id": _text(lg, "league_id"),
        "name": _text(lg, "name"),
        "season": _int(lg, "season"),
        "num_teams": _int(lg, "num_teams"),
        "scoring_type": _text(lg, "scoring_type"),
        "draft_status": _text(lg, "draft_status"),
        "current_week": _int(lg, "current_week"),
        "start_week": _int(lg, "start_week"),
        "end_week": _int(lg, "end_week"),
        "start_date": _text(lg, "start_date"),
        "end_date": _text(lg, "end_date"),
    }


def settings(root):
    s = root.find("league/settings")
    return {
        "playoff_start_week": _int(s, "playoff_start_week"),
        "num_playoff_teams": _int(s, "num_playoff_teams"),
        "max_weekly_adds": _int(s, "max_weekly_adds"),
        "max_adds": _int(s, "max_adds"),
        "trade_end_date": _text(s, "trade_end_date"),
    }


def stat_categories(root):
    return [
        {
            "stat_id": _text(stat, "stat_id"),
            "name": _text(stat, "name"),
            "display_name": _text(stat, "display_name"),
            "lower_is_better": _text(stat, "sort_order") == "0",
            "is_display_only": _flag(stat, "is_only_display_stat"),
        }
        for stat in root.findall("league/settings/stat_categories/stats/stat")
    ]


def roster_positions(root):
    return [
        {
            "position": _text(pos, "position"),
            "count": _int(pos, "count"),
            # None when Yahoo omits the flag: unknown, not "bench".
            "is_starting": None if _text(pos, "is_starting_position") is None
            else _flag(pos, "is_starting_position"),
        }
        for pos in root.findall("league/settings/roster_positions/roster_position")
    ]


def game_weeks(root):
    return [
        {"week": _int(w, "week"), "start": _text(w, "start"), "end": _text(w, "end")}
        for w in root.findall("game/game_weeks/game_week")
    ]


def games(root):
    return [
        {"game_key": _text(g, "game_key"), "season": _int(g, "season")}
        for g in root.findall("games/game")
    ]


def user_leagues(root):
    out = []
    for game in root.findall("users/user/games/game"):
        for lg in game.findall("leagues/league"):
            out.append({
                "game_key": _text(game, "game_key"),
                "season": _int(game, "season"),
                "league_key": _text(lg, "league_key"),
                "league_id": _text(lg, "league_id"),
                "name": _text(lg, "name"),
                "num_teams": _int(lg, "num_teams"),
                "is_finished": _flag(lg, "is_finished"),
            })
    return out


# ---- teams ---------------------------------------------------------------

def teams(root):
    return [
        {
            "team_key": _text(t, "team_key"),
            "team_id": _int(t, "team_id"),
            "name": _text(t, "name"),
            "manager": _text(t, "managers/manager/nickname"),
            "moves": _int(t, "number_of_moves"),
            "trades": _int(t, "number_of_trades"),
            "adds_week": _int(t, "roster_adds/coverage_value"),
            "adds_used": _int(t, "roster_adds/value"),
        }
        for t in root.findall("league/teams/team")
    ]


def standings(root):
    out = []
    for t in root.findall("league/standings/teams/team"):
        st = t.find("team_standings")
        out.append({
            "team_key": _text(t, "team_key"),
            "rank": _int(st, "rank"),
            "wins": _int(st, "outcome_totals/wins"),
            "losses": _int(st, "outcome_totals/losses"),
            "ties": _int(st, "outcome_totals/ties"),
            "pct": number(_text(st, "outcome_totals/percentage")),
            "playoff_seed": _int(st, "playoff_seed"),
        })
    return out


def scoreboard(root):
    out = []
    for m in root.findall("league/scoreboard/matchups/matchup"):
        out.append({
            "week": _int(m, "week"),
            "week_start": _text(m, "week_start"),
            "week_end": _text(m, "week_end"),
            "status": _text(m, "status"),
            "is_playoffs": _flag(m, "is_playoffs"),
            "is_consolation": _flag(m, "is_consolation"),
            "is_tied": _flag(m, "is_tied"),
            "winner_team_key": _text(m, "winner_team_key"),
            "teams": [
                {
                    "team_key": _text(t, "team_key"),
                    "name": _text(t, "name"),
                    "points": number(_text(t, "team_points/total")),
                    "stats": _stats(t.find("team_stats")),
                }
                for t in m.findall("teams/team")
            ],
            "stat_winners": [
                {
                    "stat_id": _text(w, "stat_id"),
                    "winner_team_key": _text(w, "winner_team_key"),
                    "is_tied": _flag(w, "is_tied"),
                }
                for w in m.findall("stat_winners/stat_winner")
            ],
        })
    return out


# ---- players -------------------------------------------------------------

def _player(p):
    return {
        "player_key": _text(p, "player_key"),
        "name": _text(p, "name/full"),
        "nba_team": _text(p, "editorial_team_abbr"),
        "position": _text(p, "display_position"),
        "status": _text(p, "status") or "",
    }


def roster(root):
    team = root.find("team")
    return {
        "team_key": _text(team, "team_key"),
        "date": _text(team, "roster/date"),
        "players": [
            {**_player(p), "slot": _text(p, "selected_position/position")}
            for p in team.findall("roster/players/player")
        ],
    }


def player_stats(root):
    out = []
    for p in root.findall("league/players/player"):
        ps = p.find("player_stats")
        stats = _stats(ps)
        played = any(
            number(v) is not None or ratio(v) is not None for v in stats.values()
        )
        out.append({
            **_player(p),
            "date": _text(ps, "date"),
            "season": _int(ps, "season"),
            "stats": stats,
            "played": played,
        })
    return out


def players_meta(root):
    out = []
    for p in root.findall("league/players/player"):
        da = p.find("draft_analysis")
        out.append({
            **_player(p),
            "average_pick": number(_text(da, "average_pick")),
            "average_round": number(_text(da, "average_round")),
            "percent_drafted": number(_text(da, "percent_drafted")),
        })
    return out


# ---- transactions and draft ----------------------------------------------

def transactions(root):
    out = []
    for t in root.findall("league/transactions/transaction"):
        players = []
        for p in t.findall("players/player"):
            td = p.find("transaction_data")
            players.append({
                **_player(p),
                "action": _text(td, "type"),
                "source_type": _text(td, "source_type"),
                "source_team_key": _text(td, "source_team_key"),
                "destination_type": _text(td, "destination_type"),
                "destination_team_key": _text(td, "destination_team_key"),
            })
        out.append({
            "transaction_key": _text(t, "transaction_key"),
            "type": _text(t, "type"),
            "status": _text(t, "status"),
            "timestamp": _int(t, "timestamp"),
            "trader_team_key": _text(t, "trader_team_key"),
            "tradee_team_key": _text(t, "tradee_team_key"),
            "players": players,
        })
    return out


def draft_results(root):
    return [
        {
            "pick": _int(d, "pick"),
            "round": _int(d, "round"),
            "team_key": _text(d, "team_key"),
            "player_key": _text(d, "player_key"),
        }
        for d in root.findall("league/draft_results/draft_result")
    ]
