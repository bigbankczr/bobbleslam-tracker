import os
import time
import json
from datetime import date
from collections import Counter, defaultdict

import requests

from load import openDatabase

BASE = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "bobble-research/1.0"}
TIMEOUT = 30
GAMELOGS = "raw/statsapi/gamelogs"
TEAMS = "raw/statsapi/teams"
SCHEDULES = "raw/statsapi/schedules"
FEEDS = "raw/statsapi/feeds"
FEED_BASE = "https://statsapi.mlb.com/api/v1.1"
BULLPENBOBBLES_TO_MLB_TEAMS = {"Los Angeles Angels of Anaheim": "Los Angeles Angels"}
PLAYED = frozenset({"F"})
NOT_PLAYED = frozenset({"D", "C"})
UPCOMING = frozenset({"S", "P"})
KNOWN_STATES = PLAYED | NOT_PLAYED | UPCOMING
QUANTITY_AT_GAME = frozenset({"all fans", "all fans in attendance", "all fans while supplies last",
                              "all kids in attendance", "all kids & moms in attendance", "early arriving fans",
                              "all early arriving fans"})
QUANTITY_NOT_AT_GAME = frozenset({"season ticket holders", "kids club", "rewards club", "jr. jays", "ticket package",
                                  "ticket club members", "flex plan", "birthday package", "mvp package",
                                  "pride club members", "select group ticket holders", "soxfest", "fanfest",
                                  "purchase","special vip ticket", "select fans", "donation", "charity", "fan appreciation weekend"})

QUANTITY_UNCLEAR = frozenset({ "limited", "none"})
# regular seasons that started later than scheduled. dates before are preseason, between it and first game were canceled
ORIGINAL_OPENING_DAYS = {2020: "2020-03-26"} # covid season began late July
# giveaway game for doubleheader player-nights with a homer, decided by hand. (mlbId, date): giveaway gamePk
DOUBLEHEADER_GIVEAWAYS = {(114739, "2003-09-13"): 17185, # Jason Giambi game 1
    (607208, "2017-05-14"): 490664, # Trea Turner game 1
    (547989, "2019-07-03"): 567273, # José Abreu game 1
    (665489, "2022-07-02"): 661724, # Vlad Jr. game 1
    (596019, "2023-05-21"): 718099} # Lindor game 1
# hand-checked handouts for unclear bobbles. postId -> atGame or notAtGame, keyed by post.
HANDOUT_DECISIONS = {
    58538: "notAtGame",   # Hideki Matsui 2010-04-05: season-long ticket offer
    37364: "atGame",      # Altuve, Correa, Keuchel 2016-06-17: special ticket at the game
    37477: "atGame",      # A.J. Pierzynski 2016-07-15: special ticket at the game
    37482: "atGame",      # Wil Myers 2016-07-15: special ticket at the game
    39298: "atGame",      # Brandon Crawford 2019-05-20: special ticket at the game
    39536: "atGame",      # Joey Gallo 2019-07-12: special ticket at the game
    40052: "atGame",      # Freeman, Albies, Acuña 2021-04-26: special ticket at the game
    40921: "notAtGame",   # Mookie Betts 2022-08-13: fun run that fell on a game day not the game
    41062: "atGame",      # Ronald Acuña Jr. 2022-09-16: special ticket at the game
    41698: "atGame",      # Julio Rodríguez 2023-09-11: special ticket at the game
    41699: "atGame",      # Eugenio Suárez 2023-09-12: special ticket at the game
    41855: "atGame",      # Adolis García 2024-05-15: special ticket at the game
    42489: "atGame",      # Carlos Correa 2025-05-23: special ticket at the game
    42491: "atGame",      # Mauricio Dubón 2025-05-23: special ticket at the game
    55069: "atGame",      # Joe Ryan 2025-07-09: special ticket at the game
    55734: "atGame",      # Salvador Perez 2025-07-09: special ticket at the game
    58051: "atGame",      # Jeremy Peña 2026-07-22: special ticket at the game
}

def gameLogPath(mlbId, season):
    """
    path to a player-season's game logs
    :param mlbId: mlb player id
    :param season: season year
    :return: (str) file path under GAMELOGS
    """
    return os.path.join(GAMELOGS, f"gamelog_{mlbId}_{season}.json")

