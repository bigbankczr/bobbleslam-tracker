import re
from html import unescape
from collections import Counter
from itertools import groupby

from shapes import loadPosts, labelsIn, fieldsIn

BATTING = {"AB", "RBI", "Walk", "SO"}
PITCHING = {"IP", "ER", "K", "PC", "ST"}



ROLE_SPLIT_RE = re.compile(r"\s*(?:,\s*and\s+|"
                      r"\s+and\s+|"
                      r"&|"
                      r"/|"
                      r",)\s*")

NAME_SPLIT_RE = re.compile(r"\s*(?:,\s*and\s+|"
                           r"\s+and\s+|"
                           r"&|"
                           r",)\s*")

KNOWN_LABELS = frozenset({"League",
                          "AB",
                          "Attendance",
                          "BB",
                          "Bobble Type",
                          "Date",
                          "ER",
                          "H",
                          "HR",
                          "IP",
                          "K",
                          "Number",
                          "PC",
                          "Park",
                          "Position",
                          "Quantity",
                          "R",
                          "RBI",
                          "SO",
                          "ST",
                          "Sponsor",
                          "Team",
                          "Theme",
                          "Themes",
                          "Walk"})

SUFFIXES = frozenset({"Jr.", "Sr.", "Jr", "Sr", "II", "III", "IV"})
PROTECTED = ("Journalists and Broadcasters", "TV and Movies")
JUNK_TYPES = frozenset({"what a piece of junk", "that’s no moon"})
SYNONYMS = {"historic player": "historical player"}
IN_SCOPE = frozenset({"player", "alumni", "historical player", "special player", "historical alumni"})
KNOWN_TYPES = frozenset({"actor",
                         "alumni",
                         "announcer",
                         "basketball player",
                         "boxer",
                         "broadcaster",
                         "business owner",
                         "celebrity",
                         "character",
                         "coach",
                         "college",
                         "comedian",
                         "dog",
                         "event",
                         "father",
                         "figure skater",
                         "football player",
                         "founder",
                         "front office",
                         "garden gnome",
                         "general manager",
                         "generic",
                         "golfer",
                         "groundskeeper",
                         "heritage",
                         "historic player",
                         "historical alumni",
                         "historical event",
                         "historical figure",
                         "historical player",
                         "hockey player",
                         "holiday",
                         "league",
                         "manager",
                         "mascot",
                         "musician",
                         "nascar driver",
                         "opponent",
                         "opponent mascot",
                         "opposing alumni",
                         "owner",
                         "pet",
                         "player",
                         "president",
                         "rapper",
                         "record producer",
                         "senior advisor",
                         "singer",
                         "skateboarder",
                         "soccer player",
                         "special event",
                         "special mascot",
                         "special player",
                         "tennis player",
                         "vehicle",
                         "vendor",
                         "zoo animal",
                     })



def checkExtraction(posts):
    """
    makes sure labelsIn and fieldsIn are the same length, and checks each label against KNOWN_LABELS
    :param posts: list of post dicts from shapes.loadPosts
    :return: none
    :raises ValueError: names post id on failure
    """
    mismatches = []
    unknown = Counter()
    unknownExamples = {}

    for post in posts:
        labels = [label.strip() for label in labelsIn(post)]
        fieldLabels = [label.strip() for label, _ in fieldsIn(post)]
        if labels != fieldLabels:
            mismatches.append((post, labels, fieldLabels))
        for label in set(labels):
            if label not in KNOWN_LABELS:
                unknown[label] += 1
                unknownExamples.setdefault(label, post)

    if mismatches or unknown:
        CAP = 20
        lines = []
        if mismatches:
            lines.append(f"{len(mismatches):,} of {len(posts):,} posts mismatched:")
            for post, expected, actual in mismatches[:CAP]:
                lines.append(f"  {post['id']} {post['link']}")
                lines.append(f"     labelsIn ({len(expected)}): {expected}")
                lines.append(f"     fieldsIn ({len(actual)}): {actual}")
            if len(mismatches) > CAP:
                lines.append(f"  ({len(mismatches) - CAP} more...)")
        if unknown:
            lines.append(f"  ({len(unknown)} unknown labels):")
            for label, count in unknown.most_common():
                lines.append(f"  {label!r}: {count:,} posts, eg {unknownExamples[label]['link']}")
        raise ValueError("\n".join(lines))
    print(f"extraction OK: {len(posts):,} posts")

