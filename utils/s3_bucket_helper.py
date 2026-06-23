import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlparse
import boto3
from botocore.config import Config
import configparser
from fastapi import File, status, HTTPException, UploadFile
from botocore.exceptions import NoCredentialsError, ClientError
from logger import *
import re, time, posixpath, os


config = configparser.ConfigParser()
config.read('config.ini')


aws_access_key = config["aws"]["access_key"]
aws_secret_key = config["aws"]["secret_key"]
aws_region_name = config["aws"]["s3_bucket_region"]
aws_bucket_name = config["aws"]["s3_bucket_name"]


# Globals
_s3_client_cache = None
_s3_client_expiry = None
_lock = asyncio.Lock()

'''async def get_s3_client():
    """
    Always returns a fresh S3 client using temporary STS credentials.
    """
    sts_client = boto3.client(
        'sts',
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region_name
    )

    response = sts_client.get_session_token(DurationSeconds=3600)
    credentials = response['Credentials']

    return boto3.client(
        's3',
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken'],
        region_name=aws_region_name,
        config=Config(signature_version='s3v4')
    )
'''

async def get_s3_client():
    """
    Returns a cached S3 client.
    Automatically refreshes credentials ~5 minutes before expiry.
    """
    global _s3_client_cache, _s3_client_expiry

    async with _lock:
        # Refresh if no client or it's expired
        if not _s3_client_cache or datetime.now() >= _s3_client_expiry:
            sts_client = boto3.client(
                "sts",
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region_name,
            )

            # Request new credentials
            response = sts_client.get_session_token(DurationSeconds=3600)
            creds = response["Credentials"]

            # Create S3 client with session credentials
            _s3_client_cache = boto3.client(
                "s3",
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=aws_region_name,
                endpoint_url=f"https://s3.{aws_region_name}.amazonaws.com",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "virtual"}
                ),
            )

            # Refresh 5 minutes before actual expiration
            _s3_client_expiry = creds["Expiration"].replace(tzinfo=None) - timedelta(minutes=5)

        return _s3_client_cache


async def generate_presigned_url(s3_client, s3_key: str, expires_in: int = 900):
    """
    Generate a pre-signed URL valid for `expires_in` seconds (default: 15 min).
    """
    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": aws_bucket_name, "Key": s3_key},
            ExpiresIn=expires_in  # in seconds
        )
        return url
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"status": "failure", "message": f"Failed to generate presigned URL: {str(e)}", "data": None}
        )


async def upload_file_to_s3(s3_key, file: UploadFile = File(...), s3_client=None):
    if s3_client is None:
        s3_client = await get_s3_client()
    try:
        original_filename = file.filename or "file"    
        no_space_filename = original_filename.replace(" ", "_")
        sanitized_filename = re.sub(r'[^\w\-.]', '_', no_space_filename)
        name_part, ext = os.path.splitext(sanitized_filename)
        timestamp = int(time.time())
        unique_filename = f"{name_part}{ext}"
        
        base_path = posixpath.dirname(s3_key)
        final_s3_key = posixpath.join(base_path, unique_filename)

        # Ensure file pointer is at start
        try:
            file.file.seek(0)
        except Exception:
            pass
        # Read the file content
        file_content = await file.read()

        # Upload the file to S3
        s3_client.put_object(
            Bucket=aws_bucket_name,
            Key=final_s3_key,
            Body=file_content,
            ContentType=file.content_type
        )

        return final_s3_key

    except NoCredentialsError:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status":"failure",
                "message":"AWS credentials not found.",
                "data": None
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": f"Failed to upload file: {str(e)}",
                "data": None
            }
        )


async def delete_file_from_s3(s3_key: str):
    logger.info(f"Deleting file {s3_key} from S3")

    s3_client = await get_s3_client()
    try:
        # Extract the actual key if a full URL is passed
        if s3_key.startswith("http"):
            parsed_url = urlparse(s3_key)
            s3_key = parsed_url.path.lstrip("/")

        response = s3_client.delete_object(Bucket=aws_bucket_name, Key=s3_key)

        if response["ResponseMetadata"]["HTTPStatusCode"] == 204:
            logger.info(f"File {s3_key} deleted successfully.")
            return True

        else:
            logger.warning(f"File '{s3_key}' deletion returned status code: {response['ResponseMetadata']['HTTPStatusCode']}")
            return False

    except ClientError as e:
        logger.error(str(e))
        return False
