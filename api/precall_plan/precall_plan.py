from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from logger import *
from models.precall_plan_models import PreCallPlanForm, PreCallPlanFormField
from models.users import User, Organization
from schemas.precall_plan_schema import PrecallPlanFieldResponse, PrecallPlanResponse
import configparser
from langchain_openai import OpenAIEmbeddings
from utils.s3_bucket_helper import delete_file_from_s3, upload_file_to_s3
from api.roleplay_assistant.constants import add_file_to_vectorstore, clear_faiss_vectorstore
from langchain_openai import OpenAIEmbeddings
import configparser
from sqlalchemy.orm import aliased
 

config = configparser.ConfigParser()
config.read('config.ini')
OPENAI_API_KEY = config['openAI_config']['key']
embed_model = config['openAI_config']['embedding_model']
 

embedding_model = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY, model= embed_model)


async def precall_plan_form(form, file, db, current_user):
    logger.info(f"Creating or updating precall plan form by admin: {current_user.email}")

    try:
        doc_url = None
        existing_form = db.query(PreCallPlanForm).filter(PreCallPlanForm.admin_id == current_user.id).first()

        if current_user.user_type == "org_admin":
            organization = db.query(Organization).filter(Organization.admin_id == current_user.id).first()  

        if file and not isinstance(file, str):
            try:
                s3_key = f"Organizations/{current_user.organization_id}/precallplan/{file.filename}"
                doc_url = await upload_file_to_s3(s3_key, file )
                logger.info(f"{file.filename} file updated successfully to S3")

                file.file.seek(0)                 
                await add_file_to_vectorstore(file, org_id=organization.id)

            except Exception as e:
                logger.error(f"Failed to upload {file.filename} to S3: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_406_NOT_ACCEPTABLE,
                    detail={
                        "status": "failure",
                        "message": "Failed to upload file in S3.",
                        "data": None
                    }
                )

        elif isinstance(file, str) and existing_form and existing_form.file_path != None:
            if len(file) == 0:
                deletion_successful = await delete_file_from_s3(existing_form.file_path)
                success = clear_faiss_vectorstore("precall_plan", embedding_model=embedding_model, org_id=organization.id)

                if success:
                    logger.info("FAISS vector store cleared.")
                else:
                    logger.info("Vector store was already empty.")


                if not deletion_successful:
                    logger.error("S3 deletion failed. Aborting DB delete.")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "status": "failure",
                            "message": "S3 file deletion failed. DB record not deleted.",
                            "data": None
                        }
                    )
                
                existing_form.file_path = None

        # Check if form already exists for this admin
        if existing_form:
            db.query(PreCallPlanFormField).filter(PreCallPlanFormField.form_id == existing_form.id).delete()

            # Update timestamps
            if doc_url:
                existing_form.file_path = doc_url
            existing_form.last_updated_at = dt.now()
            new_form = existing_form

        else:
            new_form = PreCallPlanForm(admin_id = current_user.id, file_path = doc_url)
            db.add(new_form)
            db.commit()
            db.refresh(new_form)

        for field in form.fields:
            db.add(PreCallPlanFormField(
                form_id = new_form.id,
                field_name = field.field_name,
                field_type = field.field_type,
                is_required = field.is_required,
                order_index = field.order_index
            ))

        db.commit()
        db.refresh(new_form)

        logger.info(f"Precall Plan Form created/updated successfully by admin: {current_user.email}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Precall Plan created/updated successfully.",
                "data": {"id": new_form.id}
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error while creating/updating Precall Plan: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to create/update Precall Plan Form.",
                "data": None
            }
        )


async def get_precall_plan_form(db, current_user):
    logger.info(f"Fetching precall plan form by user: {current_user.email}")
    try:
        if not current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Organization not found for user",
                    "data": None
                }
            )

        Creator = aliased(User)
        form = (
            db.query(PreCallPlanForm).join(Creator, Creator.id == PreCallPlanForm.admin_id)
            .filter(
                Creator.organization_id == current_user.organization_id
            )
            .first()
        )

        if not form:
            logger.error(f"No precall plan found for user: {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No precall plan found",
                    "data": None
                }
            )

        form_data = PrecallPlanResponse.model_validate({
                **form.__dict__,
                "file_url": form.file_path if form.file_path else None,
                "precall_plan_fields": [
                    PrecallPlanFieldResponse.model_validate(field.__dict__).model_dump()
                    for field in form.precall_plan_form_field
                ]
            }).model_dump()

        logger.info(f"Precall plan fetched successfully by user: {current_user.email}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Precall plan fetched successfully",
                "data": form_data
            }
        )
    except HTTPException as http_exe:
        raise http_exe

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to fetch Precall Plan Form.",
                "data": None
            }
        )
