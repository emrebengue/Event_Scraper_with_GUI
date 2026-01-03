# =====================================================================IMPORT&LIBRARY=====================================================================
import os
import re
import time
import json

# import tiktoken
import pandas as pd
import validators

from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Comment
from collections import defaultdict
from dotenv import load_dotenv

from openai import OpenAI

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()


# from Event_Json_Processor import EventJSONProcessor

# json_processor = EventJSONProcessor()

from LLM_openai import LLMModels

# =====================================================================API&LLM=====================================================================

# ADD YOUR OPENAI API KEY!!
# [0]Openai Paid
#api_key_list = [x.strip() for x in os.getenv("API_LIST").split(",")]
api_key_openai = os.getenv("API")

client_openai = OpenAI(api_key=api_key_openai)

llm_models = LLMModels(client_openai=client_openai)


# =====================================================================SCRAPING=====================================================================
def get_website_text(url):
    try:
        # Configure ChromeOptions to add a custom User-Agent
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
        driver.get(url)

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//*"))
        )
        WebDriverWait(driver, 5).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(3)

        text = driver.page_source
        return text

    except Exception as e:
        print(f"Error scraping dynamic website: {e}")
        return ""


def clean_extracted_html(html):
    """
    Given an HTML string, further reduce noise by:
      • Removing HTML comments.
      • Removing empty tags (tags with no non-whitespace text)
        except for certain allowed ones.
      • Optionally removing empty <a> tags (unless they contain an image).
      • Collapsing multiple whitespace characters.
    """
    # Handle None or non-string input
    if html is None or not isinstance(html, str):
        return ""

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
    cleaned_html = re.sub(r"\s+", " ", cleaned_html)
    # 331432 -> 39066
    soup = BeautifulSoup(cleaned_html.strip(), "html.parser")
    plain_text = soup.get_text(separator="\n", strip=True)
    return plain_text


def extract_event_sections(html_text):
    """
    Given raw HTML text, this function parses and cleans the HTML,
    then uses a weighted scoring system to identify which container
    most likely holds event information. We boost candidates that contain
    both date and time information.
    """
    # Handle None input
    if html_text is None:
        return "No event section found"

    # 1. Parse and clean HTML
    soup = BeautifulSoup(html_text, "html.parser")
    # Remove irrelevant tags
    for tag in soup(["script", "style", "img", "link", "footer", "header", "nav"]):
        tag.decompose()

    # 2. Keyword configuration – notice that we add a regex for time formats.
    event_keywords = {
        "terms": r"\b(calendar|schedule|event|fair|seminar|webinar|workshop|session|day|college|hub|club|group|meeting|high school|career|prep|hs|conference|expo|symposium)\b",
        "class_ids": r"calendar|schedule|events?|program",
        # Date formats: matches common numeric dates and month name dates.
        "date_formats": r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2})\b",
        # Time formats: e.g., 1:00 PM, 09:30 am, etc.
        "time_formats": r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b",
        "schema_org": r"schema\.org/Event",
    }

    # 3. First, check for schema.org markup – if present, return the container.
    schema_events = soup.find_all(attrs={"itemtype": "http://schema.org/Event"})
    if schema_events:
        return "\n".join([str(e.parent.parent) for e in schema_events])

    # 4. Otherwise, build a candidate list from common container elements.
    candidates = []
    elements = soup.find_all(["div", "section", "article", "li", "tr", "tbody"])
    for element in elements:
        score = 0
        # Get all text with some whitespace separation
        element_text = element.get_text(separator=" ", strip=True).lower()
        attributes = " ".join([str(element.attrs)]).lower()

        # Schema.org detection
        if re.search(event_keywords["schema_org"], attributes):
            score += 4

        # Keyword matching in element text
        if re.search(event_keywords["terms"], element_text, flags=re.IGNORECASE):
            score += 1

        # Keyword matching in class/id attributes
        class_list = element.get("class", [])
        element_class = " ".join(class_list) if class_list else ""
        element_id = element.get("id", "")
        class_id = f"{element_class} {element_id}".strip()
        if re.search(event_keywords["class_ids"], class_id, re.IGNORECASE):
            score += 2

        # Date and Time detection – boost if both are present.
        date_found = re.search(event_keywords["date_formats"], element_text)
        time_found = re.search(event_keywords["time_formats"], element_text)
        if date_found and time_found:
            score += 8  # Strong indicator when both are found
        elif date_found:
            score += 2
        elif time_found:
            score += 1

        # Structural scoring: slight boosts for list/table items.
        if element.name in ["li", "tr"]:
            score += 1
        if element.find_parent(["ul", "ol", "table"]):
            score += 1

        if score > 0:
            candidates.append((element, score))

    # 5. Aggregate scores up the DOM tree so that a parent that contains many candidates gets a boost.
    container_scores = defaultdict(int)
    for element, score in candidates:
        # Look upward to parents (limit to three levels) and sum their scores.
        parents = element.find_parents(["div", "section", "article"], limit=3)
        for parent in parents:
            container_scores[parent] += score

    if not container_scores:
        return "No event section found"

    # 6. Choose the container with the highest score.
    best_container = max(container_scores.items(), key=lambda x: x[1])[0]
    return str(best_container.prettify())


