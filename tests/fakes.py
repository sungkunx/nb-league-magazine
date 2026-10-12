"""Test helpers: a stand-in Yahoo API that answers from fixtures."""
import re
from pathlib import Path

from nbl.yahoo import YahooError

FIX = Path(__file__).parent / "fixtures"
NS = 'xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng"'
LEAGUE = "470.l.80126"


def fixture(name) -> bytes:
    return (FIX / name).read_bytes()


def roster_xml(team_key, day, players) -> bytes:
    """players: list of (player_key, name, slot)."""
    rows = "".join(
        f"<player><player_key>{key}</player_key><name><full>{name}</full></name>"
        f"<editorial_team_abbr>NBA</editorial_team_abbr><display_position>G</display_position>"
        f"<selected_position><position>{slot}</position></selected_position></player>"
        for key, name, slot in players
    )
    return (
        f"<fantasy_content {NS}><team><team_key>{team_key}</team_key>"
        f"<roster><date>{day}</date><players>{rows}</players></roster></team></fantasy_content>"
    ).encode()


def stats_xml(day, lines) -> bytes:
    """lines: list of (player_key, name, {stat_id: value})."""
    rows = "".join(
        f"<player><player_key>{key}</player_key><name><full>{name}</full></name>"
        f"<player_stats><date>{day}</date><stats>"
        + "".join(f"<stat><stat_id>{i}</stat_id><value>{v}</value></stat>" for i, v in stats.items())
        + "</stats></player_stats></player>"
        for key, name, stats in lines
    )
    return f"<fantasy_content {NS}><league><players>{rows}</players></league></fantasy_content>".encode()


class FakeYahoo:
    """Answers API paths like the real service would, and records every path.

    rosters: {team_key: [(player_key, name, slot), ...]} served for any date.
    """

    def __init__(self, rosters=None, roster_date=None, fail=()):
        self.rosters = rosters or {
            f"{LEAGUE}.t.1": [("470.p.1", "Alpha One", "PG"), ("470.p.2", "Alpha Two", "BN")],
            f"{LEAGUE}.t.2": [("470.p.3", "Bravo One", "C")],
        }
        self.roster_date = roster_date  # force the date Yahoo reports back
        self.fail = fail  # path fragments that raise YahooError
        self.paths = []
        self.calls = 0

    def get(self, path):
        self.paths.append(path)
        self.calls += 1
        for fragment in self.fail:
            if fragment in path:
                raise YahooError(f"GET {path} failed (HTTP 400)", 400)
        if path.startswith("users;use_login=1/"):
            return fixture("user_leagues.xml")
        if path.startswith("games;"):
            return fixture("games.xml")
        if path.endswith("/game_weeks"):
            return fixture("game_weeks.xml")
        if path.endswith("/settings"):
            return fixture("settings.xml")
        if path.endswith("/teams"):
            return fixture("teams.xml")
        if path.endswith("/standings"):
            return fixture("standings.xml")
        if path.endswith("/transactions"):
            return fixture("transactions.xml")
        if path.endswith("/draftresults"):
            return fixture("draftresults.xml")
        if "/scoreboard;week=" in path:
            return fixture("scoreboard_w1.xml")
        m = re.fullmatch(r"team/(.+)/roster;date=(\d{4}-\d\d-\d\d)", path)
        if m:
            team_key, day = m.groups()
            return roster_xml(team_key, self.roster_date or day, self.rosters[team_key])
        m = re.search(r"/players;player_keys=([^/]+)/stats;type=date;date=(\d{4}-\d\d-\d\d)$", path)
        if m:
            keys, day = m.groups()
            return stats_xml(day, [(k, k, {"12": "10"}) for k in keys.split(",")])
        if "/draft_analysis" in path:
            return fixture("players_draft.xml")
        if "/stats;type=season" in path:
            return stats_xml("", [("470.p.5352", "Nikola Jokic", {"12": "2100"})])
        raise YahooError(f"GET {path} failed (HTTP 404)", 404)

    def count(self, fragment):
        return sum(1 for p in self.paths if fragment in p)