def fetchGameLog(mlbId, season):
    """
    download a player's regular season game logs, hitting and pitching, saves raw response. files on disk skipped,
    except current season files older than a day.
    :param mlbId: mlb player id
    :param season: season year
    :return: (bool) True if fetched, False if skipped
    :raises requests.RequestException: if stats api returns a 4/500 error, timeout, or dropped connection
    """
    path = gameLogPath(mlbId, season)
    if os.path.exists(path):
        if season != date.today().year:
            return False
        if time.time() - os.path.getmtime(path) < 24 * 60 * 60:
            return False
    response = requests.get(f"{BASE}/people/{mlbId}/stats",
                            params={"stats": "gameLog", "group": "hitting,pitching", "season": season},
                            headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    os.makedirs(GAMELOGS, exist_ok=True)
    temp = path + ".temp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write(response.text)
    os.replace(temp, path)
    time.sleep(1)
    return True

def loadGameLog(mlbId, season):
    """
    read one player-season's game log, hitting and pitching splits grouped by date
    :param mlbId: mlb player id
    :param season: season year
    :return: (dict) {date: [split, ...]} each split is keyed hitting or pitching
    :raises FileNotFoundError: if never fetched
            json.JSONDecodeError: if the file is truncated
    """
    path = gameLogPath(mlbId, season)
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            e.add_note(f"while loading {path}")
            raise
    byDate = defaultdict(list)
    for entry in data["stats"]:
        group = entry["group"]["displayName"]
        for split in entry["splits"]:
            byDate[split["date"]].append({**split, "group": group})
    return dict(byDate)

def playerSeasons(conn):
    """
    list every (player, season) with at least one bobblehead night, from matched and resolved honorees. one game log
    call per pair
    :param conn: open connection from openDatabase()
    :return: (list) (mlbId, season) pairs in season order
    """
    rows = conn.execute("""SELECT DISTINCT m.mlbId,
                                           CAST(substr(p.date, 1, 4) AS INTEGER) AS season 
                           FROM honoreeMatches m
                           JOIN posts p ON p.id = m.postId
                           WHERE m.mlbId IS NOT NULL
                           ORDER BY  season, m.mlbId""")
    return [(row["mlbId"], row["season"]) for row in rows]

def teamsPath(season):
    """
    path to one season's mlb team list
    :param season: season year
    :return: (str) file path under TEAMS
    """
    return os.path.join(TEAMS, f"teams_{season}.json")

def fetchTeams(season):
    """
    download one season's mlb team list from statsapi and save raw response. files on disk skipped, except current
    season files older than a day
    :param season: season year
    :return: (bool) True if fetched, False if skipped
    :raises requests.RequestException: if stats api returns a 4/500 error, timeout, or dropped connection
    """
    path = teamsPath(season)
    if os.path.exists(path):
        if season != date.today().year:
            return False
        if time.time() - os.path.getmtime(path) < 24 * 60 * 60:
            return False
    response = requests.get(f"{BASE}/teams", params={"sportId": 1, "season": season},
                            headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()

    os.makedirs(TEAMS, exist_ok=True)
    temp = path + ".temp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write(response.text)
    os.replace(temp, path)
    time.sleep(1)
    return True

def loadTeams(season):
    """
    read one season's team file
    :param season: season year
    :return: (list) team dicts from statsapi team array
    :raises FileNotFoundError: if season never fetched
            json.JSONDecodeError: if file is truncated
    """
    path = teamsPath(season)
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)["teams"]
        except json.JSONDecodeError as e:
            e.add_note(f"while loading {path}")
            raise

def buildTeamIndex(years):
    """
    per-season lookup from team name to team id
    :param years: season years
    :return: (dict) {season: {name: teamId}}
    """
    return {year: {team["name"]: team["id"] for team in loadTeams(year)} for year in years}

def giveawayTeams(conn, teamIndex):
    """
    team id for every (giveaway team, season) with a matched honoree. site names pass through BULLPENBOBBLES_TO_MLB_TEAMS,
    then exact name in a given season. if no matches, same name's id from any season(survives name changes)
    :param conn: open connection from openDatabase()
    :param teamIndex: from buildTeamIndex()
    :return: (dict) {(site team name, season): teamId}
    :raises ValueError: if a remaps source is a real team, lists every name that matched no id, or >1
    """
    unsafe = [source for source in BULLPENBOBBLES_TO_MLB_TEAMS if any(source in byName for byName in teamIndex.values())]
    if unsafe:
        raise ValueError(f"team remap whose source is a real team name: {unsafe}")
    rows = conn.execute("""SELECT DISTINCT p.team, CAST(substr(p.date, 1,4) AS INTEGER) AS season
                           FROM posts p JOIN honoreeMatches m ON m.postId = p.id
                           WHERE m.mlbId IS NOT NULL
                           ORDER BY season, p.team""")

    ids, failures = {}, []
    for row in rows:
        team, season = row["team"], row["season"]
        name = BULLPENBOBBLES_TO_MLB_TEAMS.get(team, team)
        if name in teamIndex[season]:
            ids[(team, season)] = teamIndex[season][name]
            continue
        found = {byName[name] for byName in teamIndex.values() if name in byName}
        if len(found) == 1:
            ids[(team, season)] = found.pop()
            print(f"   cross-season: {team!r} {season} -> {ids[(team, season)]}")
        else:
            failures.append((team, season, sorted(found)))
    if failures:
        raise ValueError(f"giveaway teams w/ no single id: {failures}")
    return ids

def schedulePath(teamId, season):
    """
    path to one team-season's schedule
    :param teamId: mlb team id
    :param season: season year
    :return: (str) file path under SCHEDULES
    """
    return os.path.join(SCHEDULES, f"schedule_{teamId}_{season}.json")

def fetchSchedule(teamId, season):
    """
    download one team-season's schedule, reg szn and spring training, save raw response. files on disk skipped, except
    current season files older than a day
    :param teamId: mlb team id
    :param season: season year
    :return: (bool) True if fetched, False if skipped
    :raises requests.RequestException: if stats api returns a 4/500 error, timeout, or dropped connection
    """
    path = schedulePath(teamId, season)
    if os.path.exists(path):
        if season != date.today().year:
            return False
        if time.time() - os.path.getmtime(path) < 24 * 60 * 60:
            return False
    response = requests.get(f"{BASE}/schedule",
                            params={"sportId": 1, "teamId": teamId, "season": season, "gameType": "R,S"},
                            headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    os.makedirs(SCHEDULES, exist_ok=True)
    temp = path + ".temp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write(response.text)
    os.replace(temp, path)
    time.sleep(1)
    return True

def loadSchedule(teamId, season):
    """
    read one team-season's schedule file, flattened to a list of games
    :param teamId: mlb team id
    :param season: season year
    :return:(list) game dicts, every date's games in file order
    :raises FileNotFoundError: if schedule never fetched
            json.JSONDecodeError: if file is truncated
    """
    path = schedulePath(teamId, season)
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            e.add_note(f"while loading {path}")
            raise
    return [game for day in data["dates"] for game in day["games"]]

def buildScheduleIndex(schedules):
    """
    per team-season lookup from date to that team's games on it
    :param schedules: (teamId, season) pairs
    :return: (dict) {(teamId, season): {officialDate: [game, ...]}}
    """
    index = {}
    for teamId, season in schedules:
        byDate = defaultdict(list)
        for game in loadSchedule(teamId, season):
            byDate[game["officialDate"]].append(game)
        index[(teamId, season)] = dict(byDate)
    return index

def seasonMarkers(scheduleIndex):
    """
    per-team season: first and last scheduled regular-season dates, w/ played makeup games keyed by original date
    :param scheduleIndex: from buildScheduleIndex()
    :return: (dict) {(teamId, season)}: {"first": date, "last": date, "makeups": {fromDate: makeupDate}}
    """
    markers = {}
    for key, byDate in scheduleIndex.items():
        regular = [day for day, games in byDate.items() if any(game["gameType"] == "R" for game in games)]
        makeups = {game["rescheduledFromDate"][:10]: game["officialDate"] for games in byDate.values()
                   for game in games
                   if game.get("rescheduledFromDate") and game["status"]["codedGameState"] in PLAYED}
        markers[key] = {"first": min(regular, default=None), "last": max(regular, default=None), "makeups": makeups}
    return markers

def giveaways(conn):
    """
    every post with a matched honoree, with what decides its handout
    :param conn: open connection from openDatabase()
    :return: (list) dicts with id, team, date, quantity, mlbId, fullName, in date order, one row per honoree
    """
    rows = conn.execute("""SELECT DISTINCT p.id, p.team, p.date, p.quantity, m.mlbId, pl.fullName
                           FROM posts p 
                                    JOIN honoreeMatches m ON m.postId = p.id 
                                    JOIN players pl ON pl.id = m.mlbId
                           WHERE m.mlbId IS NOT NULL
                           ORDER BY p.date, p.team, p.id""")
    return [dict(row) for row in rows]

def classifyGiveaway(games, day, today, markers):
    """
    decide what happened on one giveaway night, given the team's games that date
    :param games: that team's schedule entries with officialDate == day
    :param day: giveaway date, YYYY-MM-DD
    :param today: today's date, YYYY-MM-DD
    :param markers: that team-season's entry from seasonMarkers()
    :return: (tuple) (kind, played games) kind - upcoming, rainout, preseason, afterSeason, noGame, spring, single,
    doubleheader or other
    :raises ValueError: on a game state not in KNOWN_STATES
    """
    codes = {game["status"]["codedGameState"] for game in games}
    if codes - KNOWN_STATES:
        raise ValueError(f"unknown game state {sorted(codes - KNOWN_STATES)} on {day}")

    played = list({game["gamePk"]: game for game in games if game["status"]["codedGameState"] in PLAYED}.values())

    if not played:
        if day >= today:
            return "upcoming", played
        if day in markers["makeups"]:
            return "rainout", played
        first = ORIGINAL_OPENING_DAYS.get(int(day[:4]), markers["first"])
        if first and day < first:
            return "preseason", played
        if markers["last"] and day > markers["last"]:
            return "afterSeason", played
        return "noGame", played

    if all(game["gameType"] == "S" for game in played):
        return "spring", played
    if len(played) == 1:
        return "single", played
    if len(played) == 2 and all(game["doubleHeader"] in ("Y", "S") for game in played):
        return "doubleheader", played
    return "other", played



def handout(quantity):
    """
    whether a post's quantity says it was handed out at the game
    :param quantity: raw quantity text from posts, or None
    :return: (str) atGame, notAtGame, or unclear. None counts as atGame, since bullpenBobbles is backfilled
    :raises ValueError: on a value not in the known sets
    """
    if quantity is None:
        return "atGame"
    value = quantity.strip().lower()
    if value in QUANTITY_NOT_AT_GAME:
        return "notAtGame"
    if value in QUANTITY_UNCLEAR or "special" in value or "group" in value:
        return "unclear"
    if value in QUANTITY_AT_GAME or any(c.isdigit() for c in value):
        return "atGame"
    raise ValueError(f"unknown quantity {quantity!r}")

def classifyPlayerNight(numbers, giveawayTeamIds):
    """
    what an honoree did on a giveaway date, from his game logs that date.
    :param numbers: his numbers that day, from loadGameLog(). one per game, per group. doubleheaders and two-way gives
    >1
    :param giveawayTeamIds: team ids giving out bobblehead
    :return: (dict) appeared, games (gamePks), homeRuns (hitting lines) differentTeam
    """
    if not numbers:
        return {"appeared": False, "games": [], "homeRuns": 0, "differentTeam": None}
    teams = {number["team"]["id"] for number in numbers}
    return {"appeared": True,
            "games": sorted({number["game"]["gamePk"] for number in numbers}),
            "homeRuns": sum(number["stat"].get("homeRuns", 0) for number in numbers if number["group"] == "hitting"),
            "differentTeam": not (teams & giveawayTeamIds)}

def feedPath(gamePk):
    """
    path to one game's live feed
    :param gamePk: mlb game id
    :return: (str) file path under FEEDS
    """
    return os.path.join(FEEDS, f"feed_{gamePk}.json")

def fetchFeed(gamePk):
    """
    download a game's live feed and saves raw response. files on disk skipped, and only final scores are fetched
    :param gamePk: mlb game id
    :return: (bool) True if fetched, false if skipped
    :raises requests.RequestException: if stats api returns a 4/500 error, timeout, or dropped connection
    """
    path = feedPath(gamePk)
    if os.path.exists(path):
        return False
    response = requests.get(f"{FEED_BASE}/game/{gamePk}/feed/live", headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    os.makedirs(FEEDS, exist_ok=True)
    temp = path + ".temp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write(response.text)
    os.replace(temp, path)
    time.sleep(1)
    return True

def loadFeed(gamePk):
    """
    read a game's live feed
    :param gamePk: mlb game id
    :return: (dict) the whole feed
    :raises FileNotFoundError: if never fetched
            json.JSONDecodeError: if the file is truncated
    """
    path = feedPath(gamePk)
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            e.add_note(f"while loading {path}")
            raise

def homeRunsIn(feed, mlbId):
    """
    every home run a batter hit in a game, from its live feed
    :param feed: from loadFeed()
    :param mlbId: the batter's mlb id
    :return: (list) one dict per home run
    """
    plays = feed["liveData"]["plays"]["allPlays"]
    rows = []
    for i, play in enumerate(plays):
        if play["result"].get("eventType") != "home_run" or play["matchup"]["batter"]["id"] != mlbId:
            continue
        about = play["about"]
        pitches = [event for event in play["playEvents"] if event.get("isPitch")]
        previous = plays[i - 1]["about"] if i else None
        leadoffInning = previous is None or (previous["inning"], previous["halfInning"]) != (about["inning"], about["halfInning"])

        rows.append({"gamePk": feed["gamePk"],
                     "atBatIndex": about["atBatIndex"],
                     "mlbId": mlbId,
                     "pitcherId": play["matchup"]["pitcher"]["id"],
                     "pitcherName": play["matchup"]["pitcher"]["fullName"],
                     "inning": about["inning"],
                     "halfInning": about["halfInning"],
                     "rbi": play["result"]["rbi"],
                     "pitches": len(pitches),
                     "distance": pitches[-1].get("hitData", {}).get("totalDistance") if pitches else None,
                     "pinchHit": any(event.get("isSubstitution")
                                     and event.get("player", {}).get("id") == mlbId
                                     and event.get("position", {}).get("code") == "11"
                                     for event in play["playEvents"]),
                     "leadoffInning": leadoffInning,
                     "leadoffGame": leadoffInning and about["inning"] == 1,
                     "walkOff": (i == len(plays) - 1 and not about["isTopInning"]
                                 and play["result"]["homeScore"] > play["result"]["awayScore"])
            })

    return rows

if __name__ == "__main__":
    conn = openDatabase()
    seasons = playerSeasons(conn)
    print(f"{len(seasons):,} player-seasons")

    years = sorted({season for _, season in seasons})
    for year in years:
        fetchTeams(year)
    print(f"{len(years)} team lists")

    teamIds = giveawayTeams(conn, buildTeamIndex(years))
    print(f"{len(teamIds):,} (team, season) pairs")

    rows = giveaways(conn)
    unknown = set(HANDOUT_DECISIONS) - {row["id"] for row in rows}
    if unknown:
        raise ValueError(f"handout decisions for posts with no matched honoree: {sorted(unknown)}")
    badValues = {postId: value for postId, value in HANDOUT_DECISIONS.items() if value not in ("atGame", "notAtGame")}
    if badValues:
        raise ValueError(f"handout decisions must be atGame or notAtGame: {badValues}")
    posts = list({row["id"]: row for row in rows}.values())
    nights = sorted({(post["team"], post["date"]) for post in posts})
    print(f"{len(posts):,} giveaway posts, {len(nights):,} nights")

    conn.close()

    schedules = sorted({(teamId, season) for (_, season), teamId in teamIds.items()})
    fetched = 0
    for i, (teamId, season) in enumerate(schedules, 1):
        try:
            if fetchSchedule(teamId, season):
                fetched += 1
        except requests.RequestException as e:
            e.add_note(f"while fetching {teamId} {season} schedule")
            raise
        if i % 100 == 0:
            print(f"   {i:,} / {len(schedules):,} {fetched:,} fetched")
    print(f"{len(schedules):,} schedules  {fetched:,} fetched")

    fetched = 0
    for i, (mlbId, season) in enumerate(seasons, 1):
        try:
            if fetchGameLog(mlbId, season):
                fetched += 1
        except requests.RequestException as e:
            e.add_note(f"while fetching game log {mlbId} {season}")
            raise
        if i % 1000 == 0 or i == len(seasons):
            print(f"   {i:,} / {len(seasons):,} {fetched:,} fetched")

    scheduleIndex = buildScheduleIndex(schedules)
    markers = seasonMarkers(scheduleIndex)
    today = date.today().isoformat()

    nightKind = {}
    for team, day in nights:
        key = (teamIds[(team, int(day[:4]))], int(day[:4]))
        nightKind[(team, day)] = classifyGiveaway(scheduleIndex[key].get(day, []), day, today, markers[key])

    outcomes, byOutcome = Counter(), defaultdict(list)
    for post in posts:
        how = HANDOUT_DECISIONS.get(post["id"], handout(post["quantity"]))
        kind = "package" if how == "notAtGame" else nightKind[(post["team"], post["date"])][0]
        outcomes[kind] += 1
        byOutcome[kind].append(post)
    unclear = sum(1 for post in posts if HANDOUT_DECISIONS.get(post["id"], handout(post["quantity"])) == "unclear")

    print(f"\n{len(posts):,} giveaway posts")
    for kind, count in outcomes.most_common():
        print(f"   {kind:>14}: {count:>6,}")
    print(f"   ({unclear:,} unclear handouts: review only if a homer)")
    for kind in ("noGame", "rainout"):
        print(f"\n{kind}")
        for post in byOutcome[kind]:
            print(f"   {post['date']}   {post['team']}   {post['quantity']!r}")

    eligible = defaultdict(lambda: {"teams": set(), "unclear": True, "kinds": set(), "name": None})
    for row in rows:
        kind = nightKind[(row["team"], row["date"])][0]
        how = HANDOUT_DECISIONS.get(row["id"], handout(row["quantity"]))
        if how == "notAtGame" or kind not in ("single", "doubleheader"):
            continue
        night = eligible[(row["mlbId"], row["date"])]
        night["teams"].add(teamIds[(row["team"], int(row["date"][:4]))])
        night["unclear"] = night["unclear"] and how == "unclear"
        night["kinds"].add(kind)
        night["name"] = row["fullName"]

    logs, results = {}, {}
    for (mlbId, day), night in eligible.items():
        season = int(day[:4])
        if (mlbId, season) not in logs:
            logs[(mlbId, season)] = loadGameLog(mlbId, season)
        results[(mlbId, day)] = classifyPlayerNight(logs[(mlbId, season)].get(day,[]), night["teams"])

    appeared = sum(1 for result in results.values() if result["appeared"])
    homerNights = [key for key, result in results.items() if result["homeRuns"]]
    print(f"\n{len(results):,} eligible player-nights   {appeared:,} appeared   {len(results) - appeared:,} DNP")
    print(f"{len(homerNights)} homer nights, {sum(results[key]['homeRuns'] for key in homerNights)} home runs")
    print("\nhomers need review")
    for key in sorted(homerNights, key=lambda key: key[1]):
        night = eligible[key]
        if ("doubleheader" in night["kinds"] and key not in DOUBLEHEADER_GIVEAWAYS) or night["unclear"]:
            print(f"   {key[1]}   {night['name']}   HR {results[key]['homeRuns']}   "
                  f"{'doubleheader ' if 'doubleheader' in night['kinds'] else ''}{'unclear' if night['unclear'] else ''}")

    feedGames = sorted({gamePk for key in homerNights for gamePk in results[key]["games"]})
    fetched = 0
    for gamePk in feedGames:
        try:
            if fetchFeed(gamePk):
                fetched += 1
        except requests.RequestException as e:
            e.add_note(f"while fetching feed {gamePk}")
            raise
    print(f"\n{len(feedGames)} feeds   {fetched} fetched")

    homeRuns, unresolved = [], []
    for mlbId, day in homerNights:
        doubleheader = "doubleheader" in eligible[(mlbId, day)]["kinds"]
        giveawayGame = DOUBLEHEADER_GIVEAWAYS.get((mlbId, day))
        if doubleheader and giveawayGame is None:
            unresolved.append((mlbId, day))
            continue
        for gamePk in results[(mlbId, day)]["games"]:
            if doubleheader and gamePk != giveawayGame:
                continue
            for row in homeRunsIn(loadFeed(gamePk), mlbId):
                homeRuns.append({**row, "date": day, "name": eligible[(mlbId, day)]["name"]})

    for (mlbId, day), gamePk in DOUBLEHEADER_GIVEAWAYS.items():
        if (mlbId, day) not in results:
            raise ValueError(f"doubleheader giveaway for {mlbId} {day} matches no eligible player-night")
        if gamePk not in results[(mlbId, day)]["games"]:
            raise ValueError(f"doubleheader giveaway {gamePk} for {mlbId} {day} is not one of his games")

    print(f"{len(homeRuns)} home run rows   {len(unresolved)} doubleheaders unresolved")
