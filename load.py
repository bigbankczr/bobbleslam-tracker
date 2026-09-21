import json
import sqlite3

from shapes import loadPosts
from parser import parsePost

DATABASE = "bobbleheads.db"

def createTables(conn):
    """
    create tables for posts, honorees, themes w/ all relevant info.
    :param conn: open connection to sqlite3 database
    :return: none
    """
    conn.executescript("""
                       CREATE TABLE IF NOT EXISTS posts (
                                                            id INTEGER PRIMARY KEY,
                                                            date TEXT NOT NULL,
                                                            modified TEXT NOT NULL,
                                                            link TEXT NOT NULL,
                                                            team TEXT NOT NULL,
                                                            teamField TEXT,
                                                            league TEXT,
                                                            park TEXT,
                                                            attendance TEXT,
                                                            quantity TEXT,
                                                            sponsor TEXT,
                                                            position TEXT,
                                                            number TEXT,
                                                            variant TEXT,
                                                            bobbleType TEXT,
                                                            inScope INTEGER NOT NULL CHECK (inScope IN (0,1)),
                                                            batting INTEGER NOT NULL CHECK (batting IN (0,1)),
                                                            pitching INTEGER NOT NULL CHECK (pitching IN (0,1)),
                                                            tags TEXT,
                                                            categories TEXT,
                                                            fields TEXT NOT NULL,
                                                            verifiedByHand INTEGER NOT NULL DEFAULT 0 CHECK 
                                                                (verifiedByHand IN (0,1)));
                       CREATE TABLE IF NOT EXISTS honorees (
                                                               postId INTEGER NOT NULL REFERENCES posts(id),
                                                               ordinal INTEGER NOT NULL,
                                                               name TEXT NOT NULL,
                                                               verifiedByHand INTEGER NOT NULL DEFAULT 0 CHECK 
                                                                   (verifiedByHand IN (0,1)),
                                                               PRIMARY KEY (postId, ordinal));
                       CREATE TABLE IF NOT EXISTS themes (
                                                             postId INTEGER NOT NULL REFERENCES posts(id),
                                                             theme TEXT NOT NULL,
                                                             PRIMARY KEY (postId, theme)
                           );
                       """)

def openDatabase(path=DATABASE):
    """
    open the sqlite database, w/ foreign key enforcement on
    :param path: database file path ":memory:" for throwaways
    :return: (sqlite3.Connection) open connection
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def insertPost(conn, parsed):
    """
    write a parsed post into posts, honorees, and themes. posts and honorees already in the database is updated by fresh
    data unless verifiedByHand is set. themes are deleted and rewritten. does not commit.
    :param conn:  open connection from openDatabase()
    :param parsed: one dict from parser.parsePost()
    :return: none
    """
    def toJson(value):
        return None if value is None else json.dumps(value, ensure_ascii=False)

    values = dict(parsed)
    values["tags"] = toJson(parsed["tags"])
    values["categories"] = toJson(parsed["categories"])
    values["fields"] = toJson(parsed["fields"])

    conn.execute("""
                 INSERT INTO posts (id,date,modified, link, team, teamField, league, park, attendance, quantity, sponsor,
                                    position, number, variant, bobbleType, inScope, batting, pitching, tags, categories, 
                                    fields)
                 VALUES (:id, :date, :modified, :link, :team, :teamField, :league, :park, :attendance, :quantity, 
                         :sponsor, :position, :number, :variant, :bobbleType, :inScope, :batting, :pitching, :tags, 
                         :categories, :fields)
                 ON CONFLICT (id) DO UPDATE SET
                                                date = excluded.date,
                                                modified = excluded.modified,
                                                link = excluded.link,
                                                team = excluded.team,
                                                teamField = excluded.teamField,
                                                league = excluded.league,
                                                park = excluded.park,
                                                attendance = excluded.attendance,
                                                quantity = excluded.quantity,
                                                sponsor = excluded.sponsor,
                                                position = excluded.position,
                                                number = excluded.number,
                                                variant = excluded.variant,
                                                bobbleType = excluded.bobbleType,
                                                inScope = excluded.inScope,
                                                batting = excluded.batting,
                                                pitching = excluded.pitching,
                                                tags = excluded.tags,
                                                categories = excluded.categories,
                                                fields = excluded.fields WHERE posts.verifiedByHand = 0""", values)

    for ordinal, name in enumerate(parsed["names"]):
        conn.execute("""
                     INSERT INTO honorees (postId, ordinal, name)
                     VALUES (?, ?, ?)
                     ON CONFLICT (postId, ordinal) DO UPDATE SET name = excluded.name
                     WHERE honorees.verifiedByHand = 0""", (parsed["id"], ordinal, name))

    conn.execute("DELETE FROM themes WHERE postId = ?", (parsed["id"],))

    conn.executemany("INSERT INTO themes (postId, theme) VALUES(?,?)",
                     [(parsed["id"], theme) for theme in parsed["themes"]])

def loadAll(conn, posts):
    """
    parse and insert every post in one shot, all or nothing.
    :param conn: open connection from openDatabase(), tables already created
    :param posts: raw post dicts from shapes.loadPosts()
    :return: none
    :raises sqlite3.IntegrityError: if any row violates a constraint. nothing written.
    """
    with conn:
        for post in posts:
            try:
                insertPost(conn, parsePost(post))
            except Exception as e:
                e.add_note(f"while loading post {post['id']}  {post['link']}")
                raise
    for table in ("posts", "honorees", "themes"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count:,} rows")


if __name__ == "__main__":
    conn = openDatabase()
    createTables(conn)
    loadAll(conn, loadPosts())
    conn.close()