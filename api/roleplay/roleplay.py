import json
from typing import Optional
from fastapi import HTTPException, Path, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, desc, or_, and_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import joinedload, aliased
from psycopg2.errors import ForeignKeyViolation
from api.roleplay_assistant.assistant import SalesEvaluator
from logger import *
from models.roleplay_models import Evaluation, Persona, Scenario, ScenarioSalesRep
from datetime import datetime as dt
from models.users import User
from schemas.roleplay_schema import AssignBulkScenarioForm, CreateScenarioWithPersona, PersonaForm, PersonaResponse, ScenarioForm, ScenarioResponse
from utils.s3_bucket_helper import delete_file_from_s3, generate_presigned_url, get_s3_client, upload_file_to_s3
from utils.utils import UPLOAD_DIR
import configparser
from pathlib import Path
from fastapi import HTTPException, status, UploadFile
from fastapi.responses import JSONResponse
from datetime import datetime as dt
import logging
from api.roleplay_assistant.rolplaybot import RolePlaybot, RolePlaybot
from api.ai_consumption.ai_token_credit import deduct_ai_credits

bot = RolePlaybot()

config = configparser.ConfigParser()
config.read('config.ini')


BASE_URL = f"http://{config['fast_api_server']['host']}:{config['fast_api_server']['port']}"

async def create_persona(persona, avatar_image, db, current_user):
    logger.info(f"Creating persona by admin: {current_user.email}")
    try:    
        file_url = ''
        if avatar_image and not isinstance(avatar_image, str):
            try:
                s3_key = f"Organizations/{current_user.organization_id}/personas/{avatar_image.filename}"
                file_url = await upload_file_to_s3(s3_key, avatar_image )
                logger.info(f"{avatar_image.filename} file updated successfully to S3")
            except Exception as e:
                logger.error(f"Failed to upload {avatar_image.filename} to S3: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_406_NOT_ACCEPTABLE,
                    detail={
                        "status": "failure",
                        "message": "Failed to upload file in S3.",
                        "data": None
                    }
                )

        new_persona = Persona(
            role = persona.role,
            thumbnail = persona.thumbnail,
            primary_goal = persona.primary_goal,
            avatar_image = file_url,
            challenges = persona.challenges,
            objections = persona.objections,
            motivations = persona.motivations,
            fears = persona.fears,
            communication_style = persona.communication_style,
            behavioral_tendencies = persona.behavioral_tendencies,
            avatar_id = persona.avatar_id,
            for_personal_use = persona.for_personal_use,
            created_at = dt.now(),
            created_by = current_user.email,
            last_updated_at = dt.now(),
            last_updated_by = current_user.email
        )
        db.add(new_persona)
        db.commit()

        logger.info(f"Persona created successfully by admin: {current_user.email}")
        return JSONResponse(
            status_code= status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Persona created successfully",
                "data": new_persona.id
            }
        )
    
    except HTTPException as http_exe:
        raise http_exe
    
    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code= status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An exception occured while creating persona.",
                "data": None
            }
        )


async def edit_persona(persona_id, persona, avatar_image, db, current_user):
    logger.info(f"Updating persona id {persona_id} by admin: {current_user.email}")
    try:
        existing_persona = db.query(Persona).filter(Persona.id == persona_id).first()
        if not existing_persona:
            raise HTTPException(
                status_code=404,
                detail={
                "status": "failure",
                "message": "Persona not found",
                "data": None
            }
        )

        # Handle S3 image update
        if avatar_image and not isinstance(avatar_image, str):

            # Delete old image from S3 if exists
            if existing_persona.avatar_image:
                deletion_successful = await delete_file_from_s3(existing_persona.avatar_image)
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

            # Upload new image
            s3_key = f"Organizations/{current_user.organization_id}/personas/{avatar_image.filename}"
            file_url = await upload_file_to_s3(s3_key, avatar_image )
            logger.info(f"{avatar_image.filename} file updated successfully to S3")
            existing_persona.avatar_image = file_url

        for field, value in persona.dict(exclude_unset=True).items():
            if value not in [None, ""]:  # Ignore None and empty string values
                setattr(existing_persona, field, value)

        existing_persona.last_updated_at = dt.now()
        existing_persona.last_updated_by = current_user.email

        db.commit()

        logger.info(f"Persona updated successfully by admin: {current_user.email}")
        return JSONResponse(
            status_code= status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Persona updated successfully",
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code= status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An exception occured while updating persona.",
                "data": None
            }
        )


