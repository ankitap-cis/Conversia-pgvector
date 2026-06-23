from fastapi import UploadFile, File, HTTPException, status
from fastapi.responses import JSONResponse
from typing import List
from utils.s3_bucket_helper import upload_file_to_s3, generate_presigned_url, get_s3_client,aws_bucket_name
from logger import *
SCENARIO_BASE_PATH = "default_scenario_images/"

async def upload_scenario_images(files):
    try:
        logger.info(f"Received request to upload {len(files)} scenario images")
        if len(files) > 15:
            logger.warning(f"Attempted to upload {len(files)} images, which exceeds the limit")
            raise HTTPException(
                status_code=400,
                detail="You can upload a maximum of 15 images"
            )
        
        logger.info(f"Uploading {len(files)} scenario images to S3")
        uploaded_keys = []

        for file in files:
            logger.info(f"Processing file: {file.filename}")
            s3_key = f"{SCENARIO_BASE_PATH}{file.filename}"
            final_key = await upload_file_to_s3(s3_key, file)
            uploaded_keys.append(final_key)
        logger.info(f"Successfully uploaded {len(uploaded_keys)} images to S3")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
            "status": "success",
            "message": "Images uploaded successfully",
            "data": uploaded_keys
        }
        )
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )
    
async def get_scenario_images(db, current_user):
    try:
        logger.info(f"Received request to fetch scenario images BY CURRENT USER: {current_user.email}")
        s3_client = await get_s3_client()

        response = s3_client.list_objects_v2(
            Bucket=aws_bucket_name,
            Prefix=SCENARIO_BASE_PATH
        )

        contents = response.get("Contents", [])

        image_urls = {}

        for obj in contents:
            id = contents.index(obj) 
            key = obj["Key"]

            url = await generate_presigned_url(s3_client, key)
            image_urls[id] = {"image_url": url, "image_key": key}

        logger.info(f"Successfully fetched {len(image_urls)} scenario images")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content= {
            "status": "success",
            "data": image_urls
        })

    except Exception as e:
        logger.error(f"Failed to fetch images: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch images: {str(e)}"
        )