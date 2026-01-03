# https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html

import boto3
import os
import json
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Literal

from .util import verify_cache_key

aws_region = os.getenv("AWS_REGION")
jobs_table = os.getenv("JOBS_TABLE", "event_scrape_jobs")
cache_table = os.getenv("CACHE_TABLE", "site_cache")
jobs_queue_url = os.getenv("JOBS_QUEUE_URL")

TTL = 24 * 3600 # 1 day caching time

app = FastAPI()


dynamodb = boto3.resource('dynamodb', region_name=aws_region)
jobs_table_resource = dynamodb.Table(jobs_table)
cache_table_resource = dynamodb.Table(cache_table)
sqs = boto3.client("sqs", region_name=aws_region)

class CreateJobRequest(BaseModel):
    input_type: Literal["url", "pdf"]
    content: str  # URL string or base64 encoded file, or file path


@app.post("/jobs")
def create_or_update_job(req: CreateJobRequest) -> object:

    cache_key = verify_cache_key(req)
    item = None
    job_id = None
    
    if cache_key:
        resp = cache_table_resource.get_item(Key={"cache_key": cache_key})
        item = resp.get("Item")


    # validate if database record is still valid
    if item:
        cached_timestamp = item.get("created_at")
        curr_time = time.time() # prev int(time.time())
        job_id = item.get("job_id")

        # Always increment visited count for tracking
        jobs_table_resource.update_item(
            Key={"job_id": job_id},
            UpdateExpression="ADD visited :inc",
            ExpressionAttributeValues={":inc": 1}
        )

        # Only return cached result if still valid
        if cached_timestamp and (curr_time - int(str(cached_timestamp))) < TTL:
            jobs_table_resource.update_item(
                Key={"job_id": job_id},
                #create alias for status because its a reserved word
                ExpressionAttributeNames={"#status": "status"},
                # append "cached" to :status
                ExpressionAttributeValues={":status": "cached"},
                # set status to :status which is "cached"
                UpdateExpression="SET #status = :status",
            )
            return { "job_id": job_id, "status": "cached" }

    # No cache or cache expired -> create new job
    job_id = str(uuid.uuid4())
    created_time = time.time() #prev int(time.time())

    job_info = {
        "job_id": job_id,
        "status": "queued",
        "input_type": req.input_type,
        "content": str(req.content),
        "visited": 0,
        "created_at": created_time,
    }

    jobs_table_resource.put_item(Item=job_info)

    sqs.send_message(
        QueueUrl=jobs_queue_url, # type: ignore # We will get to it
        MessageBody=json.dumps({
            "job_id": job_id,
            "input_type": req.input_type,
            "content": req.content
        })
    )

    return { "job_id": job_id, "status": "queued" }

@app.get("/jobs/{job_id}")
def get_item(job_id: str):
    resp = jobs_table_resource.get_item(Key={"job_id": job_id})
    item = resp.get("Item")

    if not item:
        raise HTTPException(status_code=404, detail="This job does not exist")

    return item