async def get_personas(search_query, limit, offset, db, current_user):
    logger.info(f"Fetching all personas by {current_user.email}")
    try:
        # Base query by user type
        query = db.query(Persona).filter(Persona.is_deleted == False, Persona.for_personal_use == False)  # Exclude personal use personas by default

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            Creator = aliased(User)
            query = query.join(Creator, Creator.email == Persona.created_by).filter(Creator.organization_id == current_user.organization_id)

        elif current_user.user_type == "sales_reps":
            query = query.join(Scenario).join(ScenarioSalesRep).filter(
                ScenarioSalesRep.sales_rep_id == current_user.id
            ).options(joinedload(Persona.scenarios)).distinct()

        else:
            logger.info(f'Role is not defined')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Role is not defined.",
                    "data": None
                }
            )

        if search_query:
            pattern = f"%{search_query}%"
            query = query.filter(Persona.thumbnail.ilike(pattern))
        
        total = query.count()
        personas = query.order_by(desc(Persona.last_updated_at)).offset(offset).limit(limit).all()

        if not personas:
            logger.warning(f"No personas found for {current_user.email}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No personas found.",
                    "data": []
                }
            )

        s3_client = await get_s3_client()

        personas_data = [
            {
                **PersonaResponse.model_validate(persona).model_dump(),
                "image_url": await generate_presigned_url(s3_client, persona.avatar_image) if persona.avatar_image else None,
                "for_personal_use": persona.for_personal_use
            } for persona in personas
        ]

        return JSONResponse(
            status_code= status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Personas fetched successfully.",
                "data": {"content": personas_data, "total": total}
            }
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching personas: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching personas. Please try again later.",
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Something went wrong. Please try again later.",
                "data": None
            }
        )


async def get_persona(persona_id, db, current_user):
    logger.info(f"Fetching persona with id: {persona_id} by {current_user.email}")
    try:
        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            Creator = aliased(User)
            persona = db.query(Persona)\
                .join(Creator, Creator.email == Persona.created_by)\
                .filter(
                    Persona.id == persona_id, Persona.is_deleted == False,
                    or_(
                        Creator.organization_id == current_user.organization_id,
                        Creator.user_type == "superadmin"
                    )
                ).first()

        elif current_user.user_type == "sales_reps":
            persona = (
                db.query(Persona)
                .join(Persona.scenarios)
                .outerjoin(Scenario.sales_reps)
                .filter(Persona.id == persona_id,Persona.is_deleted == False,
                or_(
                    # Assigned sales rep
                    ScenarioSalesRep.sales_rep_id == current_user.id,

                    # Personal scenario created by same user
                    and_(
                        Persona.for_personal_use == True,
                        Persona.created_by == current_user.email
                    )
                ))
                .first()
            )


        if not persona:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No persona found.",
                    "data": []
                }
            )

        s3_client = await get_s3_client()

        persona_data = PersonaResponse.model_validate(persona).model_dump()
        persona_data["image_url"] = await generate_presigned_url(s3_client, persona.avatar_image) if persona.avatar_image else None
        persona_data["for_personal_use"] = persona.for_personal_use
        return JSONResponse(
                status_code= status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "Persona fetched successfully.",
                    "data": persona_data
                }
            )

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching persona {persona_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching persona. Please try again later.",
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Something went wrong. Please try again later.",
                "data": None
            }
        )


async def delete_persona(persona_id, db, current_user):
    logger.info(f"Deleting persona having id {persona_id} by admin {current_user.email}")
    try:
        # Check if persona is assigned to any scenario
        in_use = db.query(Scenario).filter(Scenario.persona_id == persona_id,Scenario.is_deleted == False).count() > 0
        if in_use:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Cannot delete: Persona is currently used in one or more scenarios.",
                    "data": None
                }
            )
        Creator = aliased(User)
        persona = db.query(Persona).join(Creator, Creator.email == Persona.created_by).filter(Persona.id == persona_id, Creator.organization_id == current_user.organization_id, Persona.is_deleted == False).first()
        if not persona:
            logger.warning(f"No persona found having id {persona_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No persona found",
                    "data": None
                }
            )

        if persona.avatar_image:
            deletion_successful = await delete_file_from_s3(persona.avatar_image)
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
        
        persona.is_deleted = True
        persona.deleted_at = dt.now()

        db.commit()

        logger.info(f"Persona deleted successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Persona deleted successfully",
                "data": None
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
                "message": "An exception occured while deleting persona",
                "data": None
            }
        )


