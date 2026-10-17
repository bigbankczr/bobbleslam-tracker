import collections
from load import openDatabase
from join import joinAll, HANDOUT_DECISIONS

def createTables(conn):
    """
    create tables for games, giveaway outcomes, appearances, home runs, and playerNights and bobbleheadHomers view
    :param conn: open connection from openDatabase()
    :return: none
    """
    conn.executescript("""CREATE TABLE IF NOT EXISTS games
                          (
    gamePk       INTEGER PRIMARY KEY,
    date         TEXT    NOT NULL,
    gameType     TEXT    NOT NULL,
    gameNumber   INTEGER NOT NULL,
    doubleHeader TEXT CHECK (doubleHeader IN ('N', 'Y', 'S')),
    homeTeamId   INTEGER NOT NULL,
    awayTeamId   INTEGER NOT NULL
                          );
CREATE TABLE IF NOT EXISTS giveawayOutcomes
(
    postId         INTEGER PRIMARY KEY REFERENCES posts (id),
    teamId         INTEGER NOT NULL,
    kind           TEXT    NOT NULL CHECK (kind IN
                                           ('cancelled', 'single', 'doubleheader', 'spring', 'package', 'noGame', 
                                            'preseason', 'rainout', 'afterSeason', 'upcoming', 'other')),
    handout        TEXT    NOT NULL CHECK (handout IN ('atGame', 'notAtGame', 'unclear')),
    handoutByHand  INTEGER NOT NULL CHECK (handoutByHand IN (0, 1)),
    giveawayGamePk INTEGER REFERENCES games (gamePk)
);
CREATE TABLE IF NOT EXISTS appearances
(
    mlbId    INTEGER NOT NULL REFERENCES players (id),
    gamePk   INTEGER NOT NULL REFERENCES games (gamePk),
    teamId   INTEGER NOT NULL,
    homeRuns INTEGER NOT NULL CHECK (homeRuns >= 0),
    PRIMARY KEY (mlbId, gamePk)
);
CREATE TABLE IF NOT EXISTS homeRuns
(
    gamePk        INTEGER NOT NULL,
    atBatIndex    INTEGER NOT NULL,
    mlbId         INTEGER NOT NULL,
    pitcherId     INTEGER NOT NULL,
    pitcherName   TEXT    NOT NULL,
    inning        INTEGER NOT NULL,
    halfInning    TEXT    NOT NULL CHECK (halfInning IN ('top', 'bottom')),
    rbi           INTEGER NOT NULL CHECK (rbi BETWEEN 1 AND 4),
    pitches       INTEGER NOT NULL CHECK (pitches >= 0),
    distance      REAL,
    pinchHit      INTEGER NOT NULL CHECK (pinchHit IN (0, 1)),
    leadoffInning INTEGER NOT NULL CHECK (leadoffInning IN (0, 1)),
    leadoffGame   INTEGER NOT NULL CHECK (leadoffGame IN (0, 1)),
    walkOff       INTEGER NOT NULL CHECK (walkOff IN (0, 1)),
    PRIMARY KEY (gamePk, atBatIndex),
    FOREIGN KEY (mlbId, gamePk) REFERENCES appearances (mlbId, gamePk)
);
DROP VIEW IF EXISTS bobbleheadHomers;
CREATE VIEW bobbleheadHomers AS
SELECT h.*,
       g.date,
       pl.fullName                         AS name,
       EXISTS (SELECT 1
               FROM honoreeMatches m
                        JOIN posts p ON p.id = m.postId
                        JOIN giveawayOutcomes o ON o.postId = p.id
               WHERE m.mlbId = h.mlbId
                 AND p.date = g.date
                 AND o.handout = 'atGame') AS confirmed
FROM homeRuns h
         JOIN games g ON g.gamePk = h.gamePk
         JOIN players pl ON pl.id = h.mlbId;
CREATE TABLE IF NOT EXISTS playerNights
    (
        mlbId           INTEGER NOT NULL REFERENCES players (id),
        date            TEXT NOT NULL,
        appeared        INTEGER NOT NULL CHECK (appeared IN (0, 1)),
        batted          INTEGER NOT NULL CHECK (batted IN (0, 1)),
        logHomeRuns     INTEGER NOT NULL CHECK (logHomeRuns >= 0),
        homeRuns        INTEGER NOT NULL CHECK (homeRuns >= 0),
        unclear         INTEGER NOT NULL CHECK (unclear IN (0, 1)),
        differentTeam   INTEGER CHECK (differentTeam IN (0, 1)),
        status          TEXT NOT NULL CHECK (status IN ('hit', 'miss', 'dnp', 'otherGame')),
        PRIMARY KEY (mlbId, date),
        CHECK (batted <= appeared), CHECK (logHomeRuns = 0 OR batted = 1),
        CHECK ((appeared = 1) = (differentTeam IS NOT NULL)),
        CHECK (homeRuns <= logHomeRuns)
);
            
""")

