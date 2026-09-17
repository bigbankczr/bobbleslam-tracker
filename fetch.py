import os
import time
import requests

BASE = "https://bullpenbobbles.com/wp-json/wp/v2"
HEADERS = {"User-Agent": "bobble-research/1.0"}
TIMEOUT = 30
DIRECTORY = "raw/09-15-26"
PERPAGE = 100

def getCategoryID(slug="mlb"):
    """look up wordpress category id by slug. prints category name and post count

    :param slug: category slug to search for. defaults to "mlb"
    :return: (int) category's wordpress id
    :raises requests.HTTPError: if requests fails returning a 4/500 error
             LookupError: if no category matches the slug
    """
    params = {"slug": slug}
    response = requests.get(f"{BASE}/categories", params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    categories = response.json()
    if not categories:
        raise LookupError(f"no wp category with slug {slug!r}")
    category = categories[0]
    print(f"category {category['slug']!r} (id {category['id']}): {category['count']} bobbleheads")
    return category["id"]

def getTotalPages(categoryID):
    """
    gets the number of pages in a category.
    :param categoryID: wordpress category id
    :return: (int) number of pages w/ perPage posts each
    """
    params = {"categories": categoryID,
              "per_page": PERPAGE,
              "_fields": "id"}
    response = requests.get(f"{BASE}/posts", params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    totalPosts = int(response.headers["X-WP-Total"])
    totalPages = int(response.headers["X-WP-TotalPages"])
    print(f"{totalPosts} posts across {totalPages} pages at {PERPAGE} per page")
    return totalPages

def fetchAll(categoryID, totalPages):
    """
    download every page of posts in a category, saves body of each. pages already present get skipped,
    :param categoryID: wordpress category id to fetch
    :param totalPages: number of pages to request
    :return:
    :raises requests.HTTPError: if requests fails returning a 4/500 error
    """
    os.makedirs(DIRECTORY, exist_ok=True)
    for page in range(1, totalPages + 1):
        filename = f"mlb_page{page:03d}.json"
        path = os.path.join(DIRECTORY, filename)
        if os.path.exists(path) and page != totalPages:
            # may need to change at some point, doesn't detect modifications to posts not added to the end
            continue

        params = {"categories" : categoryID,
                  "per_page" : PERPAGE,
                  "page" : page,
                  "orderby" : "date",
                  "order" : "asc",
                  "_fields" : "id,date,modified,slug,link,title,content,categories,tags"
                  }
        response = requests.get(f"{BASE}/posts", params=params, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()

        with open(path, "w") as f:
            f.write(response.text)
        print(f"saved {filename}")
        time.sleep(1)

if __name__ == "__main__":
    catID = getCategoryID()
    pages = getTotalPages(catID)
    fetchAll(catID, pages)