async def create_scenario(scenario, scenario_image,scenario_file: UploadFile, db, current_user):
    logging.info(f"Creating scenario by admin: {current_user.email}")
    try:
        # Check if the given persona_id exists
        Creator = aliased(User)
        persona_exists = db.query(Persona).join(Creator, Creator.email == Persona.created_by).filter(Persona.id == scenario.persona_id, Creator.organization_id == current_user.organization_id).first()
        if not persona_exists:
            logger.warning(f"Persona ID {scenario.persona_id} does not exist.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": f"Persona ID {scenario.persona_id} does not exist.",
                    "data": None
                }
            )

        evaluation_exists = db.query(Evaluation).join(Creator, Creator.email == Evaluation.created_by).filter(Evaluation.id == scenario.evaluation_id, Creator.organization_id == current_user.organization_id).first()
        if not evaluation_exists:
            logger.warning(f"Evaluation ID {scenario.evaluation_id} does not exist.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": f"Evaluation ID {scenario.evaluation_id} does not exist.",
                    "data": None
                }
            )
        evaluation_titles = [field.title_area for field in evaluation_exists.fields]

        # Upload scenario image to S3
    
        file_url = ""
        if scenario_image and isinstance(scenario_image, str):
            file_url = scenario_image

        if scenario_image and not isinstance(scenario_image, str):
            try:
                s3_key = f"Organizations/{current_user.organization_id}/scenarios/images/{scenario_image.filename}"
                file_url = await upload_file_to_s3(s3_key, scenario_image)
                logger.info(f"{scenario_image.filename} uploaded successfully to S3")
            except Exception as e:
                logger.error(f"Failed to upload {scenario_image.filename} to S3: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_406_NOT_ACCEPTABLE,
                    detail={
                        "status": "failure",
                        "message": "Failed to upload file in S3.",
                        "data": None
                    }
                )

        # Upload scenario file to S3, save locally, add to vector store
        doc_url = ""
        if scenario_file and not isinstance(scenario_file, str):
            s3_key = f"Organizations/{current_user.organization_id}/scenarios/documents/{scenario_file.filename}"
            doc_url = await upload_file_to_s3(s3_key, scenario_file)

        new_scenario = Scenario(
            title = scenario.title,
            description = scenario.description,
            admin_id = current_user.id,
            scenario_image = file_url,
            scenario_file = doc_url,
            ai_trainer_opening = scenario.ai_trainer_opening,
            selling_methodology = scenario.selling_methodology,
            ideal_sales_outcome = scenario.ideal_sales_outcome,
            topics_to_cover = scenario.topics_to_cover,
            current_state = scenario.current_state,
            barriers_to_change = scenario.barriers_to_change,
            critical_questions = scenario.critical_questions,
            persona_id = scenario.persona_id,
            evaluation_id = scenario.evaluation_id,
            for_personal_use = scenario.for_personal_use,
            created_at = dt.now(),
            created_by = current_user.email,
            last_updated_at = dt.now(),
            last_updated_by = current_user.email
        )
        db.add(new_scenario)
        db.commit()
        db.refresh(new_scenario)

        if scenario_file and not isinstance(scenario_file, str):

            await scenario_file.seek(0)
            evaluator = SalesEvaluator(bot=None, evaluation_criteria=evaluation_titles)

            result = await evaluator.add_file_to_vectorstore(
                scenario_file,
                current_user.organization_id,
                new_scenario.id
            )

            usage_metadata = result.get("usage_metadata", {}) if result else {}
            total_tokens = usage_metadata.get("total_tokens", 0)

            logger.info(f"Scenario file embedding tokens: {total_tokens}")

            await deduct_ai_credits(
                db=db,
                user_id=current_user.id,
                input_tokens=total_tokens,
                output_tokens=0,
                stt_minutes=0.0,
                tts_minutes=0.0
            )

        logger.info(f"Scenario created successfully by admin: {current_user.email}")
        return JSONResponse(
            status_code= status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Scenario created successfully",
                "data": {"id": new_scenario.id}
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code= status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An exception occured while creating scenario.",
                "data": None
            }
        )


