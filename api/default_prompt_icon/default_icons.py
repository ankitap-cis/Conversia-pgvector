from fastapi import status, HTTPException
from fastapi.responses import JSONResponse
from logger import *
from utils.s3_bucket_helper import upload_file_to_s3, get_s3_client, aws_bucket_name, generate_presigned_url

PROMPT_BASE_PATH = "default_prompt_icons/"

async def upload_prompt_icons(files):
    try:
        logger.info(f"Received request to upload {len(files)} prompts icons")
        if len(files) > 15:
            logger.warning(f"Attempted to upload {len(files)} icons, which exceeds the limit")
            raise HTTPException(
                status_code=400,
                detail="You can upload a maximum of 15 icons"
            )
            
        logger.info(f"Uploading {len(files)} prompt icons to S3")
        uploaded_keys = []
        
        for file in files:
            logger.info(f"Processing file: {file.filename}")
            s3_key = f"{PROMPT_BASE_PATH}{file.filename}"
            final_key = await upload_file_to_s3(s3_key, file)
            uploaded_keys.append(final_key)
            
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": True,
                "message": "Prompt icons uploaded successfully",
                "data": {}
            }
        )
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )
        
async def get_prompt_icons(db, current_user):
    try:
        logger.info(f"Received request to fetch prompt icons BY CURRENT USER: {current_user.email}")
        s3_client = await get_s3_client()

        response = s3_client.list_objects_v2(
            Bucket=aws_bucket_name,
            Prefix=PROMPT_BASE_PATH
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