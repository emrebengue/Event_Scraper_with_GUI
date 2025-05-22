# Event_Scraper
Honours  Project - Emirali Gungor, Emre Bengu

## Overview

This project aims to scrape event pages from various US school fair websites and extract structured information such as event dates, times, locations, and event-related links. It also supports event extraction from PDF catalogs using OCR. The extracted data can be viewed or exported using a Flask web interface.

## Thought Process

When we started the project, we analyzed multiple websites (provided by our client) to determine if they loaded dynamically or statically. We quickly realized that almost all tested websites were dynamic, meaning their event information was loaded via JavaScript rather than being available in the initial HTML response. This led us to choose Selenium along with BeautifulSoup for scraping, as it allows us to render JavaScript and extract the dynamically loaded content.

Next, we needed a method to accurately identify the event information section within a given website. We devised a weighted system based on event-related keywords, structured elements, and metadata such as schema.org annotations. This system helps us extract event-related sections even when websites structure their HTML differently. The function `extract_event_sections` was implemented for this purpose.

During our tests, we observed that many event pages did not contain event details directly but instead provided links to individual event pages. This required us to extract all links from the identified event section and filter them to retain only relevant event pages. Initially, we experimented with multiple regex-based filtering techniques, but due to variations in website structures, it was difficult to standardize a universal regex pattern. As a result, we implemented a system to extract all anchor tags and use an OpenAI LLM to determine which links are likely to point to individual event pages.

We also realized that in some cases, the event information is embedded inside downloadable PDFs, typically as part of event catalogs or brochures. These PDFs are often shared by school organizations and contain comprehensive listings of upcoming events. Since these documents are not directly parseable via standard HTML techniques, we integrated AWS Textract, which allows us to perform OCR on PDFs. The text extracted from these PDFs is then sent to our OpenAI-powered pipeline, which extracts structured event details such as event name, date, time, location, and links.

Finally, recognizing the need for a user-friendly interface and data persistence, we developed a full-stack web application using Flask. The application includes user authentication, data management using SQLAlchemy, and support for viewing and exporting results.

## Features

- **PDF Support with AWS Textract**: Uploads PDFs to S3, runs Textract OCR, and processes the output for event data.
- **Event Section Identification**: Uses regex scoring and heuristics to extract the most relevant event container in HTML.
- **Event Link Extraction & Filtering**: Extracts anchor tags and sends the list to an OpenAI model to eliminate irrelevant links.
- **Date, Time, and Location Extraction**: Scans for patterns and navigates the DOM to return event-specific sections.
- **LLM Integration with OpenAI**: All text (HTML or PDF) is passed to OpenAI models for final event data extraction.
- **Web Interface with Flask**: Clean and responsive UI to scrape, review, and export data.
- **Database Storage with SQLAlchemy**: Events and users are stored in a SQLite-backed schema with user-specific views.

## Implementation Details

The architecture is modular and scalable. Here's a breakdown of the major implementation components and how each is handled across the pipeline.

---

### 1. Weighted Event Section Detection ([algorithm_based_extraction.py](algorithm_based_extraction.py))

We implemented a custom scoring system to identify HTML sections most likely to contain event information. This was necessary due to the wide variability in website structures.

- The function `extract_event_sections(html_text)` loops through elements like `<div>`, `<section>`, `<article>`, `<li>`, and assigns scores based on several factors:
  - Presence of **event-related keywords** (e.g., "schedule", "fair", "seminar")
  - Presence of **date and time patterns** using regex
  - Presence of **schema.org markup** like `itemtype='http://schema.org/Event'`
  - Use of structural hints (e.g., parent containers, list nesting)

- Scores are aggregated up to 3 parent levels to capture container hierarchies.
- The container with the highest cumulative score is selected as the likely event section.
- This approach balances flexibility with precision and adapts well to diverse layouts.

### 2. PDF Extraction with AWS Textract ([extract_pdf.py](extract_pdf.py))

This script manages the upload of a PDF to an S3 bucket and extracts its content using AWS Textract.

- `upload_file_to_s3(local_path, file_name)`:
  Uploads a user-provided PDF to an S3 bucket.

- `extract_text_from_pdf(document_name)`:
  Launches a Textract job to analyze the PDF stored in S3. Once the job is complete, it gathers all `LINE` blocks, sorts them by their position on the page (top-to-bottom, left-to-right), and returns the structured text in a readable format.

### 3. LLM Pipeline (OpenAI API) ([LLM_openai.py](LLM_openai.py))

All structured extraction is performed by OpenAI models (GPT-4o-mini). The following stages use LLMs:

- **Filtering Event Links**: After gathering raw `<a>` tags, we ask OpenAI to return indices of links that are not detail pages.
- **Event Extraction from HTML Listings**: Once a listing section is cleaned, it is sent to OpenAI to parse events.
- **Event Extraction from Detail Pages**: Each detail page's content is cleaned and sent to OpenAI.
- **Event Extraction from PDFs**: The OCR-extracted text is sent to OpenAI with prompts tailored for unstructured data.
- **Merging Listings + Detail Events**: OpenAI merges the two JSON results into a unified format.

