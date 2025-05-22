from config import s3, textract, bucket_name, client_openai, region
from html_keyword_scrape import html_extractor

import json
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

import io
import os
import time
from datetime import datetime
import re
from urllib.parse import urlparse

# ------------------ KEYWORDS ---------------------
# possible_event_keywords = {
#'terms': r'\b(calendar|schedule|event|fair|seminar|webinar|workshop|session|day|college|hub|club|group|meeting|high school|career|prep|hs|conference|expo|symposium)\b',
#'class_ids': r'calendar|schedule|events?|program',
#'date_formats': r'\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2})\b',
#'time_formats': r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b',
#'schema_org': r'schema\.org/Event'
# }

ignore_keywords = r"\b(contact|benefits|login|terms|privacy|faq|resources|@)\b"
# -------------------------------------------------

# -----------  GLOBAL ------------
URL = None
todays_date = datetime.today().strftime("%Y-%m-%d")
base_dir = os.path.join(os.getcwd(), todays_date)
# ---------------------------------------------------


# ----------------- Code Starts Here -----------------


def setup_directory():
    upload = "UPLOAD"
    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(upload, exist_ok=True)

    return base_dir, upload


def init_driver():
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


def iframe_detector(driver):
    iframes_in_body = driver.find_elements(By.XPATH, "//body//iframe")
    return bool(iframes_in_body)


def save_screenshot(driver, path):
    if iframe_detector(driver):
        print("iframe detected")
        unclip_scrollbars(driver)
    time.sleep(1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    total_height = driver.execute_script("return document.body.scrollHeight")
    driver.set_window_size(1920, total_height)
    time.sleep(2)
    driver.save_screenshot(path)


def url_name_parser(url):
    if isinstance(url, bytes):
        url = url.decode("utf-8")

    parsed_url = urlparse(url)

    # Make sure netloc is also a string
    if isinstance(parsed_url.netloc, bytes):
        netloc = parsed_url.netloc.decode("utf-8")
    else:
        netloc = parsed_url.netloc

    domain_parts = netloc.split(".")
    event_name = (
        ".".join(domain_parts[-3:]) if len(domain_parts) > 2 else ".".join(domain_parts)
    )
    return event_name


def take_and_save_screenshot(url, save_dir):
    driver = None

    try:
        driver = init_driver()
        driver.get(url)
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Capture entire page
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)

        driver.implicitly_wait(10)

        domain = url_name_parser(url)
        # Timestamp for screenshot naming
        # place_holder = datetime.now().strftime("%H%M%S")
        print(f"this is domain: {domain}")
        screenshot_path = os.path.join(save_dir, f"{domain}.png")
        save_screenshot(driver, screenshot_path)

        return screenshot_path

    except Exception as e:
        print("cannot take a screenshot!")
        return None

    finally:
        if driver:
            driver.quit()


def take_a_screenshot(url):
    global base_dir
    global todays_date
    if not os.path.isdir(f"{base_dir}"):
        base_dir, _ = setup_directory(url)

    screenshot_path = take_and_save_screenshot(url, base_dir)

    return screenshot_path


def unclip_scrollbars(driver):
    """
    Remove overflow constraints for any div that has scrollable content.
    """
    script = """
    const elements = Array.from(document.querySelectorAll('*'))
    .filter(e => e.scrollHeight > e.clientHeight && getComputedStyle(e).overflowY !== 'visible');
    elements.forEach(el => {
      el.style.overflowY = 'visible';
      el.style.height = 'auto';
      el.style.maxHeight = 'none';
    });
    """
    driver.execute_script(script)


