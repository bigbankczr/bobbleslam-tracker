# Bobbleslam Tracker
#### Inspired by Manny Ramirez
On July 22, 2009, the Dodgers gave away 56,000 Manny bobbleheads. He was hit in the hand by a pitch the day before and 
left out of the starting lineup. Joe Torre called him to pinch hit with the bases loaded in a tie game. He took the 
first pitch he saw over the Mannywood sign in left for a grand slam. I was sitting down the first base line that night 
with my dad and tios, 5 years old with the bobblehead in my hand and to this day it remains one of my favorite Dodger 
Stadium memories. It also turns out no one's ever checked how often this has happened.

So, I made a six-stage ETL pipeline that finds every home run hit by an MLB player on his own bobblehead night. Scrapes 4,241 
stadium giveaway records, resolves the honored players to MLB identities, and joins them against official schedules, 
game logs and play-by-play: **208** confirmed bobblehead-night home runs, 1999-2026.

### How It's Made
**Tech:** Python, SQLite, requests, RegEx, WordPress REST API, MLB Stats API

| Stage | File                   | What it does
|-------|------------------------|---
| fetch | `fetch.py`             | Pulls 4,241 giveaways from a WordPress API
| probe | `shapes.py`            | Counts 25 field labels across 135 distinct shapes
| parse | `parser.py`            | Turns HTML blobs into records; titles into honorees, teams, variants
| load  | `load.py`              | Writes 4,241 posts, 4,460 honorees, 1,164 themes into SQLite
| match | `match.py -> store.py` | Resolves 2,164 of 2,267 players against 37,803 player-seasons
| join  | `join.py -> homers.py` | Joins schedules, game logs and play by play into 208 home runs

The stages that hit a network cache every response to disk, so re-running never touches the original source again. 
Computation and writing are separate files, so diagnostics can be run without writing to the database.

### Roadblocks
**The source is hand-entered.** 4,241 posts produced 135 distinct field combinations.
* Fields appear and disappear with how much the owner has backfilled, so a missing batting line can mean "not yet 
entered," not "didn't play")
* The bobble-type field describes the roles represented, not the figures present. Honoree counts instead come from the 
title

**Matching names to players.** MLB's `lookup_player()` matches substrings across every field (A dog named Cash would 
match Andrew Cashner), so each season's player list is fetched once and matched locally instead.
* Normalizes Unicode accents, curly apostrophes, and initials (A.J. == AJ)
* Keeps suffixes for comparison: stripping them would match Eric Young Sr. to his son
* Scopes to the giveaway's season, so retired alumni don't match falsely
* Remaps nicknames and legal name changes (Kiké Hernandez == Enrique Hernandez)

**The obvious key doesn't work.** 
Player + date collided 135 times due to bobblehead variants, and a night where three 
giveaways honored the same player. Deduping would have dropped real giveaways, so giveaways are stored and player nights 
are derived. A check constraint also makes it impossible to insert a matched row with no player id.

**Edge cases as branches, not failures.** 
* Postponed games marked Final in the schedule and share a `gamePk` with their makeup
* 27 doubleheaders, where a homer only counts in the game the bobbles were handed out at
* 79 non-game giveaways (season-ticket holder, mail-in distribution, etc.)
* Every 2020 canceled giveaway
* 17 players honored while on another roster, 3 homers

### Status
Pipeline complete, zero hand edits needed as the database rebuilds from raw files. Remaining: 
**A teams table.** Team ids are currently stored as bare StatsAPI integers
**A frontend.** Browse the 208, plus a ticker for upcoming bobblehead nights

### Data Sources
Giveaway records compiled from BullpenBobbles.com. Baseball data from the MLB Stats API.