# =====================================================================CLEANING=====================================================================
# def get_token_count(text):
#     try:
#         enc = tiktoken.get_encoding("cl100k_base")
#         token_count = len(enc.encode(text))
#         print("*******TOKEN COUNT*******\n", token_count)
#         return int(token_count)
#     except Exception as e:
#         print("ERROR occured get_token_count")
#         return []


def transform_to_plain_text_and_clean(raw_text, base_url=None, flag=None):
    try:
        # get_event_sections_text = extract_event_sections(raw_text)
        if flag == None:  # That means we are feeding the main page
            get_event_sections_text = extract_event_sections(raw_text)
            event_links = extract_event_links(
                get_event_sections_text, base_url=base_url
            )

        else:
            get_event_sections_text = extract_date_location_sections(raw_text)
            event_links = ""

        # print("*" * 27 + "EXTRACTED EVENT SECTIONS HTML:","*" * 27 +"\n", get_event_sections_text,"\n")

        cleaned_html = clean_extracted_html(get_event_sections_text)
        print(
            "*" * 27 + "CLEAN EVENT SECTIONS HTML:", "*" * 27 + "\n", cleaned_html, "\n"
        )
        return cleaned_html, event_links

    except Exception as e:
        print("ERROR occured while transforming to text&clean", e)
        return None, []


