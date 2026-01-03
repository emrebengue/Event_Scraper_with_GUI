import time
import traceback
from collections import defaultdict
from bs4 import BeautifulSoup, Comment
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def init_driver():
    """Initialize and return a headless Chrome driver."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-cache")
    options.add_argument("--disk-cache-size=0")
    options.add_argument("--disable-application-cache")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/58.0.3029.110 Safari/537.3"
    )
    driver = webdriver.Chrome(options=options)
    return driver


def remove_layout_noise(container):
    if container is None:
        return None

    # Tags that often carry layout noise
    layout_keywords = [
        "header",
        "footer",
        "nav",
        "menu",
        "sidebar",
        "breadcrumb",
        "search",
        "sponsor",
        "login",
        "social",
        "advert",
        "banner",
    ]

    for tag in container.find_all(True):
        if not hasattr(tag, "get") or not hasattr(tag, "decompose"):
            continue

        class_attr = tag.get("class") or []
        id_attr = tag.get("id") or ""

        class_list = [cls for cls in class_attr if isinstance(cls, str)]
        id_str = id_attr if isinstance(id_attr, str) else ""
        attrs_text = " ".join(class_list + [id_str]).lower()

        # remove if the tag is one of the layout types and contains layout-related keywords
        if tag.name in ["div", "section", "aside", "ul", "table"]:
            if any(kw in attrs_text for kw in layout_keywords):
                tag.decompose()
                continue

        # additional rule: strip empty menus/lists
        if tag.name in ["ul", "ol"] and not tag.get_text(strip=True):
            tag.decompose()
            continue

    return container


def remove_duplicate_lines(text):
    seen = set()
    result = []
    for line in text.splitlines():
        if line.strip() and line not in seen:
            result.append(line)
            seen.add(line)
    return "\n".join(result)


def scrape_page(url):
    """
    Unified scraper that uses Selenium for any URL, whether it's 'static' or 'dynamic'.
    Takes a screenshot, extracts the HTML, and returns either the event sections
    or the date/location sections.
    """
    driver = None
    try:
        driver = init_driver()
        driver.get(url)
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Scroll to the bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(10)
        text = driver.page_source

        print("Fetched HTML length:", len(text))

        html_body = extract_event_sections(text)
        # print("Extracted event HTML length:", len(html_body) if html_body else "None")

        return html_body

    except Exception as e:
        print(f"Error scraping {url}: {e}")
        traceback.print_exc()
        return None

    finally:
        if driver:
            driver.quit()


def extract_event_sections(html_text):
    """
    Extracts the HTML block most likely to contain a list of events using keyword-based scoring.
    """

    EVENT_KEYWORDS = [
        "college fair",
        "event",
        "exhibit",
        "schedule",
        "date",
        "location",
        "venue",
        "host",
        "register",
        "attend",
        "time",
        "high school",
        "university",
        "campus",
        "representative",
        "exhibitor",
        "student",
        "counselor",
        "details",
        "city",
        "state",
        "participating",
        "school",
    ]

    soup = BeautifulSoup(html_text, "html.parser")

    # Clean up common non-content tags
    for tag in soup(
        ["script", "style", "img", "link", "footer", "header", "nav", "svg", "form"]
    ):
        tag.decompose()

    elements = soup.find_all(["div", "section", "article", "li", "tr", "tbody", "p"])

    candidates = []
    for element in elements:
        element_text = element.get_text(separator=" ", strip=True).lower()
        score = sum(element_text.count(k.lower()) for k in EVENT_KEYWORDS)

        if score > 0:
            candidates.append((element, score))

    if not candidates:
        return "No keyword matches found in the page."

    # Aggregate scores at higher-level containers
    container_scores = defaultdict(int)
    for element, score in candidates:
        parents = element.find_parents(
            ["section", "article", "div", "tbody", "ul"], limit=2
        )
        for parent in parents:
            container_scores[parent] += score

    if not container_scores:
        return "No high-score containers found."

    # Get the best-scoring block
    best_container = max(container_scores.items(), key=lambda x: x[1])[0]
    # print(f"best_container", best_container)
    # print("---------------------------------------------------")
    # Optional: refine to the smallest section that still holds meaningful content
    refined_candidates = []
    for child in best_container.find_all(
        ["div", "p", "li", "tr", "td"], recursive=True
    ):
        text = child.get_text(separator=" ", strip=True).lower()
        score = sum(text.count(k.lower()) for k in EVENT_KEYWORDS)
        if score > 2:
            refined_candidates.append((child, score))

    if refined_candidates:
        best_final = max(refined_candidates, key=lambda x: x[1])[0]
        best_container = best_final

    # Final cleanup
    for tag in best_container.find_all(
        ["button", "script", "style", "img", "svg", "form", "footer", "header", "nav"]
    ):
        tag.decompose()

    print(
        f"Scored {len(candidates)} potential blocks. Top score: {max(score for _, score in candidates)}"
    )

    return str(best_container.prettify())


def clean_extracted_html(html):
    """
    Given an HTML string, further reduce noise by:
      • Removing HTML comments.
      • Removing empty tags (tags with no non-whitespace text)
        except for certain allowed ones.
      • Optionally removing empty <a> tags (unless they contain an image).
      • Collapsing multiple whitespace characters.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. Remove HTML comments (e.g. instructions or inline notes)
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 2. Remove empty tags.
    # Iterate over all tags and decompose ones that are "empty"
    for tag in soup.find_all():
        # tag.attrs is a dictionary; if it's empty, the tag has no attributes.
        # tag.get_text(strip=True) returns the tag's text with whitespace removed.
        if not tag.attrs and not tag.get_text(strip=True):
            tag.decompose()

    # 4. Normalize whitespace in the final HTML output.
    cleaned_html = soup.prettify()
    # Collapse multiple whitespace characters to a single space.

    # MIGHT NEED THIS LINE LATER
    # cleaned_html = re.sub(r"\s+", " ", cleaned_html)

    # 331432 -> 39066
    soup = BeautifulSoup(cleaned_html.strip(), "html.parser")
    plain_text = soup.get_text(separator="\n", strip=True)
    return plain_text


def html_extractor(link):
    scraped = scrape_page(link)

    if not scraped or "No keyword matches" in scraped:
        print("No events section found.")
        return

    cleaned_events = clean_extracted_html(scraped)
    cleaned_events = remove_duplicate_lines(cleaned_events)

    return cleaned_events