def parseTitle(title):
    """
    split a title.rendered string into honoree(s), team, and variant
    :param title: raw title.rendered string
    :return: (tuple) (names, team, variant)
    """
    title = unescape(title)
    variant = None
    match = re.findall(r"\(([^)]*)\)", title)
    if match:
        variant = " / ".join(part.strip() for part in match)
        title = re.sub(r"\s*\([^)]*\)", "", title).strip()
    if "," not in title:
        raise ValueError(f"no comma in title: {title!r}")

    names, team = title.rsplit(",", 1)
    team = team.strip()

    parts = NAME_SPLIT_RE.split(names)

    parts = [part.strip() for part in parts if part.strip()]


    merged = []
    for part in parts:
        if part in SUFFIXES and merged:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged, team, variant

def suspiciousNames(names):
    """
    return names that don't look like people. parts w/ fewer than 2 names or first letter lowercase likely a mascot or
    character
    :param names: name strings from parseTitle
    :return: (list) the parts that look wrong
    """
    flagged = []
    for name in names:
        pieces = name.split()
        if len(pieces) < 2 or any(piece[:1].islower() for piece in pieces[1:]):
            flagged.append(name)
    return flagged

def normalizeBobbleType(value):
    """
    takes raw bobble type string and reduces to a set of base names. splits on "&", "and", "/", and oxford commas, then
    lowercases and folds plurals and synonyms
    :param value: raw bobble type field or None
    :return: (frozenset)  role strings. empty if missing or junk.
    """
    if value is None:
        return frozenset()
    value = unescape(value).strip()
    if value.lower() in JUNK_TYPES:
        return frozenset()
    parts = ROLE_SPLIT_RE.split(value)
    roles = set()
    for part in parts:
        part = part.strip().lower()
        if not part:
            continue
        part = SYNONYMS.get(part, part)
        if part.endswith("s") and part[:-1] in KNOWN_TYPES:
            part = part[:-1]
        roles.add(part)
    return frozenset(roles)

def splitThemes(value):
    """
    split a themes value into individual theme names. separator is " and ".
    :param value: raw theme or themes field
    :return: (list) theme names in the order they appear.
    """
    for i, name in enumerate(PROTECTED):
        value = value.replace(name, f"\x00{i}\x00")
    parts = [part.strip() for part in value.split(" and ")]

    for i, name in enumerate(PROTECTED):
        parts = [part.replace(f"\x00{i}\x00", name) for part in parts]

    return [part for part in parts if part]




def parsePost(post):
    """
    extract everything useful from a raw post dict
    :param post: a post from shapes.loadPosts
    :return: (dict) flat fields, parsed title, normalized roles, theme list, and stat block(s) present.
    """
    fields = dict(fieldsIn(post))
    labels = set(labelsIn(post))

    names, team, variant = parseTitle(post["title"]["rendered"])
    roles = normalizeBobbleType(fields.get("Bobble Type"))

    raw = fields.get("Themes") or fields.get("Theme")
    themes = splitThemes(raw) if raw else []

    return {
        "id": post["id"],
        "date": post["date"][:10],
        "modified": post["modified"][:10],
        "link": post["link"],
        "names": names,
        "team": team,
        "teamField": fields.get("Team"),
        "league": fields.get("League"),
        "variant": variant,
        "roles": roles,
        "inScope": bool(roles & IN_SCOPE) or not roles,
        "bobbleType": fields.get("Bobble Type"),
        "themes": themes,
        "park": fields.get("Park"),
        "attendance": fields.get("Attendance"),
        "quantity": fields.get("Quantity"),
        "sponsor": fields.get("Sponsor"),
        "position": fields.get("Position"),
        "number": fields.get("Number"),
        "batting": bool(labels & BATTING),
        "pitching": bool(labels & PITCHING),
        "categories": post.get("categories"),
        "tags": post.get("tags"),
        "fields": fields,

    }

def parseAll(posts):
    """
    parse all posts and expand into one row per bobble
    :param posts:
    :return: (list) row dictionaries
    """
    rows = []
    for post in posts:
        parsed = parsePost(post)
        for name in parsed["names"]:
            row = dict(parsed)
            row["name"] = name
            row["honoreeCount"] = len(parsed["names"])
            rows.append(row)
    return rows

def keyCollisions(rows):
    """
    check for unique candidate keys across parsed rows. counts if sharing (name, date) and (id, name). prints collisions
    :param rows: row dicts from parseAll()
    :return: (tuple) counters holding keys occurring more than once
    """
    nameDate = Counter()
    idName = Counter()

    for row in rows:
        nameDate[(row["name"], row["date"])] += 1
        idName[(row["id"], row["name"])] += 1

    nameDate = Counter({key: count for key, count in nameDate.items() if count > 1})
    idName = Counter({key: count for key, count in idName.items() if count > 1})

    print(f"{len(nameDate):,} (name, date) keys on more than one row")
    print(f"{len(idName):,} (id, name) keys on more than one row")

    collided = sorted((row for row in rows if (row["name"], row["date"]) in nameDate), key=lambda row: (row["name"], row["date"]),)
    for key, group in groupby(collided, key=lambda row: (row["name"], row["date"])):
        name, date = key
        print(f"\n {name}  {date}")
        for row in group:
            print(f"      {row['id']}   {row['variant']!r}   {row['link']}")

    return nameDate, idName