def clearJoin(conn):
    """
    deletes the tables created in homers.py, so storeAll can rewrite from scratch. does not commit.
    :param conn: open connection from openDatabase()
    :return: none
    """
    for table in ("playerNights", "homeRuns", "appearances", "giveawayOutcomes", "games"):
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
    :param conn: open connection from openDatabase()
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

def nightRows(joined):
    """
    one row per eligible player-night. status: hit, miss, dnp, otherGame. two homer counts, (1) logHomeRuns: every homer
    in game log that date. (2) homers that count, hit in the same game as a giveaway. only differs from (1) if dh
    :param joined: from join.joinAll()
    :return: (list) row dicts for insertNights
    :raises ValueError: if a stored home run belongs to no eligible night
    """
    homers = collections.Counter((row["mlbId"], row["date"]) for row in joined["homeRuns"])
    stray = set(homers) - set(joined["results"])
    if stray:
        raise ValueError(f"home runs on no eligible night: {sorted(stray)}")

    rows = []
    for key, result in joined["results"].items():
        mlbId, day = key
        homeRuns = homers[key]
        if homeRuns:
            status = "hit"
        elif not result["appeared"]:
            status = "dnp"
        elif result["homeRuns"] == 0:
            status = "miss"
        else:
            status = "otherGame"
        rows.append({"mlbId": mlbId, "date": day,"appeared": result["appeared"], "batted": result["batted"], "logHomeRuns": result["homeRuns"],
                     "homeRuns": homeRuns, "unclear": joined["eligible"][key]["unclear"], "differentTeam":
                         result["differentTeam"],"status": status})
    return rows

def insertNights(conn, nights):
    """
    insert every playerNight from nightRows(). does not commit.
    :param conn: open connection from openDatabase()
    :param nights: from nightRows()
    :return: none
    """
    conn.executemany("""INSERT INTO playerNights (mlbId, date, appeared, batted, logHomeRuns, homeRuns, unclear, differentTeam, 
                                                  status)
                        VALUES(:mlbId, :date, :appeared, :batted, :logHomeRuns, :homeRuns, :unclear, :differentTeam, :status)""", nights)

def storeAll(conn, joined):
    """
    rewrite every join table in one shot, all or nothing. prints count after commit
    :param conn: open connection from openDatabase(), tables already created
    :param joined: from join.joinAll()
    :return: none
    :raises sqlite3.IntegrityError: if any row violates a constraint. nothing is written
    :raises ValueError: if a stored home run belongs to no eligible night.
    """
    nights = nightRows(joined)
    with conn:
        clearJoin(conn)
        insertGames(conn, joined["games"])
        insertOutcomes(conn, joined["posts"])
        insertAppearances(conn, joined["appearances"])
        insertHomeRuns(conn, joined["homeRuns"])
        insertNights(conn, nights)

    for table in ("games", "giveawayOutcomes", "appearances", "homeRuns", "playerNights"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        print(f"{table}: {count:,} rows")
    total, confirmed = conn.execute("SELECT COUNT (*), SUM(confirmed) FROM bobbleheadHomers").fetchone()
    print(f"bobbleheadHomers: {total:,} rows, {confirmed:,} confirmed")
    for status, unclear, count in conn.execute("""SELECT status, unclear, COUNT(*) FROM playerNights
                                               GROUP BY status, unclear ORDER BY status, unclear"""):
        print(f"   {status:>9}   {'unclear' if unclear else 'clear':<7}   {count:,}")

if __name__ == "__main__":
    conn = openDatabase()
    createTables(conn)
    joined = joinAll(conn)
    storeAll(conn, joined)
    conn.close()