import csv
import itertools
import operator
import os

from load import openDatabase

EXPORT = "export"
# (status, unclear, batted) -> display color
DISPLAY = {
    ("hit", 0, 1): "green",
    ("hit", 1, 1): "green",
    ("miss", 0, 1): "red",
    ("miss", 1, 1): "grey",
    ("miss", 0, 0): "grey",
    ("miss", 1, 0): "grey",
    ("dnp", 0, 0): "grey",
    ("dnp", 1, 0): "grey",
    ("otherGame", 0, 1): "grey"
}

NIGHT_POSTS = """WITH nightPosts AS
         (SELECT m.mlbId, p.date, p.id AS postId, p.link, p.variant, o.teamId, h.name AS honoree
          FROM honoreeMatches m
                   JOIN honorees h ON h.postId = m.postId and h.ordinal = m.ordinal
                   JOIN posts p on p.id = m.postId
                   JOIN giveawayOutcomes o ON o.postId = p.id
          WHERE m.mlbId IS NOT NULL
            AND o.kind IN ('single', 'doubleheader')),
     postThemes AS
         (SELECT postId, GROUP_CONCAT(theme, ', ') AS themes
          FROM themes
          GROUP BY postId)
SELECT pn.date,
       pn.mlbId,
       pl.fullName AS player,
       t.name      AS team,
       CASE
           WHEN np.variant IS NULL THEN np.honoree
           ELSE np.honoree || ' (' || np.variant || ')'
           END     AS bobblehead,
       pt.themes,
       np.link,
       pn.status,
       pn.unclear,
       pn.appeared, 
       pn.batted,
       pn.homeRuns,
       pn.logHomeRuns,
       pn.differentTeam
FROM playerNights pn
         JOIN players pl ON pl.id = pn.mlbId
         JOIN nightPosts np ON np.mlbId = pn.mlbId AND np.date = pn.date
         JOIN teams t ON t.id = np.teamId AND t.season = CAST(substr(pn.date, 1, 4) AS INTEGER)
         LEFT JOIN postThemes pt ON pt.postId = np.postId
ORDER BY pn.date, pl.fullName, pn.mlbId, np.postId"""

HOMERS = """SELECT h.date,
       h.mlbId,
       h.name        AS player,
       t.name        AS team,
       ot.name       AS opponent,
       h.inning,
       h.halfInning,
       h.rbi,
       h.rbi = 4     AS grandSlam,
       h.pitcherName AS pitcher,
       h.pitcherId,
       h.pitches,
       h.distance,
       h.pinchHit,
       h.leadoffInning,
       h.leadoffGame,
       h.walkOff,
       h.confirmed,
       h.gamePk,
       h.atBatIndex
FROM bobbleheadHomers h
         JOIN appearances a ON a.mlbId = h.mlbId AND a.gamePk = h.gamePk
         JOIN games g ON g.gamePk = h.gamePk
         JOIN teams t ON t.id = a.teamId and t.season = CAST(substr(h.date, 1, 4) AS INTEGER)
         JOIN teams ot ON ot.id = CASE WHEN a.teamId = g.homeTeamId THEN g.awayTeamId ELSE g.homeTeamId END
    AND ot.season = t.season
ORDER BY h.date, h.gamePk, h.atBatIndex"""

def checkCount(conn, rows, source):
    """
    check an export has exactly one row per row in source
    :param conn: open connection from openDatabase()
    :param rows: export rows dicts
    :param source: table the export comes from
    :return: none
    :raises ValueError: if the export is empty or count differs from source
    """
    expected = conn.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0]
    if not rows or len(rows) != expected:
        raise ValueError(f"export from {source}: {len(rows):,} rows, table has {expected:,}")

def joinValues(values):
    """
    join values for one cell
    :param values: strings, in post order
    :return: (str) values joined with ' / ' or None if none
    """
    return " / ".join(values) if values else None

def mergeNight(posts):
    """
    fold one night's post rows into one row. bobblehead and link keep one entry per post in order
    team and themes are distinct
    :param posts: row dicts for (mlbId, date) in postId order
    :return: (dict) one night row
    """
    row = dict(posts[0])
    row["team"] = joinValues(list(dict.fromkeys(p["team"] for p in posts)))
    row["themes"] = joinValues(list(dict.fromkeys(p["themes"] for p in posts if p["themes"] is not None)))
    row["bobblehead"] = joinValues([p["bobblehead"] for p in posts])
    row["link"] = joinValues([p["link"] for p in posts])
    return row

def buildNights(conn):
    """
    one row per playerNights row, with display color
    :param conn: open connection from openDatabase()
    :return: (list) row dicts for nights.csv
    :raises ValueError: on a row count mismatch
    :raises KeyError: on a (status, unclear) pair not in DISPLAY
    """
    posts = [dict(row) for row in conn.execute(NIGHT_POSTS)]
    nights = [mergeNight(list(group)) for _, group in itertools.groupby(posts, key=operator.itemgetter("mlbId",
                                                                                                       "date"))]
    checkCount(conn, nights, "playerNights")
    for row in nights:
        try:
            row["display"] = DISPLAY[(row["status"], row["unclear"], row["batted"])]
        except KeyError as e:
            e.add_note(f"no display color for {row['player']} {row['date']}")
            raise
    return nights

def buildHomers(conn):
    """
    one row per home run
    :param conn: open connection from openDatabase()
    :return: (list) row dicts for homers.csv
    :raises ValueError: on a row count mismatch
    """
    rows = [dict(row) for row in conn.execute(HOMERS)]
    checkCount(conn, rows, "homeRuns")
    return rows

def writeCsv(name, rows):
    """
    write rows to export /<name> using a temp file. None becomes an empty cell
    :param name: file name, eg nights.csv
    :param rows: rows dicts, all with same keys
    :return: none
    """
    path = os.path.join(EXPORT, name)
    temp = path + ".temp"
    with open(temp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp, path)
    print(f"{name}: {len(rows):,} rows")

def exportAll(conn):
    """
    build and check both exports, and write. nothing written unless both are clean
    :param conn: open connection from openDatabase()
    :return: none
    :raises ValueError: on a row count mismatch
    :raises KeyError: on an unlisted (status, unclear) pair
    """
    nights = buildNights(conn)
    homers = buildHomers(conn)
    os.makedirs(EXPORT, exist_ok=True)
    writeCsv("nights.csv", nights)
    writeCsv("homers.csv", homers)

if __name__ == "__main__":
    conn = openDatabase()
    try:
        exportAll(conn)
    finally:
        conn.close()
