import collections
import glob
import json
import os
import re
from html import unescape

TAG_RE = re.compile(r"<[^>]+>")
FIELD_RE = re.compile(r"<strong>(.*?):</strong>(.*?)(?=<br|</p>|</div>|<strong>|$)",re.M,)




DIRECTORY = "raw/09-15-26"
LABEL_RE = re.compile(r"<strong>(.*?):</strong>")
HIDDEN_SPAN_RE = re.compile(r'<span style="visibility: hidden;">.*?</span>')


def fieldsIn(post):
    """Extract (label, value) pairs, tags stripped and entities unescaped."""
    html = HIDDEN_SPAN_RE.sub("", post["content"]["rendered"])
    return [(m.group(1), unescape(TAG_RE.sub("", m.group(2))).strip())
            for m in FIELD_RE.finditer(html)]



def loadPosts(directory=DIRECTORY):
    """
    read all saved pages and return the posts inside them
    :param directory: folder w/ raw page files
    :return: (list) list of post dicts
    :raises json.JSONDecodeError: if a file is truncated/not in correct shape
    """
    paths = sorted(glob.glob(os.path.join(directory, "*.json")))
    posts = []
    for path in paths:
        with open(path) as f:
            posts.extend(json.load(f))
    print(f"{len(paths)} files, {len(posts)} posts")
    return posts

def labelsIn(post):
    """
    extract the field labels present in a post
    :param post: a post dict with a 'content.rendered' string
    :return: (list) label strings eg ("league", "team", "date", "ab", "r")
    """
    html = post["content"]["rendered"]
    cleaned = HIDDEN_SPAN_RE.sub("", html)
    return LABEL_RE.findall(cleaned)


def shape(posts):
    """
    count label usage by occurance, post counts, and shape
    :param posts: post dictionaries to scan
    :return: (tuple) of occurences, postsContaining, shapes as three counters
    """
    occurrences = collections.Counter()
    postsContaining = collections.Counter()
    shapes = collections.Counter()
    for post in posts:
        labels = labelsIn(post)
        occurrences.update(labels)
        postsContaining.update(set(labels))
        shapes[tuple(sorted(set(labels)))] += 1
    return occurrences, postsContaining, shapes

if __name__ == "__main__":
    posts = loadPosts()
    occurrences, postsContaining, shapes = shape(posts)

    print(f"\n{len(occurrences)} distinct labels\n")
    for label, count in occurrences.most_common():
        print(f"  {label:<14} {count:>5} occurrences  {postsContaining[label]:>5} posts")

    for label, count in sorted(occurrences.most_common()):
        print(f'"{label}",')

    print(f"\n{len(shapes)} distinct shapes, top 20:\n")
    for signature, count in shapes.most_common(20):
        print(f"  {count:>5}  {', '.join(signature)}")

    # H and R appear in both batter and pitcher blocks
    BATTING = {"AB", "RBI", "Walk", "SO"}
    PITCHING = {"IP", "ER", "K", "PC", "ST"}

    # two-way/ pitchers pre universal dh
    for post in posts:
        labels = set(labelsIn(post))
        if labels & BATTING and labels & PITCHING:
            print(post["id"], post["title"]["rendered"], post["date"][:10])

    # anamalous giveaways: covid, manager, ticketholder giveaway during offszn, cancellation given away 2 yrs later
    missing = [p for p in posts if "Park" not in labelsIn(p)]
    print(f"{len(missing)} posts missing Park\n")
    for p in missing:
        print(f"  {p['id']}  {p['date'][:10]}  {p['title']['rendered']}")
        print(f"     {p['link']}")

    # mostly licensed prop info (marvel, star wars, etc.)
    tagged = [p for p in posts if p.get("tags")]
    print(f"{len(tagged)} of {len(posts)} ({len(tagged) / len(posts):.1%}) have tags")



# explored some questions possibly useful in future
# what values does a given label take?
    # for target in ("Theme", "Themes", "Bobble Type"):
    #     values = collections.Counter(v for p in posts for (l, v) in fieldsIn(p) if l == target)
    #     print(f"\n{target}: {sum(values.values())} posts, {len(values)} distinct values")
    #     for value, count in values.most_common():
    #         print(f"  {count:>5}  {value}")

# has a team ever honored a player on the opposing roster?
    # for post in posts:
    #     for label, value in fieldsIn(post):
    #         if label == "Bobble Type" and ("Opponent" in value or "Opposing" in value):
    #             print(f"{post['date'][:10]}  {value:<28}  {post['title']['rendered']}")
    #             print(f"    {post['link']}")

# do the compund bobble types mean multiple ppl or roles?
    # for post in posts:
    #     for label, value in fieldsIn(post):
    #         if label == "Bobble Type" and (" & " in value or " and " in value):
    #             print(f"{value:<34}  {post['title']['rendered']}")