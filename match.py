import json
import os
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date

import requests

from load import openDatabase
from parser import normalizeBobbleType


URL = "https://statsapi.mlb.com/api/v1/sports/1/players"
HEADERS = {"User-Agent": "bobble-research/1.0"}
TIMEOUT = 30
DIRECTORY = "raw/statsapi"
APOSTROPHES = str.maketrans({"\u2019": "'"})


def seasonsNeeded(conn):
    """
    list every season that has at least one post, from the giveaway dates in the database
    :param conn: open connection from openDatabase()
    :return: (list) season years as ints
    """
    rows = conn.execute("""SELECT DISTINCT substr(date, 1, 4) AS season
                            FROM posts
                            ORDER BY season""")
    return [int(row["season"]) for row in rows]


def seasonPath(season):
    """
    path to one season's player list
    :param season: season year
    :return: (str) file path under DIRECTORY
    """
    return os.path.join(DIRECTORY, f"baseball_players_{season}.json")

def fetchSeason(season):
    """
    download one season's mlb player list from statsapi and save raw response. seasons already on disk are skipped,
    except the current.
    :param season: season year
    :return: none
    :raises requests.HTTPError: if stats api returns a 4/500 error
    """
    path = seasonPath(season)
    if os.path.exists(path) and season != date.today().year:
        return

    response = requests.get(URL, params={"season": season}, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()

    os.makedirs(DIRECTORY, exist_ok=True)
    temp = path + ".temp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write(response.text)
    os.replace(temp, path)

    print(f"{season}: {len(response.json()['people']):,} players")
    time.sleep(1)

def loadSeason(season):
    """
    read one season file and return its players
    :param season: season year
    :return: (list) player dicts from statsapi's "people" array
    :raises FileNotFoundError: if season was never fetched
            json.JSONDecodeError: if the file is truncated
    """
    path = seasonPath(season)
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)["people"]
        except json.decoder.JSONDecodeError as e:
            e.add_note(f"while loading {path}")
            raise

