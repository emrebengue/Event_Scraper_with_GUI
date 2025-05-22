import time
import os
from config import s3, textract, bucket_name_pdf, region
from collections import defaultdict
import json
from openai import OpenAI
from LLM_openai import LLMModels
from dotenv import load_dotenv

load_dotenv()

# ADD YOUR OPENAI API KEY!!
# [0]Openai Paid
api_key_list = [x.strip() for x in os.getenv("API_LIST").split(",")]
api_key_openai = api_key_list[0]

client_openai = OpenAI(api_key=api_key_openai)

llm_models = LLMModels(client_openai=client_openai)


def extract_text_from_pdf(document_name):
    # Create bucket if it does not exists already
    try:
        s3.create_bucket(
            Bucket=bucket_name_pdf,
            CreateBucketConfiguration={"LocationConstraint": region},
        )
        print(f"{bucket_name_pdf} created.")

    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"{bucket_name_pdf} already exists.")

    response = textract.start_document_text_detection(
        DocumentLocation={
            "S3Object": {"Bucket": bucket_name_pdf, "Name": document_name}
        }
    )

    job_id = response["JobId"]
    print(f"Started job with ID: {job_id}")

    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        status = result["JobStatus"]
        print(f"Job status: {status}")
        if status in ["SUCCEEDED", "FAILED"]:
            break
        time.sleep(5)
    if status == "SUCCEEDED":
        blocks = []
        next_token = None

        while True:
            if next_token:
                result = textract.get_document_text_detection(
                    JobId=job_id, NextToken=next_token
                )
            else:
                result = textract.get_document_text_detection(JobId=job_id)

            blocks.extend(result["Blocks"])
            next_token = result.get("NextToken")
            if not next_token:
                break

        # Group blocks by page and y-coordinate
        rows_by_y = defaultdict(list)
        for block in blocks:
            if block["BlockType"] == "LINE":
                y_coord = round(block["Geometry"]["BoundingBox"]["Top"], 2)
                rows_by_y[y_coord].append(
                    (block["Geometry"]["BoundingBox"]["Left"], block["Text"])
                )

        # Sort rows by their vertical position, then sort items in each row by horizontal position
        sorted_rows = sorted(rows_by_y.items())
        structured_lines = []

        for _, row in sorted_rows:
            sorted_line = sorted(row)  # Sort by x-axis (left)
            line_text = " | ".join(text for _, text in sorted_line)
            structured_lines.append(line_text)

        text = "\n".join(structured_lines)
        try:
            result = llm_models.llm_openai_from_textract_pdf(text)
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


def upload_file_to_s3(local_path, pdf_file):
    file_name = os.path.basename(pdf_file)
    s3.upload_file(local_path, bucket_name_pdf, file_name)
    print(f"Uploaded {local_path} to s3://{bucket_name_pdf}/{file_name}")
    return file_name


# USAGE
# bucket = "your-s3-bucket-name"
# document = "path/to/your/document.pdf"  # relative to the S3 bucket root
#
# text = extract_text_from_pdf(bucket, document)
# print(text)
