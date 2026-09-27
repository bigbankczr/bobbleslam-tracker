import glob
import os
import re

from load import openDatabase
from join import TEAMS, loadTeams, teamsPath

TEAM_FILE_RE = re.compile(r"teams_(\d{4})\.json")

def createTables(conn):
    """
    creates teams lookup
    :param conn: open connection from openDatabase()
    :return: none
    """

    conn.executescript("""CREATE TABLE IF NOT EXISTS teams (id INTEGER NOT NULL,
                                                            season INTEGER NOT NULL, 
                                                            name TEXT NOT NULL, 
                                                            teamName TEXT NOT NULL, 
                                                            PRIMARY KEY (id, season));""")

def seasonsOnDisk(directory=TEAMS):
    """
    every season with a cached team file
    :param directory: team cache directory
    :return: (list) season years, sorted
    :raises ValueError: on a team file whose name has no season
            FileNotFoundError: if the directory holds no team files
    """
    seasons = []
    for path in sorted(glob.glob(os.path.join(directory, "teams_*.json"))):
        match = TEAM_FILE_RE.fullmatch(os.path.basename(path))
        if not match:
            raise ValueError(f"unrecognized team file: {path}")
        seasons.append(int(match.group(1)))
    if not seasons:
        raise FileNotFoundError(f"no team files in {directory}")
    return seasons

def teamRows(seasons):
    """
    one row per team per season, from cached files
    :param seasons: season years
    :return: (list) row dicts for insertTeams
    :raises KeyError: if a team  lacks id, name or teamName, names the file
    """
    rows = []
    for season in seasons:
        for team in loadTeams(season):
            try:
                rows.append({"id": team["id"], "season": season, "name": team["name"], "teamName": team["teamName"]})
            except KeyError as e:
                e.add_note(f"while reading {teamsPath(season)}, team {team.get('id')}")
                raise
    return rows

ORPHANS = """WITH used (source, teamId, season) AS 
                                 (SELECT 'giveawayOutcomes', o.teamId, CAST(substr(p.date, 1, 4) AS INTEGER)
                                 FROM giveawayOutcomes o JOIN posts p ON p.id = o.postId
                                 UNION
                                 SELECT 'appearances', a.teamId, CAST(substr(g.date, 1, 4) AS INTEGER)
                                 FROM appearances a JOIN games g ON g.gamePk = a.gamePk
                                 UNION
                                 SELECT 'games', homeTeamId, CAST(substr(date, 1, 4) AS INTEGER) FROM games
                                 UNION
                                 SELECT 'games', awayTeamId, CAST(substr(date, 1, 4) AS INTEGER) FROM games)
                        SELECT u.source, u.teamId, u.season 
                        FROM used u
                        LEFT JOIN teams t ON t.id = u.teamId AND t.season = u.season
                        WHERE t.id IS NULL
                        ORDER BY u.season, u.teamId"""

def storeAll(conn, seasons):
    """
    rewrite the teams table from cached files and checks if every team id in the join tables has a name, all or nothing.
    prints count after commit
    :param conn: open connection from openDatabase()
    :param seasons: from seasonsOnDisk()
    :return: None
    :raises ValueError: if any team id in the join tables has no row for season. nothing written
            sqlite3.IntegrityError: on a duplicate (id, season) nothing written
    """
    rows = teamRows(seasons)
    with conn:
        conn.execute("DELETE FROM teams")
        conn.executemany("""INSERT INTO teams (id, season, name, teamName) VALUES (:id, :season, :name, :teamName)""", rows)
        orphans = conn.execute(ORPHANS).fetchall()
        if orphans:
            raise ValueError(f"team ids with no name for their season: {[tuple(r) for r in orphans]}")

    count = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    print(f"teams: {count:,} rows across {len(seasons)} seasons")

if __name__ == "__main__":
    conn = openDatabase()
    createTables(conn)
    storeAll(conn, seasonsOnDisk())
    conn.close()