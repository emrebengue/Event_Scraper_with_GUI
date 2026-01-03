from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import shutil

from extract_via_image_processing import main as screenshot_main, todays_date
from algorithm_based_extraction import main as algo_main
from extract_pdf import upload_file_to_s3, extract_text_from_pdf

app = FastAPI()

UPLOAD_FOLDER = "UPLOAD"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


class ScrapeRequest(BaseModel):
    url: str


@app.get("/")
def home():
    return {"message": "Fast API is working.."}


# Runs extract_via_image_processing.py
@app.post("/extract-via-screenshot")
def extract_from_url_screenshot(request: ScrapeRequest):
    try:
        csv_file = screenshot_main(request.url)
        if not csv_file:
            raise HTTPException(status_code=400)
        return {
            "message": "Scraping successful",
            "csv_file": os.path.basename(csv_file),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/extract-via-algo")
def extract_with_algo(request: ScrapeRequest):
    try:
        algo_main(request.url)
        return {"message": "Algorithm-based extraction complete."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# extract_via_image_processing can also proccess manually taken Screenshot-based
# instead of giving a url, you can give a screenshot path
@app.post("/extract-manual-screenshot")
def extract_from_uploaded_file(file: UploadFile = File(...)):
    saved_file = os.path.join(UPLOAD_FOLDER, file.filename)
    try:
        with open(saved_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        csv_file = screenshot_main(saved_file)
        if not csv_file:
            raise HTTPException(status_code=400)

        return {
            "message": "Manual screenshot processing successful",
            "csv_file": os.path.basename(csv_file),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(saved_file):
            os.remove(saved_file)


@app.post("/extract-pdf")
def extract_from_pdf_upload(file: UploadFile = File(...)):
    local_path = os.path.join(UPLOAD_FOLDER, file.filename)
    try:
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        s3_filename = upload_file_to_s3(local_path, file.filename)
        text = extract_text_from_pdf(s3_filename)

        return {"message": "PDF processed successfully", "data": text}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)