if __name__ == "__main__":
    posts = loadPosts()

## titles
# failures

    # failures, multi, variants, odd = [], [], [], []
    # for post in posts:
    #     raw = post["title"]["rendered"]
    #     try:
    #         names, team, variant = parseTitle(raw)
    #     except ValueError as e:
    #         failures.append((post,e))
    #         continue
    #     if len(names) > 1:
    #         multi.append((post, names, team))
    #     if variant:
    #         variants.append((post, names, variant))
    #     flagged = suspiciousNames(names)
    #     if flagged:
    #         odd.append((post, names, flagged))



    # print(f"\n{len(failures)} titles w no team comma")
    # for post, e in failures:
    #     print(f"   {post['id']}  {post['title']['rendered']!r}")
    #     print(f"      {post['link']}")

# variants
    # print(f"\n{len(variants)} titles w a variant")
    # for post, names, variant in variants:
    #     print(f"   {variant:<12}  {names}")

# msacot names and other unknown formats
    # print(f"\n{len(odd)} titles w suspicious name pieces")
    # for post, names, flagged in odd:
    #     print(f"   {flagged} <- {names}")
    #     print(f"      {post['link']}")

# multi-bobble
    # print(f"\n{len(multi)} multi-name titles")
    # for post, names, team in multi:
    #     print(f"   {len(names)}  {names}  |  {team}")

## bobble type
# splits
    # parts = Counter()
    # for post in posts:
    #     for label, value in fieldsIn(post):
    #         if label == "Bobble Type":
    #             parts.update(
    #                 part.strip() for part in ROLE_SPLIT_RE.split(unescape(value).strip().lower())
    #                 if part.strip()
    #             )
    # for part, count in parts.most_common():
    #     print(f"  {count:>5}  {part!r}")


##themes
# theme vs themes
    # themes = Counter()
    # both = []
    # for post in posts:
    #     found = {l: v for l, v in fieldsIn(post) if l in ("Theme", "Themes")}
    #     if len(found) > 1:
    #         both.append(post)
    #     for label, value in found.items():
    #         themes[(label, value)] += 1
    #
    # print(f"{len(both)} posts carry both Theme and Themes")
    #
    # for label in ("Theme", "Themes"):
    #     vals = {v: c for (l, v), c in themes.items() if l == label}
    #     print(f"\n{label}: {sum(vals.values())} posts, {len(vals)} distinct values")
    #
    # print("\n--- every Themes value ---")
    # for (label, value), count in sorted(themes.items()):
    #     if label == "Themes":
    #         print(f"  {count:>3}  {value!r}")
    #
    # print("\n--- singular Theme values containing a separator ---")
    # for (label, value), count in sorted(themes.items()):
    #     if label == "Theme" and re.search(r"[,&/]| and ", value):
    #         print(f"  {count:>3}  {value!r}")
    ## splitter check
    # THEMES = set()
    # plural = []
    # for post in posts:
    #     for label, value in fieldsIn(post):
    #         if label == "Theme":
    #             THEMES.add(value)
    #         elif label == "Themes":
    #             plural.append((post, value))
    #
    # print(f"{len(THEMES)} singular theme names, {len(plural)} plural values\n")
    # for post, value in sorted(plural, key=lambda pair: pair[1]):
    #     print(f"  {value!r}")
    #     print(f"    -> {splitThemes(value)}")
    #
    # bad = []
    # for post, value in plural:
    #     for part in splitThemes(value):
    #         if part not in THEMES:
    #             bad.append((post, value, part))
    #
    # print(f"\n{len(bad)} parts not in the singular vocabulary")
    # for post, value, part in bad:
    #     print(f"  {part!r}  from  {value!r}")
    #     print(f"  {post['link']}")
## rows
    # rows = parseAll(posts)
    #
    # print(f"\n{len(posts):,} posts -> {len(rows):,} rows")
    #
    # inScope = sum(1 for r in rows if r["inScope"])
    # untyped = sum(1 for r in rows if not r["roles"])
    # print(f"{inScope:,} in scope, {untyped:,} untyped")
    #
    # counts = Counter(r["honoreeCount"] for r in rows)
    # print("\nhonorees per post:")
    # for n, count in sorted(counts.items()):
    #     print(f"  {n}  {count:>6,} rows")
    #
    # mismatched = [r for r in rows if r["team"] != r["teamField"]]
    # print(f"\n{len(mismatched):,} rows where parsed team != Team field")
    # for r in mismatched[:30]:
    #     print(f"  {r['team']!r}  vs  {r['teamField']!r}")
    #     print(f"     {r['link']}")

