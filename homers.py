from load import openDatabase
from join import joinAll, HANDOUT_DECISIONS

def createTables(conn):
    """
    create tables for games, giveaway outcomes, appearances and home runs, and the bobbleheadHomers view
    :param conn: open connection from openDatabase()
    :return: none
    """
    conn.executescript("""CREATE TABLE IF NOT EXISTS games (gamePk INTEGER PRIMARY KEY,
                                                            date TEXT NOT NULL,
                                                            gameType TEXT NOT NULL,
                                                            gameNumber INTEGER NOT NULL,
                                                            doubleHeader TEXT CHECK (doubleHeader IN ('N', 'Y', 'S')),
                                                            homeTeamId INTEGER NOT NULL,
                                                            awayTeamId INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS giveawayOutcomes ( postId INTEGER PRIMARY KEY REFERENCES posts(id),
        teamId INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('single', 'doubleheader', 'spring', 'package', 'noGame', 'preseason', 
                                  'rainout', 'afterSeason', 'upcoming', 'other')),
        handout TEXT NOT NULL CHECK (handout IN ('atGame', 'notAtGame', 'unclear')),
        handoutByHand INTEGER NOT NULL CHECK (handoutByHand IN (0, 1)),
        giveawayGamePk INTEGER REFERENCES games(gamePk));
    CREATE TABLE IF NOT EXISTS appearances ( mlbId INTEGER NOT NULL REFERENCES players(id),
        gamePk INTEGER NOT NULL REFERENCES games(gamePk),
        teamId INTEGER NOT NULL,
        homeRuns INTEGER NOT NULL CHECK (homeRuns >= 0),
        PRIMARY KEY (mlbId, gamePk));
    CREATE TABLE IF NOT EXISTS homeRuns (gamePk INTEGER NOT NULL,
                                         atBatIndex INTEGER NOT NULL,
                                         mlbId INTEGER NOT NULL,
                                         pitcherId INTEGER NOT NULL,
                                         pitcherName TEXT NOT NULL,
                                         inning INTEGER NOT NULL,
                                         halfInning TEXT NOT NULL CHECK (halfInning IN ('top', 'bottom')),
                                         rbi INTEGER NOT NULL CHECK (rbi BETWEEN 1 AND 4),
                                         pitches INTEGER NOT NULL CHECK (pitches >= 0),
                                         distance REAL,
                                         pinchHit INTEGER NOT NULL CHECK (pinchHit IN (0, 1)),
                                         leadoffInning INTEGER NOT NULL CHECK (leadoffInning IN (0, 1)),
                                         leadoffGame INTEGER NOT NULL CHECK (leadoffGame IN (0, 1)),
                                         walkOff INTEGER NOT NULL CHECK (walkOff IN (0, 1)),
                                         PRIMARY KEY (gamePk, atBatIndex),
                                         FOREIGN KEY (mlbId, gamePk) REFERENCES appearances(mlbId, gamePk));
    DROP VIEW IF EXISTS bobbleheadHomers;
    CREATE VIEW bobbleheadHomers AS
    SELECT h.*, g.date, pl.fullName AS name,
           EXISTS (SELECT 1 
                   FROM honoreeMatches m
                            JOIN posts p ON p.id = m.postId
                            JOIN giveawayOutcomes o ON o.postId = p.id
                   WHERE m.mlbId = h.mlbId AND p.date = g.date AND o.handout = 'atGame') AS confirmed 
    FROM homeRuns h
             JOIN games g ON g.gamePk = h.gamePk
             JOIN players pl ON pl.id = h.mlbId;
""")

def clearJoin(conn):
    """
    deletes the tables created in homers.py, so storeAll can rewrite from scratch. does not commit.
    :param conn: open connection from openDatabase()
    :return: none
    """
    for table in ("homeRuns", "appearances", "giveawayOutcomes", "games"):
        conn.execute(f"DELETE FROM {table}")

def insertGames(conn, games):
    """
    insert every game from joinAll(). does not commit.
    :param conn: open connection from openDatabase()
    :param games: joined["games"]
    :return: none
    """
    conn.executemany("""INSERT INTO games (gamePk, date, gameType, gameNumber, doubleHeader, homeTeamId, awayTeamId)
                        VALUES (:gamePk, :date, :gameType, :gameNumber, :doubleHeader, :homeTeamId, :awayTeamId)""", games)

def insertOutcomes(conn, posts):
    """
    insert one outcome per giveaway from joinAll(). does not commit.
    :param conn: opem connection from openDatabase()
    :param posts: joined["posts"]
    :return: none
    """
    rows = [{**post, "handoutByHand": post["id"] in HANDOUT_DECISIONS} for post in posts]
    conn.executemany("""INSERT INTO giveawayOutcomes (postId, teamId, kind, handout, handoutByHand, giveawayGamePk) 
                        VALUES (:id, :teamId, :kind, :handout, :handoutByHand, :giveawayGame)""", rows)

def insertAppearances(conn, appearances):
    """
    insert every (player, game) appearance from joinAll(). does not commit.
    :param conn: open connection from openDatabase()
    :param appearances: joined["appearances"]
    :return: none
    """
    conn.executemany("""INSERT INTO appearances (mlbId, gamePk, teamId, homeRuns) 
                        VALUES (:mlbId, :gamePk, :teamId, :homeRuns)""", appearances)

def insertHomeRuns(conn, homeRuns):
    """
    insert every home run from joinAll(). does not commit.
    :param conn: open connection from openDatabase()
    :param homeRuns: joined["homeRuns"]
    :return: none
    """
    conn.executemany("""INSERT INTO homeRuns(gamePk, atBatIndex, mlbId, pitcherId, pitcherName, inning, halfInning, rbi, 
                                             pitches, distance, pinchHit, leadoffInning, leadoffGame, walkOff)
                        VALUES (:gamePk, :atBatIndex, :mlbId, :pitcherId, :pitcherName, :inning, :halfInning,
                                :rbi, :pitches, :distance, :pinchHit, :leadoffInning, :leadoffGame, :walkOff)""",
                     homeRuns)

def storeAll(conn, joined):
    """
    rewrite every join table in one shot, all or nothing. prints count after commit
    :param conn: ioen connection from openDatabase(), tables already created
    :param joined: from join.joinAll()
    :return: none
    :raises sqlite3.IntegrityError: if any row violates a constraint. nothing is written
    """
    with conn:
        clearJoin(conn)
        insertGames(conn, joined["games"])
        insertOutcomes(conn, joined["posts"])
        insertAppearances(conn, joined["appearances"])
        insertHomeRuns(conn, joined["homeRuns"])

    for table in ("games", "giveawayOutcomes", "appearances", "homeRuns"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        print(f"{table}: {count:,} rows")
    total, confirmed = conn.execute("SELECT COUNT (*), SUM(confirmed) FROM bobbleheadHomers").fetchone()
    print(f"bobbleheadHomers: {total:,} rows, {confirmed:,} confirmed")

if __name__ == "__main__":
    conn = openDatabase()
    createTables(conn)
    joined = joinAll(conn)
    storeAll(conn, joined)
    conn.close()