# =====================================================================LINKS=====================================================================
def extract_date_location_sections(html_text):
    """
    Extracts sections of HTML containing date, time, and location information,
    then moves up two parent levels to return the relevant event section.
    """
    try:
        # Handle None input
        if html_text is None:
            return "No date or location information found"

        # Parse HTML
        soup = BeautifulSoup(html_text, "html.parser")

        # Remove unnecessary tags
        for tag in soup(["script", "style", "img", "link", "footer", "header", "nav"]):
            tag.decompose()

        # Regular expressions for identifying date, time, and location patterns
        patterns = {
            "date": r"\b((?:Mon|Tues|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat|Sun)(?:day)?,?\s*)?"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
            r"Dec(?:ember)?)(?:\.|,)?\s+\d{1,2}(?:st|nd|rd|th)?\,?\s*(?:\d{4})?"
            r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            "time": r"\b\d{1,2}:\d{2}\s*(?:[AaPp]\.?[Mm]\.?)?\s*(?:-|to)\s*\d{1,2}:\d{2}"
            r"\s*(?:[AaPp]\.?[Mm]\.?)?\b|\b\d{1,2}:\d{2}\s*(?:[AaPp]\.?[Mm]\.?)?\b",
            "location": r"\b([A-Z][a-z]+(?:[ -][A-Z][a-z]+)*,\s*(?:[A-Z]{2}|(?:Alabama|Alaska|Arizona|"
            r"Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|"
            r"Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|"
            r"Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|"
            r"New\sHampshire|New\sJersey|New\sMexico|New\sYork|North\sCarolina|North\sDakota|"
            r"Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\sIsland|South\sCarolina|South\sDakota|"
            r"Tennessee|Texas|Utah|Vermont|Virginia|Washington|West\sVirginia|Wisconsin|Wyoming))"
            r"|(?:High\s+School|University|College|Campus|Institute))\b",
        }
        # Search for elements that contain date, time, or location
        candidates = []
        elements = soup.find_all(
            ["div", "section", "article", "li", "tr", "tbody", "p"]
        )

        for element in elements:
            score = 0
            element_text = element.get_text(separator=" ", strip=True).lower()

            # Check for date, time, and location keywords
            date_found = re.search(patterns["date"], element_text, flags=re.IGNORECASE)
            time_found = re.search(patterns["time"], element_text, flags=re.IGNORECASE)
            location_found = re.search(
                patterns["location"], element_text, flags=re.IGNORECASE
            )

            if date_found:
                score += 3
            if time_found:
                score += 2
            if location_found:
                score += 3

            # Boost score if multiple factors are found
            if date_found and location_found:
                score += 4
            if date_found and time_found:
                score += 3
            if date_found and time_found and location_found:
                score += 6  # Strong indication of event info

            if score > 0:
                candidates.append((element, score))

        if not candidates:
            return "No date or location information found"

        # Aggregate scores for parents
        container_scores = defaultdict(int)
        for element, score in candidates:
            parents = element.find_parents(
                ["section", "article", "tbody", "tr"], limit=2
            )
            for parent in parents:
                container_scores[parent] += score

        if not container_scores:
            return "No relevant container found"

        # Choose the best container
        best_container = max(container_scores.items(), key=lambda x: x[1])[0]

        # return str(best_container.prettify())

        # NARROW DOWN FROM HERE

        refined_candidates = []
        for child in best_container.find_all(
            ["p", "span", "strong", "li", "div"], recursive=True
        ):
            child_text = child.get_text(separator=" ", strip=True).lower()
            if (
                re.search(patterns["date"], child_text, flags=re.IGNORECASE)
                or re.search(patterns["time"], child_text, flags=re.IGNORECASE)
                or re.search(patterns["location"], child_text, flags=re.IGNORECASE)
            ):
                refined_candidates.append(child)

        # Select the smallest tag that contains all required info
        best_final_container = None
        for candidate in refined_candidates:
            candidate_text = candidate.get_text(separator=" ", strip=True).lower()
            if (
                re.search(patterns["date"], candidate_text, flags=re.IGNORECASE)
                and re.search(patterns["time"], candidate_text, flags=re.IGNORECASE)
                and re.search(patterns["location"], candidate_text, flags=re.IGNORECASE)
            ):
                best_final_container = candidate
                break  # Stop once we find the best match

        if best_final_container:
            best_container = best_final_container

        if best_container.parent and best_container.parent.name is not ["html", "body"]:
            best_container = best_container.parent

        # for _ in range(2):
        #     if best_container.parent and best_container.parent.name is not ['html', 'body']:
        #         best_container = best_container.parent

        # Remove irrelevant nested elements
        for tag in best_container(
            [
                "button",
                "script",
                "style",
                "img",
                "svg",
                "form",
                "footer",
                "header",
                "nav",
            ]
        ):
            tag.decompose()

        return str(best_container.prettify())
    except Exception as e:
        print("ERROR occured while processing extract_date_location_sections", e)


