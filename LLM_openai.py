class LLMModels:
    def __init__(self, client_openai):
        """
        Store references to API clients so the methods can call them.
        """
        self.client_openai = client_openai

    def llm_openai_from_textract_pdf(self, extracted_text):
        try:
            prompt = f"""
            Below is the plain text extracted from a PDF using OCR (Textract). Extract all structured college fair or event listings from this text.

            Here is the text:
            {extracted_text}
            """

            system_prompt = """
            *Role:*  
            You are a highly skilled Structured Event Data Extractor. Your task is to extract the most accurate event details from plain OCR text.

            *Objective:*  
            Extract key event details and output them **strictly in JSON format**.

            *Extract the following fields:*
            - *Event Name*
            - *Event Date:* Standardized to YYYY-MM-DD
            - *Event Time:* Start/End in 24-hour HH:MM format
            - *Event Location:* City and state/province
            - *Event URL:* If available

            *Instructions:*  
            - Remove header/footer noise and irrelevant text.
            - Standardize all formats.
            - **Return only JSON. No explanations.**
            - **If no event found, return `[]`.**
            """

            response = self.client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )

            result = response.choices[0].message.content.strip()
            result = result.replace("```json", "").replace("```", "").strip()
            return result

        except Exception as e:
            print(f"[OpenAI PDF LLM Error] {e}")
            return None

    def llm_openai_get_event_links(self, list_of_path):
        try:
            prompt = f"""
                Here is the **JSON list**:
                {list_of_path}
                """
            system_prompt = """
            You will receive a **Python list of URLs scraped from a college event/fair webpage**. Your task is to identify indices of URLs that **do NOT point to a specific event/fair detail page** (i.e., invalid links). 

                ### Rules for Invalid Links:
                1. **Generic Pages**: Links containing terms like `events`, `calendar`, `programs`, `overview`, `schedule`, `list`, `register` (if standalone), or `index` in their path.
                2. **Non-Specific Paths**: URLs without a unique identifier (e.g., no slugs with dates, event names, or alphanumeric IDs like `summer-workshop-2025` or `1309401`).
                3. **Navigation/Noise**: Links to site sections like `contact`, `about`, or `home`.

                ### Rules for Valid Links:
                - URLs with **unique event names**, **dates**, or **IDs** in their path (e.g., `miami-nacac-college-fair-1225634` or `event-calendar/Details/...`).
                - URLs with `/Register/` *are valid* if they include a unique event slug/ID (e.g., `ap/Events/Register/2JFNZ8gH3CNCz` is invalid because it lacks a descriptive slug, but `event-calendar/Details/...` followed by a registration link is valid).

                ### Output:
                Return a **strictly valid JSON array** containing **only the indices of invalid URLs**. Example: `[0, 3, 5]`. If all are valid, return `[]`.

                ### Instructions:
                1. Analyze each URL's path segments and parameters.
                2. Flag indices of URLs matching the "Invalid Links" rules above.
                3. When in doubt, assume validity to minimize false positives.
                4. **NO EXPLANATIONS**—only the array.
                    """
            response = self.client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )

            # Extract and return the response
            response_text = response.choices[0].message.content
            response_text = response_text.replace("`", "")
            response_text = response_text.replace("json", "")
            response_text = response_text.strip()
            return response_text
        except Exception as e:
            print(f"Error extracting event details: {e}")
            return None

    def llm_openai_dictionary(self, text):
        try:
            # Define the prompt for OpenAI
            prompt = f"""
                Here is the **JSON dictionary**:
                {text}
                """

            # Call OpenAI API
            system_prompt = """
                **Role:**  
                You are a highly skilled Structured Event Data Extractor. Your task is to process **a JSON dictionary** in which each key maps to a text chunk derived from a college event or fair website's HTML. Although the exact layout and hierarchy may vary between different keys, each text chunk contains event listings with essential details. The text chunks have been pre-selected and maintain most of the structural cues (such as headers, paragraphs, and line breaks) that indicate the event hierarchy.

                **Objective:**  
                From each text chunk within the dictionary, extract key event details (Event Name, Date, Time, City, State, URL) and output them in a single JSON object in the specified format. Events generally follow a consistent pattern (for example, six distinct fields, each on its own line), but slight variations can occur. If one event appears to have fewer or more lines than expected (e.g., five instead of six), assume that the standard pattern still applies and assign null to any missing field rather than discarding or misinterpreting the event.

                **Extract the following fields for each event:**
                - **Event Name:** The title or name of the event.
                - **Event Date:** The event's date, standardized to the format YYYY-MM-DD. (If a date range is given, use the start date; if only month and day are given, infer the year from context or assume the current year.)
                - **Event Time:** The start time of the event in 24-hour HH:MM format (or null if not available). (Note: Event time values are expected to follow conventional quarter-hour increments (e.g., times that end in :00, :15, :30, or :45). Any time value that does not conform to these typical increments should be treated as invalid (set to null).)
                When encountering a time range formatted as "START TIME to END TIME" (e.g., "10:30 AM to 12:15 PM"), interpret this as the duration of an event, with the first time representing the event's start and the second time its end.
                
                If a single time is present without a corresponding end time, consider it as a standalone timestamp, which may not necessarily indicate the event's start time.
                
                Prioritize time ranges over single timestamps when determining event durations.
                - **Event City:** The city where the event is held (or null if not explicitly mentioned).
                - **Event State/Province:** The state or province (or null if not available).
                - **Event URL:** A URL linking to more event details (or null if not found).

                **Input:**  
                A JSON dictionary where:
                - Each **key** represents an identifier or label for the text chunk (e.g., an event reference, page URL, or internal tag).
                - Each **value** is the plain text extracted from a college fair or event webpage.  
                Although most chunks follow a standard segmentation, some may have fewer lines. In such cases, infer that the standard pattern is valid and assign null to missing fields while preserving the information from remaining lines.

                **Output:**  
                Return a single JSON object in the following format:

                ```json
                {
                "events": [
                    {
                    "name": "EventName",
                    "date": "YYYY-MM-DD",
                    "time": "HH:MM",          // or null if unknown
                    "city": "CityName",       // or null if unavailable
                    "state": "StateOrProvince", // or null if unavailable
                    "url": "EventURL"         // or null if unavailable
                    },
                    // ... additional event objects if multiple events are found
                ]
                }


                **Instructions:**

                1. **Process the Input Text:**  
                - Use the structural cues (such as consistent line breaks, headers, or bullet points) to separate and identify individual events.

                2. **Extract Event Details:**  
                - **Event Name:** Identify the event title from the most prominent line in the event block.
                - **Event Date:** Identify and standardize the date. Handle various formats like "August 28, 2024", "2024-08-28", "08/28/2024". If a range is present, use the start date.
                - **Event Time:** Convert various time formats (e.g., "5:00 PM", "17:00", "10am") to a 24-hour HH:MM format. If no time is provided, assign null.
                - **Event City & State/Province:** Extract the location details. They may appear together (e.g., "Los Angeles, CA") or separately. If one part is missing, assign null to the missing field.
                - **Event URL:** Extract any URL present (for instance, following a "Learn More" cue) or assign null if not found.

                3. **Handle Variations and Ambiguities:**  
                Pattern Recognition:
                        Events often follow repetitive patterns. Identify common structures in the text and use them for better extraction accuracy.
                        If a pattern is recognized (e.g., name always on the first line, date on the second, etc.), use it to infer missing details.
                - In cases of ambiguity or when a field cannot be confidently extracted, set its value to null rather than making an incorrect guess.

                4. **Construct Valid JSON:**  
                - For each event identified, construct a JSON object with the specified keys.
                - Aggregate all event objects into a JSON array under the key "events."
                - Ensure that your final output is valid JSON without any extraneous text or formatting.

                5. **Output the Final JSON:**  
                - Return only the JSON object as your output.

                Focus on accuracy, consistency, and careful handling of the patterns, even when slight variations occur between event listings. If an event deviates from the common structure, normalize it to match the standard pattern by assigning null to any missing fields.
                """
            response = self.client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )

            # Extract and return the response
            response_text = response.choices[0].message.content
            response_text = response_text.replace("`", "")
            response_text = response_text.replace("json", "")
            response_text = response_text.strip()
            return response_text
        except Exception as e:
            print(f"Error extracting event details: {e}")
            return None

    def llm_openai_plain_text(self, text):
        try:
            prompt = f"""
            Here is the **plain text**:
            {text}
            """

            system_prompt = """
            **Role:**  
            You are a highly skilled Structured Event Data Extractor. Your task is to process plain text that has been cleaned from a college event or fair website's HTML. Although the exact layout and hierarchy may vary between websites, each text chunk contains event listings with essential details. The input text chunks have been pre-selected and maintain most of the structural cues (such as headers, paragraphs, and line breaks) that indicate the event hierarchy.

            **Objective:**  
            From each provided text chunk, extract key details for every event and output a single JSON object in the specified format. 

            **Extract the following fields for each event:**
            - **Event Name:** The title or name of the event.
            - **Event Date:** The event's date, standardized to the format YYYY-MM-DD. (If a date range is given, use the start date; if only month and day are given, infer the year from context or assume the current year.)
            - **Event Time:** The start time of the event in 24-hour HH:MM format (or null if not available).
            - **Event City:** The city where the event is held (or null if not explicitly mentioned).
            - **Event State/Province:** The state or province (or null if not available).
            - **Event URL:** A URL linking to more event details (or null if not found).


            **Input:**  
            Plain text derived from cleaned HTML from a college fair/event page with event details.

            **Output:**  
            Return a single JSON object in the following format:

            ```json
            {
            "events": [
                {
                "name": "EventName",
                "date": "YYYY-MM-DD",
                "time": "HH:MM",          // or null if unknown
                "city": "CityName",       // or null if unavailable
                "state": "StateOrProvince", // or null if unavailable
                "url": "EventURL"         // or null if unavailable
                },
                // ... additional event objects if multiple events are found
            ]
            }
            ```

            **Instructions:**

            1. **Process the Input Text:**  
            - Use the structural cues (such as consistent line breaks, headers, or bullet points) to separate and identify individual events.

            2. **Extract Event Details:**  
            - **Event Name:** Identify the event title from the most prominent line in the event block.
            - **Event Date:** Identify and standardize the date. Handle various formats like "August 28, 2024", "2024-08-28", "08/28/2024". If a range is present, use the start date.
            - **Event Time:** Convert various time formats (e.g., "5:00 PM", "17:00", "10am") to a 24-hour HH:MM format. If no time is provided, assign null.
            - **Event City & State/Province:** Extract the location details. They may appear together (e.g., "Los Angeles, CA") or separately. If one part is missing, assign null to the missing field.
            - **Event URL:** Extract any URL present (for instance, following a "Learn More" cue) or assign null if not found.

            3. **Handle Variations and Ambiguities:**  
            Pattern Recognition:
                    Events often follow repetitive patterns. Identify common structures in the text and use them for better extraction accuracy.
                    If a pattern is recognized (e.g., name always on the first line, date on the second, etc.), use it to infer missing details.
            - In cases of ambiguity or when a field cannot be confidently extracted, set its value to null rather than making an incorrect guess.

            4. **Construct Valid JSON:**  
            - For each event identified, construct a JSON object with the specified keys.
            - Aggregate all event objects into a JSON array under the key "events."
            - Ensure that your final output is valid JSON without any extraneous text or formatting.

            5. **Output the Final JSON:**  
            - Return only the JSON object as your output.

            Focus on accuracy, consistency, and careful handling of the patterns, even when slight variations occur between event listings. If an event deviates from the common structure, normalize it to match the standard pattern by assigning null to any missing fields.
            """

            response = self.client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )

            # Extract and return the response
            response_text = response.choices[0].message.content
            response_text = response_text.replace("`", "")
            response_text = response_text.replace("json", "")
            response_text = response_text.strip()
            return response_text

        except Exception as e:
            print(f"Error extracting event details: {e}")
            return None

    def llm_openai_merger(self, detail_page_json, listing_page_json):
        """
        Merge results from both event extraction methods to create more complete event data.

        Args:
            detail_page_json (str): JSON string from processing individual event detail pages
            listing_page_json (str): JSON string from processing the main listing page

        Returns:
            str: A merged JSON string containing all events with the most complete information
        """
        try:
            prompt = f"""
            You are an expert event data merger. You will receive two JSON objects containing event information from the same source website, but extracted in different ways.

            **Input 1**: JSON from processing individual event detail pages:
            {detail_page_json}

            **Input 2**: JSON from processing the main listing page:
            {listing_page_json}

            Both inputs follow the same structure:
            {{
            "events": [
                {{
                "name": "EventName",
                "date": "YYYY-MM-DD",
                "time": "HH:MM",          // or null if unknown
                "city": "CityName",       // or null if unavailable
                "state": "StateOrProvince", // or null if unavailable
                "url": "EventURL"         // or null if unavailable
                }},
                // ... additional event objects
            ]
            }}
            """

            system_prompt = """
            You are an expert event data merger. Your task is to combine event information from two different extraction methods to create the most complete dataset possible.

            **Instructions:**

            1. **Identify Matching Events**:
               - Match events between the two inputs using the following criteria (in descending priority):
                 - Exact URL match
                 - Name + Date match
                 - Similar name (>80% similarity) + Close date (±3 days)

            2. **Merge Matching Events**:
               - For each pair of matching events, create a new event object
               - For each field, use the first available value in this priority order:
                 a. Non-null value from Input 1 (detail pages are usually more accurate)
                 b. Non-null value from Input 2
                 c. null if neither input has the value

            3. **Handle Unique Events**:
               - Include events found in only one of the inputs as-is
               - Events only found in the detail pages (Input 1) are likely more accurate
               - Events only found in the listing page (Input 2) should still be included

            4. **Ensure Data Quality**:
               - Verify that date formats are consistently YYYY-MM-DD
               - Verify that time formats are consistently HH:MM (24-hour format)
               - Standardize location information (e.g., "New York, NY" → city: "New York", state: "NY")
               - Ensure all URLs are absolute, not relative

            5. **Return Complete Results**:
               - Return all events in a single "events" array
               - Sort events by date, with earliest events first
               - Remove any duplicates with identical names and dates

            **Output**: A single merged JSON object containing all events with the most complete information available, using the same structure as the inputs.

            Your goal is to create the most comprehensive and accurate collection of events possible by combining information from both sources. If there are conflicts between the data sources, prioritize information from detailed pages (Input 1) as it is typically more accurate.
            """

            response = self.client_openai.chat.completions.create(
                model="gpt-4o",  # Using the stronger model for better merging logic
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )

            # Extract and return the response
            response_text = response.choices[0].message.content
            # Clean up the response if needed
            if "```json" in response_text:
                # Extract just the JSON part if it's in a code block
                start = response_text.find("```json") + 7
                end = response_text.rfind("```")
                response_text = response_text[start:end].strip()

            return response_text

        except Exception as e:
            print(f"Error merging event details: {e}")
            return None
