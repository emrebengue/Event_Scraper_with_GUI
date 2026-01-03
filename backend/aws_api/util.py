from datetime import datetime, timezone
import hashlib
import base64
from aws_api.jobs import CreateJobRequest

from fastapi import HTTPException

def current_iso_time():
    return datetime.now(timezone.utc).isoformat()

def url_cache_key(url: str) -> str :
    return hashlib.sha256(url.encode()).hexdigest()  # for now keep hashing simple

def pdf_cache_key(pdf: bytes) -> str:
    return hashlib.sha256(pdf).hexdigest()


# Decode base64-encoded PDF string to raw bytes for hashing
def decode_pdf_base64(pdf_b64: str) -> bytes:
    return base64.b64decode(pdf_b64)

def verify_cache_key(req: CreateJobRequest) -> str | None:
    cache_key = None

    # Generate cache key based on input type
    if req.input_type == "url":
        cache_key = url_cache_key(req.content)
        
    elif req.input_type == "pdf": 
        b64_pdf = decode_pdf_base64(req.content)
        cache_key = pdf_cache_key(b64_pdf)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid input_type: {req.input_type}")

    return cache_key