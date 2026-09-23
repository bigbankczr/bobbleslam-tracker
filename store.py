from load import openDatabase
from match import matchBobbles, prepareIndex

def createTables(conn):
    """
    creates tables for players and honoree matches. honoreeMatches references honorees and players
    :param conn: open connection to sqlite3 database
    :return: none
    """
    conn.executescript(""" 
                       CREATE TABLE IF NOT EXISTS players ( id INTEGER PRIMARY KEY,
                                                                fullName TEXT NOT NULL);
                       CREATE TABLE IF NOT EXISTS honoreeMatches ( postId INTEGER NOT NULL,
                                                                   ordinal INTEGER NOT NULL,
                                                                   mlbId INTEGER,
                                                                   status TEXT NOT NULL,
                                                                   remapped INTEGER NOT NULL,
                                                                   PRIMARY KEY (postId, ordinal),
                           FOREIGN KEY (postId, ordinal) REFERENCES honorees(postId, ordinal),
                           FOREIGN KEY (mlbId) REFERENCES players(id),
                           CHECK (remapped IN (0,1)),
                           CHECK (status IN ('matched', 'resolved', 'ambiguous', 'none')),
                           CHECK ((mlbId IS NULL) = (status IN ('ambiguous', 'none'))));""")

def playersIn(results):
    """
    collect every matched player from results, keyed on mlb id. dedupes, since a player can have >1 giveaway. arrives in
    date order, last write wins so the latest spelling of a name survives
    :param results: result dicts from match.matchBobbles()
    :return: (dict) {mlbId: fullName}
    """
    return {r["mlbId"]: r["mlbName"] for r in results if r["mlbId"] is not None}

def insertPlayers(conn, players):
    """
    upsert every player into the database, existing rows take fresh name, does not commit. upsert allows homeRuns to
    reference this table
    :param conn: open connection from openDatabase()
    :param players: {mlbId: fullName} from playersIn()
    :return: none
    """
    conn.executemany(""" INSERT INTO players (id, fullName) 
                         VALUES (?, ?) 
                         ON CONFLICT (id) DO UPDATE SET fullName = excluded.fullName""", players.items())

def insertMatches(conn, results):
    """
    delete every match row and rewrite from results. one row per in-scope honoree including misses. does not commit
    :param conn: open connection from openDatabase()
    :param results: result dicts from match.matchBobbles()
    :return: none
    """
    conn.execute("DELETE FROM honoreeMatches")
    rows = [(r["postId"], r["ordinal"], r["mlbId"], r["status"], r["remapped"]) for r in results]
    conn.executemany(""" INSERT INTO honoreeMatches (postId, ordinal, mlbId, status, remapped) 
                     VALUES (?, ?, ?, ?, ?)""", rows)

def storeAll(conn, results):
    """
    store players and matches in one shot, all or nothing. prints count after the commit.
    :param conn: open connection from openDatabase(), tables already created
    :param results: result dicts from match.matchBobbles()
    :return: none
    :raises sqlite3.IntegrityError: if any row violates a constraint, nothing writes.
    """
    players = playersIn(results)
    with conn:
        insertPlayers(conn, players)
        insertMatches(conn, results)

    for table in ("players", "honoreeMatches"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count:,} rows")


if __name__ == "__main__":
    conn = openDatabase()
    createTables(conn)
    index = prepareIndex(conn)
    results = matchBobbles(conn, index)
    storeAll(conn, results)
    conn.close()