async def edit_scenario(scenario_id, scenario, scenario_image, scenario_file, db, current_user):
    logger.info(f"Updating scenario ID {scenario_id} by admin: {current_user.email}")
    try:
        existing_scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if not existing_scenario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "Scenario not found.",
                    "data": None
                }
            )

        scenario_data = scenario.dict(exclude_unset=True)

        # Check if persona_id is present in request
        if "persona_id" in scenario_data:
            new_persona_id = scenario_data["persona_id"]

            # Validate persona_id (0 is invalid)
            if not new_persona_id or new_persona_id == 0:
                logger.warning(f"Invalid persona_id: {new_persona_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failure",
                        "message": "Persona ID cannot be 0 or empty.",
                        "data": None
                    }
                )

            # Ensure persona exists
            persona_exists = db.query(Persona).filter(Persona.id == new_persona_id).first()
            if not persona_exists:
                logger.warning(f"Invalid persona_id: {new_persona_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failure",
                        "message": f"Persona ID {new_persona_id} does not exist.",
                        "data": None
                    }
                )
        Creator = aliased(User)
        evaluation_exists = db.query(Evaluation).join(Creator, Creator.email == Evaluation.created_by).filter(
            Evaluation.id == existing_scenario.evaluation_id,
            Creator.organization_id == current_user.organization_id
        ).first()

        if not evaluation_exists:
            logger.warning(f"Evaluation ID {existing_scenario.evaluation_id} does not exist.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": f"Evaluation ID {existing_scenario.evaluation_id} does not exist.",
                    "data": None
                }
            )

        evaluation_titles = [field.title_area for field in evaluation_exists.fields]
        org_id = current_user.organization_id
        evaluator = SalesEvaluator(bot=None, evaluation_criteria=evaluation_titles)

        # Handle S3 image update
        if scenario_image and not isinstance(scenario_image, str):
            # Delete old image from S3 if exists
            if existing_scenario.scenario_image:
                deletion_successful = await delete_file_from_s3(existing_scenario.scenario_image)
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

            # Upload new image
            s3_key = f"Organizations/{current_user.organization_id}/scenarios/images/{scenario_image.filename}"
            file_url = await upload_file_to_s3(s3_key, scenario_image )
            logger.info(f"{scenario_image.filename} file updated successfully to S3")
            existing_scenario.scenario_image = file_url

        # Handle S3 file update
        if scenario_file and not isinstance(scenario_file, str):
            # Delete old image from S3 if exists
            if existing_scenario.scenario_file:
                deletion_successful = await delete_file_from_s3(existing_scenario.scenario_file)
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

            s3_key = f"Organizations/{current_user.organization_id}/scenarios/documents/{scenario_file.filename}"
            doc_url = await upload_file_to_s3(s3_key, scenario_file )
            logger.info(f"{scenario_file.filename} file updated successfully to S3")
            existing_scenario.scenario_file = doc_url

            org_id = current_user.organization_id
            #editing the old scenario file in vectorstore
            result = await evaluator.add_file_to_vectorstore(
                file=scenario_file,
                org_id=org_id,
                scenario_id=scenario_id,
                replace_existing=True
            )

            usage_metadata = result.get("usage_metadata", {}) if result else {}
            total_tokens = usage_metadata.get("total_tokens", 0)

            logger.info(f"Scenario file update embedding tokens: {total_tokens}")

            await deduct_ai_credits(
                db=db,
                user_id=current_user.id,
                input_tokens=total_tokens,
                output_tokens=0,
                stt_minutes=0.0,
                tts_minutes=0.0
            )

        elif isinstance(scenario_file, str) and existing_scenario.scenario_file != None:
            if len(scenario_file) == 0:
                deletion_successful = await delete_file_from_s3(existing_scenario.scenario_file)
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
                
                existing_scenario.scenario_file = None
                await evaluator.delete_scenario_file(org_id, scenario_id)

        # Update fields dynamically, ignoring None and empty strings
        for field, value in scenario_data.items():
            if value not in [None]:  
                setattr(existing_scenario, field, value)

        existing_scenario.last_updated_at = dt.now()
        existing_scenario.last_updated_by = current_user.email

        db.commit()

        logger.info(f"Scenario updated successfully by admin: {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Scenario updated successfully",
                "data": None
            }
        )

    except IntegrityError as e:
        if isinstance(e.orig, ForeignKeyViolation):
            logger.error("Foreign key constraint failed: Invalid persona_id.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Invalid persona_id. The referenced Persona does not exist.",
                    "data": None
                }
            )

        logger.error(f"Database Integrity Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "A database error occurred while updating the scenario.",
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(f"Unexpected Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An unexpected error occurred while updating Scenario.",
                "data": None
            }
        )