def llm_openai(obj):
    try:
        if (
            isinstance(obj, list)
            and len(obj) == 2
            and all(isinstance(data, str) for data in obj)
        ):
            textract_text, html_text = obj
            system_prompt = """
            *Role:*  
            You are a highly skilled Structured Event Data Extractor. Your task is to compare and extract the most accurate event details from **two sources** of textual data: one from OCR (Textract), and one from HTML scraping.

            *Objective:*  
            Extract key event details and output them **strictly in JSON format**.

            *Extract the following fields:*
            - *Event Name*
            - *Event Date:* Standardized to YYYY-MM-DD
            - *Event Time:* Start/End in 24-hour HH:MM format
            - *Event Location:* City and state/province
            - *Event URL:* If available

            *Instructions:*  
            - Prioritize HTML data **if** it’s more structured or complete.
            - Remove header/footer noise, and irrelevant text.
            - Standardize all formats.
            - **Return only JSON. No explanations.**
            - **If no event found, return `[]`.**
            """
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Source 1 - Textract Output:\n{textract_text}",
                },
                {
                    "role": "user",
                    "content": f"Source 2 - HTML Extracted Section:\n{html_text}",
                },
                {
                    "role": "user",
                    "content": "Extract and structure the most accurate event details from these two sources.",
                },
            ]

            response = client_openai.chat.completions.create(
                model="gpt-4o-mini", messages=messages
            )
            return response.choices[0].message.content
        else:
            system_prompt = """
                *Role:*  
                You are a highly skilled Structured Event Data Extractor. Your task is to extract event details from screenshots containing event schedules.

                *Objective:*  
                From each image, extract key event details and output them **strictly in JSON format**.

                *Extract the following fields:*
                - *Event Name:* The name of the event.
                - *Event Date:* Standardized to YYYY-MM-DD format.
                - *Event Time:* Start time in 24-hour HH:MM format (or null if unavailable).
                - *Event City:* The city where the event is held.
                - *Event State/Province:* The state or province of the event.
                - *Event URL:* If a URL is detected, extract it.

                *Instructions:*  
                - Accurately detect text from images.
                - Use text structure and patterns to infer missing fields where possible.
                - Standardize date and time formats.
                - Construct a valid JSON output.
                - **If no event information is found, return an empty JSON array `[]` (without any additional messages).**
                - **DO NOT include any explanations, comments, or additional text. Only return the JSON response.**
                """
            messages = [{"role": "system", "content": system_prompt}]

            images = []

            for i, img in enumerate(obj, start=1):
                b64 = encode_img_for_llm(img)
                images.append(f"Image {i} (base64): {b64}")

            image_str = "\n".join(images)
            messages.append({"role": "user", "content": image_str})
            messages.append(
                {
                    "role": "user",
                    "content": "Extract and structure the event details from these screenshots.",
                }
            )
            response = client_openai.chat.completions.create(
                model="gpt-4o-mini", messages=messages
            )
            return response.choices[0].message.content

    except Exception as e:
        print(f"Error extracting event details: {e}")
        return []


def extract_table_data(textract_data):
    # Store blocks in a dictionary where id is the key and the value is the entire block
    blocks = {block["Id"]: block for block in textract_data}
    # We work with Table format so we only append TABLE types to the array so we look for BlockType
    tables = [block for block in textract_data if block["BlockType"] == "TABLE"]

    if not tables:
        print("No tables detected in the document.")
        return []

    all_tables = []

    for table in tables:
        # cell_block = []
        # # Find child cell blocks, if there are no chill sell then returns empty array []
        # for relation in table.get('Relationships', []):
        #     for cell_id in relation['Ids']:
        #         if relation['Type'] == 'CHILD':
        #             if cell_id in blocks:
        #                 cell_block.append(blocks[cell_id])

        # This one is more efficient than the one above
        cell_blocks = [
            blocks[cell_id]
            for rel in table.get("Relationships", [])
            if rel["Type"] == "CHILD"
            for cell_id in rel["Ids"]
            if cell_id in blocks
        ]

        # Extract row and column data
        table_data = {}
        for cell in cell_blocks:
            if cell["BlockType"] == "CELL":
                # Ideally, AWS textract detect all the rows and columns but in case of failure, row and (or) column index value becomes 0.
                row = cell.get("RowIndex", 0)
                col = cell.get("ColumnIndex", 0)
                text = ""

                # Extract text from cell safely
                if "Relationships" in cell:
                    for rel in cell["Relationships"]:
                        if rel["Type"] == "CHILD":
                            # Efficient implementation
                            word_ids = [
                                blocks[word_id]["Text"]
                                for word_id in rel["Ids"]
                                if word_id in blocks and "Text" in blocks[word_id]
                            ]
                            text = " ".join(word_ids)

                if row not in table_data:
                    # creates a dictionary based on row if it does not exists already in table_data
                    table_data[row] = {}
                table_data[row][col] = text

        if not table_data:
            print("No structured data found in table.")
            continue

        # Convert extracted table data into Pandas DataFrame
        rows = max(table_data.keys(), default=0)
        cols = max(
            (max(row.keys(), default=0) for row in table_data.values()), default=0
        )

        if rows == 0 or cols == 0:
            print("Table is empty, No valid row or column")
            continue

        table_matrix = []
        for r in range(1, rows + 1):
            row_data = [table_data.get(r, {}).get(c, "") for c in range(1, cols + 1)]
            table_matrix.append(row_data)

        all_tables.append(pd.DataFrame(table_matrix))

    return all_tables


