import boto3
import os
import openai
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# OPENAI KEY
OPENAI_KEY = os.environ.get("API")
client_openai = openai.OpenAI(api_key=OPENAI_KEY)

# AWS Setup
aws_region = "us-east-2"
aws_s3 = boto3.client("s3", region_name=aws_region)
aws_textract = boto3.client("textract", region_name=aws_region)
bucket_name = "uottawa-scraper-bucket"
bucket_name_pdf = "uottawa-pdf-extraction"