async def get_scenarios(search_query, limit, offset, source, db, current_user):
    logger.info(f"Fetching scenarios by user: {current_user.email}")
    try:
        # Base query by user type
        query = db.query(Scenario).filter(Scenario.is_deleted == False)

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            Creator = aliased(User)
            query = query.join(Creator, Creator.email == Scenario.created_by)

        
            if source == "home":
                query = query.filter(
                    or_(
                        and_(
                            Scenario.for_personal_use == True,
                            Scenario.created_by == current_user.email
                        ),
                        and_(
                            Scenario.for_personal_use == False,
                            or_(
                                Creator.organization_id == current_user.organization_id,
                                Creator.user_type == "superadmin"
                            )
                        )
                    )
                )

            elif source == "settings":
                query = query.filter(
                    and_(
                        Scenario.for_personal_use == False,
                        Creator.organization_id == current_user.organization_id
                    )  
                )

        elif current_user.user_type == "sales_reps":
            query = query.filter(
                or_(
                    and_(
                        Scenario.for_personal_use == True,
                        Scenario.created_by == current_user.email
                    ),
                    and_(
                        Scenario.for_personal_use == False,
                        Scenario.sales_reps.any(ScenarioSalesRep.sales_rep_id == current_user.id)
                    )
                )
            )
        else:
            logger.info(f'Role is not defined')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Role is not defined.",
                    "data": None
                }
            )
        
        if search_query:
            ilike_pattern = f"%{search_query}%"
            query = query.filter(Scenario.title.ilike(ilike_pattern))
        
        total = query.count()
        scenarios = query.order_by(desc(Scenario.last_updated_at)).offset(offset).limit(limit).all()

        if not scenarios:
            logger.warning(f"No scenarios found for {current_user.email}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No scenarios found.",
                    "data": []
                }
            )

        s3_client = await get_s3_client()

        scenarios_data = [
            {
                **ScenarioResponse.model_validate(scenario).model_dump(),
                "image_url": await generate_presigned_url(s3_client, scenario.scenario_image) if scenario.scenario_image else None,
                "file_url":  await generate_presigned_url(s3_client, scenario.scenario_file) if scenario.scenario_file else None,
                "for_personal_use": scenario.for_personal_use
            }
            for scenario in scenarios]
        logger.info(f"Scenarios fetched successfully by user: {current_user.email}")

        return JSONResponse(
            status_code= status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Scenarios fetched successfully.",
                "data": {"content": scenarios_data, "total": total}
            }
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching personas: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching scenarios. Please try again later.",
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Something went wrong. Please try again later.",
                "data": None
            }
        )


async def get_scenario(scenario_id, db, current_user):
    logger.info(f"Fetching scenario having id {scenario_id} by user: {current_user.email}")
    try:

        # Base query by user type
        query = db.query(Scenario)

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            Creator = aliased(User)
            query = (
                query
                .join(Creator, Creator.email == Scenario.created_by)
                .filter(
                    Scenario.id == scenario_id,
                    or_(
                        and_(
                            Scenario.for_personal_use == True,
                            Scenario.created_by == current_user.email
                        ),
                        and_(
                            Scenario.for_personal_use == False,
                            or_(
                                Creator.organization_id == current_user.organization_id,
                                Creator.user_type == "superadmin"
                            )
                        )
                    )
                )
            )
        elif current_user.user_type == "sales_reps":
            query = query.filter(
                Scenario.id == scenario_id,
                or_(
                    and_(
                        Scenario.for_personal_use == True,
                        Scenario.created_by == current_user.email
                    ),
                    and_(
                        Scenario.for_personal_use == False,
                        Scenario.sales_reps.any(
                            ScenarioSalesRep.sales_rep_id == current_user.id
                        )
                    )
                )
            )

        scenario = query.first()
        if not scenario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No scenario found.",
                    "data": []
                }
            )

        s3_client = await get_s3_client()

        scenario_data = ScenarioResponse.model_validate(scenario).model_dump()
        scenario_data["image_url"] = await generate_presigned_url(s3_client, scenario.scenario_image) if scenario.scenario_image else None
        scenario_data["file_url"] = await generate_presigned_url(s3_client, scenario.scenario_file) if scenario.scenario_file else None
        scenario_data["for_personal_use"] = scenario.for_personal_use

        return JSONResponse(
                status_code= status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "Scenario fetched successfully.",
                    "data": scenario_data
                }
            )

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching persona {scenario_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching scenario. Please try again later.",
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Something went wrong. Please try again later.",
                "data": None
            }
        )


