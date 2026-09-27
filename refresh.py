import time
import homers
import join
import load
import store
import teams
from match import matchBobbles, prepareIndex
from shapes import loadPosts

def stage(name):
    """
    print a header before each stage so the output reads as a log
    :param name: stage name
    :return: (float) start time for elapsed()
    """
    print(f"\n=== {name}")
    return time.time()

def elapsed(start):
    print(f"   ({time.time()-start:.0f}s)")

def main():
    """
    rebuild everything from raw files in stage order. stops on first error
    :return: none
    """
    conn = load.openDatabase()
    try:
        start = stage("load")
        load.createTables(conn)
        load.loadAll(conn, loadPosts())
        elapsed(start)

        start = stage("store")
        store.createTables(conn)
        store.storeAll(conn, matchBobbles(conn, prepareIndex(conn)))
        elapsed(start)

        start = stage("join")
        joined = join.joinAll(conn)
        join.printReport(joined)
        elapsed(start)

        start = stage("homers")
        homers.createTables(conn)
        homers.storeAll(conn, joined)
        elapsed(start)

        start = stage("teams")
        teams.createTables(conn)
        teams.storeAll(conn, teams.seasonsOnDisk())
        elapsed(start)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

