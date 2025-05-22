import boto3
import os
import openai
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# OPENAI KEY
OPENAI_KEY = os.environ.get("API_OPENAI")
client_openai = openai.OpenAI(api_key=OPENAI_KEY)

# AWS Setup
region = "us-east-2"
s3 = boto3.client("s3", region_name=region)
textract = boto3.client("textract", region_name=region)
bucket_name = "uottawa-scraper-bucket"
bucket_name_pdf = "uottawa-pdf-extraction"