async def delete_scenario(scenario_id, db, current_user):
    logger.info(f"Deleting scenario having id {scenario_id} by admin {current_user.email}")
    try:
        Creator = aliased(User)
        scenario = db.query(Scenario).join(Creator, Creator.email == Scenario.created_by).filter(Scenario.id == scenario_id, Creator.organization_id == current_user.organization_id).first()
        if not scenario:
            logger.warning(f"No scenario found having id {scenario_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No scenario found",
                    "data": None
                }
            )

        if scenario.scenario_image and "default_samples" and "default_scenario_images" not in scenario.scenario_image.lower():
            deletion_successful = await delete_file_from_s3(scenario.scenario_image)
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

        if scenario.scenario_file:
            deletion_successful = await delete_file_from_s3(scenario.scenario_file)
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

        evaluation_exists = db.query(Evaluation).join(Creator, Creator.email == Evaluation.created_by).filter(Evaluation.id == scenario.evaluation_id, Creator.organization_id == current_user.organization_id).first()
        if not evaluation_exists:
            logger.warning(f"Evaluation ID {scenario.evaluation_id} does not exist.")
            
        if evaluation_exists and len(evaluation_exists.fields) > 0: 
            evaluation_titles = [field.title_area for field in evaluation_exists.fields]

            org_id = current_user.organization_id
            evaluator = SalesEvaluator(bot=None, evaluation_criteria=evaluation_titles)
            await evaluator.delete_scenario_file(org_id, scenario_id)

        # 🔹 Soft delete DB record
        scenario.is_deleted = True
        scenario.deleted_at = dt.now()

        db.commit()

        logger.info(f"Scenario deleted successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Scenario deleted successfully",
                "data": None
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
                "message": "An exception occured while deleting scenario",
                "data": None
            }
        )

async def delete_persona_scenario(scenario_id, db, current_user):
    logger.info(f"Deleting persona scenario having id {scenario_id} by admin {current_user.email}")
    try:
        scenario = db.query(Scenario).filter(Scenario.id == scenario_id, Scenario.for_personal_use == True, Scenario.created_by == current_user.email).first()
        if not scenario:
            logger.warning(f"No persona scenario found having id {scenario_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No persona scenario found",
                    "data": None
                }
            )
        logger.info(f"Persona scenario found having id {scenario_id}, proceeding to delete.")
        persona_id = scenario.persona_id
        await delete_scenario(scenario.id, db, current_user)

        # Check if persona is used in any other scenario
        in_use = db.query(Scenario).filter(Scenario.persona_id == persona_id, Scenario.is_deleted == False).count() > 0
        if not in_use:
            logger.info(f"Persona with id {persona_id} is not used in any other scenario, proceeding to delete persona.")
            await delete_persona(persona_id, db, current_user)
        else:
            logger.info(f"Persona with id {persona_id} is still used in other scenarios, skipping persona deletion.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Persona scenario deleted successfully",
                "data": None
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
                "message": "An exception occured while deleting persona scenario",
                "data": None
            }
        )
    