Functions:
- `llm_openai_from_textract_pdf(extracted_text)`
- `llm_openai_get_event_links(list_of_links)`
- `llm_openai_plain_text(text_from_listing)`
- `llm_openai_dictionary(json_dict_from_detail_pages)`
- `llm_openai_merger(detail_json, listing_json)`

Each function uses a purpose-specific prompt with strict formatting constraints to ensure the response is in JSON.

### 4. Database Integration ([database.py](database.py))

We use SQLAlchemy to manage persistent data:

- **User Table**: Handles authentication with hashed passwords, unique emails, and timestamps.
- **Event Table**: Stores event fields including name, date, time, city, state, URL, source URL, and timestamps.
- Each user has access to their own set of saved events. Events can be added, updated, deleted, and exported.

Models:
- `User` (username, email, password, events[])
- `Event` (name, date, time, location, user_id, created_at)

### 5. Flask Web Application ([app.py](app.py))

The web app provides a user interface for scraping and viewing events:

#### Routes:
- `/`: Welcome page
- `/signup`, `/login`, `/logout`: User auth routes
- `/main`: Dashboard to input URLs or upload PDFs
- `/process`: Accepts an event listing URL and begins scraping
- `/upload-pdf`: Handles PDF upload, runs Textract, and passes text to OpenAI
- `/events`: Table view of all stored events
- `/event/<id>`: Individual event page
- `/event/edit/<id>`: Update event fields
- `/event/delete/<id>`: Remove an event
- `/download/<filename>` and `/download_excel/<filename>`: Download event data

#### HTML Rendering:
- Clean Bootstrap-based templates for responsive layout.
- Event results shown as cards or tables with interactive links.

#### Export Support:
- Events can be downloaded as `.json` or `.xlsx`.
- JSON output mirrors the structure returned by OpenAI.

### 6. HTML Keyword-Based Scraping ([html_keyword_scrape.py](html_keyword_scrape.py))

This module handles event section extraction from HTML using keyword scoring.

- `html_extractor(link)`  
  Main function to scrape a page, identify event-relevant sections using keyword heuristics (e.g. "college fair", "schedule", "date", "location"), clean the extracted HTML, and return plain text.

- Internals:
  - Uses `Selenium` to fully load dynamic websites.
  - Scores containers using a list of event-related keywords.
  - Boosts scores for elements higher up in the DOM tree that contain many matched keywords.
  - Applies additional noise reduction through functions like `remove_layout_noise()` and `remove_duplicate_lines()`.

This function is called by the screenshot-based extraction system (`extract_via_image_processing.py`) to enhance LLM accuracy with relevant HTML text.

## FastAPI Endpoints (fast_api.py)

In addition to the Flask interface, we implemented a separate FastAPI service for programmatic access to the scraping tools. These endpoints are designed to support different workflows (e.g., triggering a scrape from a frontend, uploading a PDF, or using screenshots).

Each route points to a specific file and backend function depending on the type of input (URL, image, PDF, or plain HTML).

To run the FASTAPI Server (Python virtual environment is recommended) :
  ```bash
  pip install -r requirements.txt
  uvicorn fast_api:app --reload
  ```
---

### `POST /extract-via-screenshot`  
**Points to:** `extract_via_image_processing.py → main()`  
**Use for:** Scraping events from a **URL** by taking a screenshot of the page.  
- Captures a full-page screenshot using Selenium  
- Uploads it to S3  
- Extracts structured event data using AWS Textract and OpenAI if needed  
- Returns a CSV with the results

Usage: 
```
curl -X POST http://127.0.0.1:8000/extract-via-screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://members.sacac.org/event-calendar"}'
```
---

### `POST /extract-manual-screenshot`  
**Points to:** `extract_via_image_processing.py → main()`  
**Use for:** Scraping events from a **user-uploaded screenshot/image file**.  
- Designed for direct image uploads (e.g., PNGs)  
- Performs the same processing as `/extract-screenshot`, but skips the URL screenshotting step

Usage:
```
curl -X POST http://127.0.0.1:8000/extract-manual-screenshot \
  -F "file=@screenshot.png"
```
*Use full path if you are not in the same folder as PDF*
example: /home/emre/Documents/screenshot.png

---

### `POST /extract-via-algo`  
**Points to:** `algorithm_based_extraction.py → main()`  
**Use for:** Scraping events using **HTML parsing and link crawling**.  
- Fetches the HTML source of the provided URL  
- Applies the `extract_event_sections` function to identify the most relevant content  
- Uses OpenAI to extract structured data from listings and linked detail pages  
- Merges both into a unified JSON format

Usage:
```
curl -X POST http://127.0.0.1:8000/extract-via-algo \
  -H "Content-Type: application/json" \
  -d '{"url": "https://members.sacac.org/event-calendar"}'
```
---

### `POST /extract-pdf`  
**Points to:** `extract_pdf.py → extract_text_from_pdf()`  
**Use for:** Uploading a **PDF catalog or event flyer** for OCR-based extraction.  
- Uploads the PDF to S3  
- Runs an async Textract job to detect and extract lines  
- Sorts and formats the result based on bounding boxes  
- Sends the text to OpenAI to generate structured JSON of event data

Usage:
```
curl -X POST http://127.0.0.1:8000/extract-pdf \
  -F "file=@pdf_file.pdf"
```
*Use full path if you are not in the same folder as PDF*
example: /home/emre/Documents/pdf_file.pdf