def extract_event_links(
    html_text: str,
    base_url: str,
    required_href_keywords: list = None,
    ignored_link_text: list = None,
) -> list:
    # Default heuristics (tune these as needed)
    if required_href_keywords is None:
        required_href_keywords = ["view", "detail", "fair", "event"]

    if ignored_link_text is None:
        ignored_link_text = [
            "register",
            "donate",
            "login",
            "signup",
            "export",
            "search",
            "view all",
        ]

    soup = BeautifulSoup(html_text, "html.parser")
    anchors = soup.find_all("a", href=True)
    candidate_links = []

    for a in anchors:
        href = a.get("href").strip()
        text = a.get_text(separator=" ", strip=True).lower()

        # Skip non-navigational links.
        if not href or href.startswith(("mailto:", "javascript:")):
            continue

        # Exclude if the visible text exactly matches or contains any ignored keyword.
        if any(ignored == text or ignored in text for ignored in ignored_link_text):
            continue

        # Require that the href contains at least one expected event-detail keyword.
        if required_href_keywords:
            if not any(keyword in href.lower() for keyword in required_href_keywords):
                continue

        # Ensure absolute URL by joining with base_url if needed
        absolute_href = urljoin(base_url, href)

        # A basic heuristic: if the text is very short (e.g., a single word like "info"), skip it.
        if len(text) < 3:
            continue

        candidate_links.append(absolute_href)

    # Remove duplicates while preserving order.
    unique_links = list(dict.fromkeys(candidate_links))
    return unique_links