async def assign_scenario(scenario_assignment, db, current_user):
    logger.info(f"Assigning scenario {scenario_assignment.scenario_id} to users by admin {current_user.email}")

    # Check if Scenario exists
    scenario = db.query(Scenario).filter(Scenario.id == scenario_assignment.scenario_id).first()
    if not scenario:
        logger.error("Scenario not found.")
        raise HTTPException(
            status_code=404, 
            detail={
                "status": "failure",
                "message": "Scenario not found.",
                "data": None
            }
        )

    # Check if User exists
    users = db.query(User).filter(User.id.in_(scenario_assignment.sales_rep_ids)).all()
    existing_user_ids = {user.id for user in users}

    # Identify invalid user IDs
    invalid_user_ids = set(scenario_assignment.sales_rep_ids) - existing_user_ids
    if invalid_user_ids:
        logger.error(f"Users not found: {invalid_user_ids}")
        raise HTTPException(
            status_code=404,
            detail={
                "status": "failure",
                "message": f"Users not found: {list(invalid_user_ids)}",
                "data": None
            }
        )

    # Check if already assigned
    existing_assignments = db.query(ScenarioSalesRep).filter(
        ScenarioSalesRep.scenario_id == scenario_assignment.scenario_id,
        ScenarioSalesRep.sales_rep_id.in_(scenario_assignment.sales_rep_ids)
    ).all()
    already_assigned_ids = {assignment.sales_rep_id for assignment in existing_assignments}
    logger.warning(f"Users {already_assigned_ids} are already assigned to scenario {scenario_assignment.scenario_id}")

    # Prepare new assignments
    new_assignments = [
        ScenarioSalesRep(
            scenario_id=scenario_assignment.scenario_id, 
            sales_rep_id=user_id, 
            assigned_by=current_user.id
        )
        for user_id in scenario_assignment.sales_rep_ids if user_id not in already_assigned_ids
    ]

    # Insert new assignments
    if new_assignments:
        db.bulk_save_objects(new_assignments)
        db.commit()
    
    logger.info(f"Scenario assigned to users{list(set(scenario_assignment.sales_rep_ids) - already_assigned_ids)} by admin {current_user.email}")
    return JSONResponse(
        status_code= status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Scenario assigned successfully",
            "data": {
                "scenario_id": scenario_assignment.scenario_id,
                "assigned_users": list(set(scenario_assignment.sales_rep_ids) - already_assigned_ids),
                "already_assigned_users": list(already_assigned_ids)
            }
        }
    )


async def assign_bulk_scenario(user_id, scenario_form, db, current_user):
    logger.info(f"Assigning scenarios having ids {scenario_form.scenario_ids} to user by admin {current_user.email}")

    # Check if User exists
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error("User not found.")
        raise HTTPException(
            status_code=404, 
            detail={
                "status": "failure",
                "message": "User not found.",
                "data": None
            }
        )

    # Check if Scenario exists
    scenarios = db.query(Scenario).filter(Scenario.id.in_(scenario_form.scenario_ids)).all()
    existing_scenario_ids = {scenario.id for scenario in scenarios}

    # Identify invalid scenario IDs
    invalid_scenario_ids = set(scenario_form.scenario_ids) - existing_scenario_ids
    if invalid_scenario_ids:
        logger.error(f"Scenarios not found: {invalid_scenario_ids}")
        raise HTTPException(
            status_code=404,
            detail={
                "status": "failure",
                "message": f"Scenarios not found: {list(invalid_scenario_ids)}",
                "data": None
            }
        )

    # Check if already assigned
    existing_assignments = db.query(ScenarioSalesRep).filter(
        ScenarioSalesRep.sales_rep_id == user_id,
        ScenarioSalesRep.scenario_id.in_(scenario_form.scenario_ids)
    ).all()

    already_assigned_ids = {assignment.scenario_id for assignment in existing_assignments}
    logger.warning(f"Scenarios {already_assigned_ids} are already assigned to user {user_id}")

    # Prepare new assignments
    new_assignments = [
        ScenarioSalesRep(
            scenario_id=scenario_id, 
            sales_rep_id=user_id, 
            assigned_by=current_user.id
        )
        for scenario_id in scenario_form.scenario_ids if scenario_id not in already_assigned_ids
    ]

    # Insert new assignments
    if new_assignments:
        db.bulk_save_objects(new_assignments)
        db.commit()
    
    logger.info(f"Scenarios {list(set(scenario_form.scenario_ids) - already_assigned_ids)} assigned to user by admin {current_user.email}")
    return JSONResponse(
        status_code= status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Scenario assigned successfully",
            "data": {
                "assigned_scenarios": list(set(scenario_form.scenario_ids) - already_assigned_ids),
                "user_id": user_id,
                "already_assigned_scenarios": list(already_assigned_ids)
            }
        }
    )