def nameKey(name):
    """
    normalize name for exact matching. applied to site and statsapi names. strips accents, normalizes apostrophes,
    periods and hyphens to spaces, merges initials (a j -> aj), collapses whitespace, and lowercases. suffixes are kept
    so sr's never match jr's
    :param name: raw name string, from a title or statsapi fullName
    :return: (str) comparison key
    """
    name = unicodedata.normalize('NFKD', name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.translate(APOSTROPHES)
    name = name.replace(".", " ").replace("-", " ")
    words, inRun = [], False
    for word in name.split():
        if len(word) == 1 and word.isalpha():
            if inRun:
                words[-1] += word
            else:
                words.append(word)
            inRun = True
        else:
            words.append(word)
            inRun = False
    return " ".join(words).lower()

# name level remaps for names nameKey can't reconcile: nicknames, name changes, typos, missing suffixes. applied in
# matchBobbles before lookup

BULLPENBOBBLES_TO_MLB = {nameKey(site): nameKey(mlb) for site, mlb in [
    # nickname vs legal name
    ("Kike Hernandez", "Enrique Hernández"),
    ("Nicholas Castellanos", "Nick Castellanos"),
    ("Peter Fairbanks", "Pete Fairbanks"),
    ("Zach Britton", "Zack Britton"),
    ("Tony Plush", "Nyjer Morgan"),
    ("Mike Gonzalez", "Michael Gonzalez"),

    # name changes
    ("Fausto Carmona", "Roberto Hernández"),
    ("Dee Gordon", "Dee Strange-Gordon"),
    ("Christian Encarnacion", "Christian Encarnacion-Strand"),

    # site typos
    ("Garrett Anderson", "Garret Anderson"),
    ("Jared Weaver", "Jered Weaver"),
    ("Hong-Chih Kuo", "Hung-Chih Kuo"),

    # missing suffix. only safe when bare name was never in mlb 99+. never: Vlad not yet: McCullers
    ("Luis Robert", "Luis Robert Jr."),
    ("Jerry Hairston", "Jerry Hairston Jr."),
    ("Rickie Weeks", "Rickie Weeks Jr."),
    ("Albert Almora", "Albert Almora Jr."),
    ("Lourdes Gurriel", "Lourdes Gurriel Jr."),
    ("Lance McCullers", "Lance McCullers Jr."),

    # title parse oddities
    ("Dansby", "Dansby Swanson"),
    ("Francisco Lindor WWE", "Francisco Lindor"),
]}

AMBIGUOUS_RESOLUTIONS = {(33066, 0): 408314, # José Reyes the Mets SS, not Jose Reyes the Cubs C
                         (33895, 0): 455759, # Chris Young the DBacks CF, not the Padres P
                         (35250, 0): 455759, # Chris Young the DBacks CF, not the Mets P
                         (35251, 0): 455759, # Chris Young the DBacks CF, not the Mets P
                         (37229, 0): 622110, # Matt Duffy the Rays 3B, not the Astros 3B
                         (37923, 0): 608070, # José Ramirez the Indians 3B, not the Braves P
                         (40568, 0): 669257, # Will Smith the Dodgers C, not the Astros P
                         (41269, 0): 669257, # Will Smith the Dodgers C, not the Rangers P
                         (41869, 0): 669257, # Will Smith the Dodgers C, not the Royals P
                         (57069, 0): 571970  # Max Muncy the Dodgers 3B, not the As 3B
}

def buildIndex(seasons):
    """
    per-season lookup from name key to the players holding that name. values are lists since players can share a name.
    stored as plain dicts.
    :param seasons: season years from seasonsNeeded()
    :return: (dict) {season: {nameKey: [{"id", "fullName"}, ...]}}
    """
    index = {}
    for season in seasons:
        byKey = defaultdict(list)
        for player in loadSeason(season):
            key = nameKey(player["fullName"])
            byKey[key].append({"id": player["id"], "fullName": player["fullName"]})
        index[season] = dict(byKey)
    return index

def unsafeRemaps(index):
    """
    finds remaps whose source name is a real mlb player in some season. remapping would steal rows.
    :param index: season index from buildIndex()
    :return: (list) (source, seasons) pairs, empty if all remaps are safe
    """
    unsafe = []
    for source in BULLPENBOBBLES_TO_MLB:
        seasons = [season for season, byKey in index.items() if source in byKey]
        if seasons:
            unsafe.append((source, seasons))
    return unsafe

ROLES = ("player", "alumni", "other", "untyped")
STATUSES = ("matched", "resolved", "ambiguous", "none")

def roleLabel(bobbleType):
    """
    reduce a raw bobble type to one label
    :param bobbleType: raw bobble type string from posts or None
    :return: (str) one of ROLES
    """
    roles = normalizeBobbleType(bobbleType)
    if "player" in roles:
        return "player"
    if "alumni" in roles:
        return "alumni"
    if not roles:
        return "untyped"
    return "other"

def matchBobbles(conn, index):
    """
    look up every in-scope honoree in the season index by name key, after applying BULLPENBOBBLES_TO_MLB. two or more
    rows decided by AMBIGUOUS_RESOLUTIONS when row has an entry
    :param conn: open connection from openDatabase()
    :param index: season index from buildIndex()
    :return: (list) one result dict per in-scope honoree. status matched/resolved/ambiguous/none, mlbId is id and
    mlbName is statsapi spelling for matched and resolved rows, None otherwise, with candidates for matching and whether
    the name was remapped
    :raises ValueError: if a resolution's id isn't among that row's candidates
    """
    rows = conn.execute("""SELECT h.postId, h.ordinal, h.name, p.date, p.team, p.bobbleType, p.link
                           FROM honorees h
                           JOIN posts p ON p.id = h.postId
                           WHERE p.inScope = 1
                           ORDER BY p.date, h.postId, h.ordinal""").fetchall()
    results = []
    for row in rows:
        season = int(row["date"][:4])
        key = nameKey(row["name"])
        remapped = key in BULLPENBOBBLES_TO_MLB
        key = BULLPENBOBBLES_TO_MLB.get(key, key)
        candidates = index[season].get(key, [])
        resolution = AMBIGUOUS_RESOLUTIONS.get((row["postId"], row["ordinal"]))

        if not candidates:
            status, mlbId, mlbName = "none", None, None
        elif len(candidates) == 1:
            status, mlbId, mlbName = "matched", candidates[0]["id"], candidates[0]["fullName"]
        elif resolution is not None:
            byId = {candidate["id"]: candidate for candidate in candidates}
            if resolution not in byId:
                raise ValueError(f"resolution {resolution} for ({row['postId']}, {row['ordinal']})"
                                 f"{row['name']!r} is not a candidate: {sorted(byId)}")
            status, mlbId, mlbName = "resolved", resolution, byId[resolution]["fullName"]
        else:
            status, mlbId, mlbName = "ambiguous", None, None

        results.append({"postId": row["postId"],
                        "ordinal": row["ordinal"],
                        "name": row["name"],
                        "date": row["date"],
                        "team": row["team"],
                        "link": row["link"],
                        "role": roleLabel(row["bobbleType"]),
                        "remapped": remapped,
                        "status": status,
                        "mlbId": mlbId,
                        "mlbName": mlbName,
                        "candidates": candidates})

    return results

if __name__ == "__main__":
    assert nameKey("Ronald Acuña Jr.") == nameKey("Ronald Acuna Jr.")
    assert nameKey("Travis d\u2019Arnaud") == nameKey("Travis d'Arnaud")
    assert nameKey("Yandy\xa0Díaz") == nameKey("Yandy Díaz")
    assert nameKey("Guerrero Jr., Vladimir ") == nameKey("Guerrero Jr., Vladimir")
    assert nameKey("Eric Young Sr.") != nameKey("Eric Young Jr.")
    assert nameKey("J.D. Martinez") == nameKey("J. D. Martinez")
    assert nameKey("JD Martinez") == nameKey("J.D. Martinez")
    assert nameKey("CC Sabathia") == nameKey("C.C. Sabathia")
    assert nameKey("AJ Pierzynski") == nameKey("A. J. Pierzynski")
    assert nameKey("Hyun-Jin Ryu") == nameKey("Hyun Jin Ryu")

    conn = openDatabase()
    seasons = seasonsNeeded(conn)
    for season in seasons:
        fetchSeason(season)

    index = buildIndex(seasons)
    unsafe = unsafeRemaps(index)
    if unsafe:
        raise ValueError(f"remaps whose source is a real player: {unsafe}")
    results = matchBobbles(conn, index)
    conn.close()

    print(f"\n{len(results):,} in-scope bobbles\n")
    counts = Counter((r["status"], r["role"]) for r in results)
    print(f"   {'':<10}" + "".join(f"{role:>9}" for role in ROLES))
    for status in STATUSES:
        print(f"   {status:<10}" + "".join(f"{counts[(status, role)]:>9,}" for role in ROLES))

    ambiguous = [r for r in results if r["status"] == "ambiguous"]
    print(f"\n{len(ambiguous)} ambiguous")
    for r in ambiguous:
        print(f"   {r['date']}   {r['name']!r:<28}   {r['team']}   {r['postId']}, {r['ordinal']}")
        print(f"       {[(c['id'], c['fullName']) for c in r['candidates']]}")

    queue = [r for r in results if r["status"] == "none" and r["role"] == "player"]
    print(f"\n{len(queue)} unmatched player rows")
    for r in queue:
        print(f"   {r['date']}   {r['name']!r:<28}   {r['team']}")
        print(f"      {r['link']}")

    deadRemaps = [r for r in results if r["remapped"] and r["status"] == "none"]
    print(f"\n{len(deadRemaps)} remapped rows still unmatched")
    for r in deadRemaps:
        print(f"   {r['date']}   {r['name']!r:<28}   {r['team']}")

    resolved = {(r["postId"], r["ordinal"]) for r in results if r["status"] == "resolved"}
    deadResolutions = set(AMBIGUOUS_RESOLUTIONS) - resolved
    print(f"\n{len(deadResolutions)} resolutions that matched no ambiguous row")
    for key in sorted(deadResolutions):
        print(f"   {key}   ->   {AMBIGUOUS_RESOLUTIONS[key]}")

    activeAlumni = [r for r in results if r["role"] == "alumni" and r["status"] != "none"]
    print(f"\n{len(activeAlumni)} alumni active that season")
    for r in activeAlumni:
        print(f"   {r['date']}   {r['name']!r:<28}   {r['team']}")
        print(f"      {r['link']}")