def loop_event_links(full_url, event_links_json, initial_list):
    event_links_json = event_links_json.replace("`", "")
    event_links_json = event_links_json.replace("json", "")
    event_links_json = event_links_json.strip()
    if not isinstance(event_links_json, list):
        try:
            indices_to_remove = json.loads(event_links_json)
        except json.JSONDecodeError:
            raise ValueError("event_links_json is not valid JSON for a list.")
    else:
        indices_to_remove = event_links_json
    if len(indices_to_remove) != 0:
        # Remove elements from initial_list at the indices provided, sorted in reverse order to avoid shifting issues.
        for index in sorted(indices_to_remove, reverse=True):
            if 0 <= index < len(initial_list):
                initial_list.pop(index)

    parsed = urlparse(full_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    print("BASE URL:", base_url)

    results = {}
    print("cleaned list:", initial_list)
    # Loop through a subset (first 2) of the modified initial_list
    for path_link in initial_list:
        if path_link.startswith("https:"):
            full_path = path_link
        else:
            full_path = base_url + path_link
        print("FULL PATH:", full_path)

        raw_text = get_website_text(full_path)
        # print("RAW TEXT IN PATH LINK:", raw_text)

        plain_text, _ = transform_to_plain_text_and_clean(raw_text, flag=1)
        results[path_link] = plain_text

    return json.dumps(results)


# =====================================================================MAIN=====================================================================


def main(input_data):
    result = {}

    if validators.url(input_data):  # Treat input as a URL
        raw_text = get_website_text(input_data)

        if raw_text:
            try:
                print("Scraped raw_text text successfully!")
                plain_text, event_links = transform_to_plain_text_and_clean(
                    raw_text, base_url=input_data
                )

                # Check if plain_text is None (extraction failed)
                if plain_text is None:
                    print("Failed to extract plain text from raw_text")
                    return {"error": "Failed to extract event data from the webpage"}

                print("STEP 1")
                print("EVENT LINKS:", "LEN:", len(event_links), "\n", event_links)

                if len(event_links) != 0:
                    extracted_links = llm_models.llm_openai_get_event_links(event_links)

                    # Check if LLM call failed
                    if extracted_links is None:
                        print("Failed to get event links from LLM (connection error or API failure)")
                        return {"error": "Failed to process event links with LLM"}

                    print(
                        "EXTRACTED EVENT LINKS:",
                        "LEN:",
                        len(extracted_links),
                        "\n",
                        extracted_links,
                    )

                    get_event_dictionary = loop_event_links(
                        input_data, extracted_links, event_links
                    )
                    links_result = llm_models.llm_openai_dictionary(
                        get_event_dictionary
                    )

                    # Check if LLM call failed
                    if links_result is None:
                        links_result = '{"events": []}'
                    else:
                        links_result = (
                            links_result.replace("`", "").replace("json", "").strip()
                        )

                    time.sleep(2)

                    plain_text_result = llm_models.llm_openai_plain_text(plain_text)

                    # Check if LLM call failed
                    if plain_text_result is None:
                        plain_text_result = '{"events": []}'
                    else:
                        plain_text_result = (
                            plain_text_result.replace("`", "").replace("json", "").strip()
                        )

                    try:
                        links_json = json.loads(links_result)
                        print(
                            f"Number of events in links result: {len(links_json.get('events', []))}"
                        )
                    except:
                        pass

                    try:
                        plain_json = json.loads(plain_text_result)
                        print(
                            f"Number of events in plain text result: {len(plain_json.get('events', []))}"
                        )
                    except:
                        pass

                    final_merged_result = llm_models.llm_openai_merger(
                        links_result, plain_text_result
                    )
                    print(
                        f"final_merged_result:{final_merged_result}\n**************************"
                    )

                    return final_merged_result
                else:
                    print("========PLAIN TEXT========\n", plain_text)
                    result = llm_models.llm_openai_plain_text(plain_text)

                    # Check if LLM call failed
                    if result is None:
                        print("Failed to process plain text with LLM (connection error or API failure)")
                        return {"error": "Failed to process event data with LLM"}

                    result = result.replace("`", "").replace("json", "").strip()
                    print(result)
                    return result

            except Exception as e:
                print("ERROR occurred while processing raw_text", e)
                return {"error": str(e)}
        else:
            print("No text could be scraped or an error occurred.")
            return {"error": "No text could be scraped or an error occurred."}

    else:  # Treat input as raw text (PDF or plain)
        print("Detected plain text input (likely PDF). Sending to PDF-tailored LLM...")
        try:
            result = llm_models.llm_openai_from_textract_pdf(input_data)

            # Check if LLM call failed
            if result is None:
                print("Failed to process PDF with LLM (connection error or API failure)")
                return {"error": "Failed to process PDF data with LLM"}

            result = result.replace("`", "").replace("json", "").strip()
            print("PDF LLM Result:\n", result)

            # Try parsing into Python object
            parsed = json.loads(result)

            # Normalize format if it's a list of Event-style entries
            if isinstance(parsed, list):

                def normalize_event(e):
                    location = e.get("Event Location")
                    if not location or not isinstance(location, str):
                        city = None
                        state = None
                    elif "," in location:
                        city, state = [x.strip() for x in location.split(",", 1)]
                    else:
                        city = location.strip()
                        state = None

                    return {
                        "name": e.get("Event Name") or None,
                        "date": e.get("Event Date") or None,
                        "time": e.get("Event Time") or None,
                        "city": city,
                        "state": state,
                        "url": (
                            f"https://{e['Event URL'].strip()}"
                            if e.get("Event URL")
                            and not e["Event URL"].startswith(("http://", "https://"))
                            else e.get("Event URL")
                        )
                        or None,
                    }

                parsed = [
                    normalize_event(e) for e in parsed
                ]  # ✅ This is what the UI and DB logic expect
            return {"events": parsed}

        except Exception as e:
            print("Error in PDF LLM:", e)
            return {"error": str(e)}


# Comment out the direct execution code when imported as a module
if __name__ == "__main__":
    url_list = [
        "https://iacac.knack.com/college-fairs#season/",  # 0
        "https://members.sacac.org/event-calendar",  # 1
        "https://www.tacac.org/college-fair-events",
        "https://www.pacac.org/event-calendar",
        "https://www.nacacnet.org/get-involved/exhibit-at-a-nacac-college-fair/",
        "https://www.educationusacanada.ca/fair/",
        "https://www.educationusacanada.ca/u-s-educators/highered-fairs/",
        "https://www.cois.org/about-cis/events#6",
        "https://www.wefs.org/fair-schedule/",
    ]
    main(url_list[-2])