async def fetch_assigned_scenarios(user_id, db, current_user):
    logger.info(f"Fetching assigned scenarios list to user id {user_id} by {current_user.email}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error("User not found.")
        raise HTTPException(
            status_code=404, 
            detail={
                "status": "failure",
                "message": "User not found.",
                "data": None
            }
        )

    scenarios = (
        db.query(Scenario)
        .join(ScenarioSalesRep, Scenario.id == ScenarioSalesRep.scenario_id)
        .filter(ScenarioSalesRep.sales_rep_id == user_id).filter(Scenario.is_deleted == False)
        .order_by(desc(ScenarioSalesRep.last_updated_at))
        .all()
    )

    if not scenarios:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "No scenarios found.",
                "data": []
            }
        )

    s3_client = await get_s3_client()

    scenarios_data = [
        # ScenarioResponse.model_validate(scenario).model_dump() 
        {
            **ScenarioResponse.model_validate(scenario).model_dump(),
            "image_url": await generate_presigned_url(s3_client, scenario.scenario_image) if scenario.scenario_image else None
        }
        for scenario in scenarios]
    logger.info(f"Scenarios fetched successfully by user: {current_user.email}")

    return JSONResponse(
        status_code= status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Scenarios fetched successfully.",
            "data": scenarios_data
        }
    )


async def remove_user_scenario(user_id, scenario_id, db, current_user):
    logger.info(f"Removing scenario having id: {scenario_id} from sales rep having id: {user_id} by admin {current_user.email}")
   
    # Check if assignment exists
    assignment = db.query(ScenarioSalesRep).filter(ScenarioSalesRep.sales_rep_id == user_id, ScenarioSalesRep.scenario_id == scenario_id).first()
    if not assignment:
        logger.error("No assigned scenario found for user with id: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "failure",
                "message": "No scenario assignment found",
                "data": None
            }
        )

    db.delete(assignment)
    db.commit()

    logger.info(f"Scenario {scenario_id} removed from user {user_id} successfully by admin {current_user.email}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Scenario removed  successfully.",
            "data": {
                "scenario_id": scenario_id,
                "user_id": user_id
            }
        }
    )

async def remove_user_scenarios_bulk(user_id, db, current_user):
    logger.info(f"Removing scenarios in bulk for user {user_id} by orgadmin {current_user.email}")

    scenario_list = (
        db.query(Scenario.id)
        .join(ScenarioSalesRep, Scenario.id == ScenarioSalesRep.scenario_id)
        .filter(ScenarioSalesRep.sales_rep_id == user_id)
        .all()
    )
    if scenario_list:
        scenario_ids = [row[0] for row in scenario_list]
        db.execute(
            delete(ScenarioSalesRep).where(
                ScenarioSalesRep.sales_rep_id == user_id,
                ScenarioSalesRep.scenario_id.in_(scenario_ids)
            )
        )

    logger.info(f"Scenarios in bulk for user {user_id} removed by orgadmin {current_user.email} successfully")


async def create_ai_scenario(scenario_persona_data, avatar_image, scenario_image, scenario_file,evaluation_id, db, current_user):
    try:
        logger.info(f"Creating AI scenario by user: {current_user.email}")
        parsed_json = json.loads(scenario_persona_data)

        raw_persona = parsed_json["data"].get("persona", {})
        raw_scenario = parsed_json["data"].get("scenario", {})

        persona_form = PersonaForm(**raw_persona, avatar_id=avatar_image, for_personal_use=True)

        avatar_image = avatar_image if avatar_image else "avatar"

        result = await create_persona(persona_form, avatar_image,db, current_user)
        logger.info(f"Persona created successfully for AI scenario by user: {current_user.email}")

        response_dict = json.loads(result.body)
        persona_id = response_dict.get("data")

        # Creator = aliased(User)
        # evaluation = db.query(Evaluation).join(Creator, Creator.email == Evaluation.created_by).filter(Creator.organization_id == current_user.organization_id).first()
        # evaluation_id = evaluation.id if evaluation else None

        scenario_form = ScenarioForm(**raw_scenario, persona_id=persona_id, evaluation_id = evaluation_id, for_personal_use=True)

        created_scenario = await create_scenario(
            scenario_form,
            scenario_image,
            scenario_file,
            db,
            current_user
        )

        return JSONResponse(
            status_code= status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "AI Scenario created successfully",
                "data": None
            }
        )

    except Exception as e:
        logger.error(f"Error in create_ai_scenario: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while creating AI scenario. Please try again later.",
                "data": None
            }
        )