def extract_layout_data(blocks, top_cut=0.1, bottom_cut=0.8):
    lines = []
    for block in blocks:
        if block.get("BlockType") == "LINE":
            text = block.get("Text", "").strip()
            bbox = block["Geometry"]["BoundingBox"]
            top = bbox["Top"]
            height = bbox["Height"]

            # If the line is entirely above our cut (top < top_cut => skip)
            # Or if the line extends into the footer region (top+height > bottom_cut => skip)
            if top < top_cut or (top + height) > bottom_cut:
                continue

            # Otherwise we keep the line
            lines.append(text)
    filter = []

    for line in lines:
        # To reduce the input tokens, we try to minimize the lines as much as we can without deleting event related information
        if not re.search(
            r"\b(home|about|committee|membership|contact|login|join|members)\b",
            line,
            re.IGNORECASE,
        ):
            filter.append(line)

    return filter


def check_relevancy_of_the_table(df):
    text = " ".join(df.astype(str).values.flatten()).lower()

    # Check for event-related words, date formats, or time formats
    # contains_event_terms = any(re.search(pattern, text) for pattern in possible_event_keywords.values())
    contains_ignore_terms = re.search(ignore_keywords, text)

    # Returns True when there are NO ignore terms
    return contains_ignore_terms is None


def main(data):
    csv_filename = None
    final_csv = None
    global URL
    scraped_html = None
    save_dir, _ = setup_directory()
    try:
        s3.create_bucket(
            Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": region}
        )
        print(f"{bucket_name} created.")

    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"{bucket_name} already exists.")

    todays_date = datetime.today().strftime("%Y-%m-%d")
    # save_dir = os.path.join(os.getcwd(), todays_date)

    image_paths = []

    # this makes the data an array even if there is only one file uploaded
    if isinstance(data, str):
        data = [data]

    if data[0].startswith("http"):
        URL = data[0]
        image_paths.append(take_a_screenshot(URL))
        scraped_html = html_extractor(URL)
    else:
        if URL:
            parsed_url = url_name_parser(URL)

            for file in data:
                updated_path = os.path.join(
                    "UPLOAD", f"{parsed_url}_{os.path.basename(file)}"
                )

                if os.path.exists(file):
                    os.rename(file, updated_path)
                    image_paths.append(updated_path)
        else:
            for file in data:
                updated_path = os.path.join("UPLOAD", f"screenshot_{todays_date}")

                if os.path.exists(file):
                    os.rename(file, updated_path)
                    image_paths.append(updated_path)
        if not image_paths:
            print("There are no uploaded images...returning...")
            return

    s3_files = []
    for i, file in enumerate(image_paths):
        file_name = os.path.basename(file)
        if URL:
            s3_file_name = (
                f"{url_name_parser(URL)}_{file_name}.png"
                if len(image_paths) > 1
                else url_name_parser(URL) + ".png"
            )
        else:
            s3_file_name = (
                f"{file_name}_{i}.png" if len(image_paths) > 1 else file_name + ".png"
            )

        s3.upload_file(file, bucket_name, s3_file_name)

        print(f"{s3_file_name} is uploaded to {bucket_name}")
        s3_files.append(s3_file_name)

    if URL:
        csv_filename = os.path.join(save_dir, f"{url_name_parser(URL)}.csv")
    else:
        csv_filename = os.path.join(save_dir, f"{file_name}.csv")
    json_filename = os.path.join(save_dir, f"{s3_files[0]}.json")

    # If there is only one image then try to process it with Textract then OPENAI
    # If there is Multiple images then only use OPENAI for better processing
    if len(image_paths) == 1:
        table_response = textract.analyze_document(
            Document={"S3Object": {"Bucket": bucket_name, "Name": s3_files[0]}},
            FeatureTypes=["TABLES"],
        )
        # Saves it locally

        with open(json_filename, "w") as f:
            json.dump(table_response["Blocks"], f, indent=4)
        with open(json_filename, "r") as f:
            textract_data = json.load(f)
        os.remove(json_filename)
        # Process the JSON response
        tables = extract_table_data(textract_data)
        relevant_tables = [
            table for table in tables if check_relevancy_of_the_table(table)
        ]

        if relevant_tables:
            json_table_data = os.path.join(
                save_dir, f"{url_name_parser(URL)}_table.json"
            )
            for i, df in enumerate(tables):
                empty_row = pd.DataFrame([[""] * df.shape[1]])
                if i == 0:
                    df.to_csv(
                        csv_filename,
                        encoding="utf-8",
                        index=False,
                        mode="w",
                        header=False,
                    )
                else:
                    empty_row.to_csv(
                        csv_filename,
                        encoding="utf-8",
                        index=False,
                        mode="a",
                        header=False,
                    )
                    df.to_csv(
                        csv_filename,
                        encoding="utf-8",
                        index=False,
                        mode="a",
                        header=False,
                    )
            combined_tables_json = pd.concat(tables, ignore_index=True).to_json(
                orient="records", indent=4
            )
            with open(json_table_data, "w") as f:
                f.write(combined_tables_json)
            print(f"Saved table data as JSON {json_table_data}")
            print(f"Saved extracted table as CSV {csv_filename}")

        elif not relevant_tables:
            layout_response = textract.analyze_document(
                Document={"S3Object": {"Bucket": bucket_name, "Name": s3_files[0]}},
                FeatureTypes=["LAYOUT"],
            )
            with open(json_filename, "w") as f:
                json.dump(layout_response["Blocks"], f, indent=4)
            with open(json_filename, "r") as f:
                textract_data = json.load(f)
            os.remove(json_filename)
            layout_block = layout_response["Blocks"]
            layout = extract_layout_data(layout_block)

            if layout:
                layout_json_filename = os.path.join(
                    save_dir, f"{url_name_parser(URL)}_layout.json"
                )
                with open(layout_json_filename, "w") as f:
                    json.dump(layout, f, indent=4)
                print(f"Saved layout data as {layout_json_filename}")
                print("Sending layout data to OpenAI...")
                layout_text = "\n".join(
                    [line.strip() for line in layout if line.strip()]
                )
                html_text = scraped_html.strip()
                event_data_llm = llm_openai(
                    [layout_text, html_text]
                )  # Or json.load(open(layout_json_filename)) if you prefer consistency
                print("EVENT DATA LLM : ", event_data_llm)
                if event_data_llm and event_data_llm.strip():
                    event_data_llm = event_data_llm.replace("`", "")
                    event_data_llm = event_data_llm.replace("json", "")
                    try:
                        event_data_json = json.loads(event_data_llm)
                    except json.JSONDecodeError:
                        print("Invalid JSON format returned from OPENAI LLM")
                        event_data_json = []
                    if event_data_json:
                        try:
                            df = pd.json_normalize(event_data_json)
                            # Because of the nested structure of the JSON output, we needed to to make flat JSON so we renamed them
                            # Based of on our AI Prompt
                            df.rename(
                                columns={
                                    "Event Time.Start Time": "Start Time",
                                    "Event Time.End Time": "End Time",
                                    "Event Location.City": "City",
                                    "Event Location.State": "State",
                                },
                                inplace=True,
                            )
                            # print("AI response: ", event_data_llm)
                            # df = pd.read_json(io.StringIO(event_data_llm))
                            df.to_csv(
                                csv_filename,
                                encoding="utf-8",
                                index=False,
                                mode="w",
                                header=True,
                            )
                            print(f"Saved OpenAI extracted data as {csv_filename}")
                        except ValueError:
                            print("error processing csv in layout")

        # Textract did not work, use OPENAI API
        else:
            print("No tables or layout extracted. Processing with OpenAI...")
            event_data_llm = llm_openai(image_paths)
            if event_data_llm and event_data_llm.strip():
                try:
                    df = pd.read_json(io.StringIO(event_data_llm))
                    df.to_csv(
                        csv_filename,
                        encoding="utf-8",
                        index=False,
                        mode="w",
                        header=True,
                    )
                    print(f"Saved OpenAI extracted data as {csv_filename}")
                except ValueError:
                    print("Upload a screenshot manually at http://127.0.0.1:5000/")
            else:
                print("Upload a screenshot manually at http://127.0.0.1:5000/")
    else:
        print("Multiple images uploaded, using OpenAI to extract data...")
        all_event_data = []
        event_data_llm = llm_openai(image_paths)
        if event_data_llm and event_data_llm.strip():
            try:
                df = pd.read_json(io.StringIO(event_data_llm))
                all_event_data.append(df)
            except ValueError:
                print(f"Error processing {image_paths} with OpenAI.")

        if all_event_data:
            # merge dataframes
            merged_df = pd.concat(all_event_data, ignore_index=True)
            final_csv = os.path.join(save_dir, f"{url_name_parser(URL)}.csv")
            df.to_csv(final_csv, encoding="utf-8", index=False, mode="w", header=True)
            llm_json_filename = os.path.join(
                save_dir, f"{url_name_parser(URL)}_llm.json"
            )
            df.to_json(llm_json_filename, orient="records", indent=4)

            print(f"Saved LLM output JSON as {llm_json_filename}")
            print(f"Saved JSON as {llm_json_filename}")
            print(f"Saved CSV saved as {final_csv}")

    # if len(image_paths) > 1:
    if final_csv and os.path.basename(final_csv):
        s3.upload_file(final_csv, bucket_name, os.path.basename(final_csv))
    elif csv_filename and os.path.exists(csv_filename):
        s3.upload_file(csv_filename, bucket_name, os.path.basename(csv_filename))
    print("reseting globally set URL..")
    URL = None
    return csv_filename
