from datetime import datetime
from typing import Optional
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import asc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from logger import *
from models.prompt_models import PromptMaster, PromptCategoryEnum, PromptUser
from models.users import User


async def create_prompt_master(prompt_data, db, current_user):
    logger.info(f"Creating prompt master: {prompt_data.title} by superadmin: {current_user.email}")

    try:
        # Check if prompt with same title and category already exists
        existing_prompt = db.query(PromptMaster).filter(
            PromptMaster.title == prompt_data.title,
            PromptMaster.category == prompt_data.category,
            PromptMaster.is_deleted == False,
        ).first()

        if existing_prompt:
            logger.warning(f"Prompt with title '{prompt_data.title}' already exists")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "status": "failure",
                    "message": f"Prompt with title '{prompt_data.title}' in category '{prompt_data.category}' already exists",
                    "data": None
                }
            )

        # Create new prompt master
        new_prompt = PromptMaster(
            category=prompt_data.category,
            title=prompt_data.title,
            description=prompt_data.description,
            prompt_content=prompt_data.prompt_content,
            icon=prompt_data.icon,
            created_by=current_user.id,
            last_updated_by=current_user.id,
        )

        db.add(new_prompt)
        db.commit()
        db.refresh(new_prompt)

        logger.info(f"Prompt master created successfully with ID: {new_prompt.id}")
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Prompt master created successfully",
                "data": {
                    "id": new_prompt.id
                }
            }
        )

    except HTTPException as http_exc:
        logger.error(f"HTTP Exception while creating prompt: {http_exc.detail}")
        raise http_exc

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error while creating prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": f"Failed to create prompt: {str(e)}",
                "data": None
            }
        )


async def update_prompt_master(prompt_id, prompt_data, db, current_user):
    logger.info(f"Updating prompt master ID {prompt_id} by superadmin: {current_user.email}")

    try:
        prompt = db.query(PromptMaster).filter(PromptMaster.id == prompt_id).first()

        if not prompt:
            logger.warning(f"Prompt master with ID {prompt_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"Prompt master with ID {prompt_id} not found",
                    "data": None
                }
            )


        # Check for duplicate title if title is being updated
        if prompt_data.title and prompt_data.title != prompt.title:
            existing_prompt = db.query(PromptMaster).filter(
                PromptMaster.title == prompt_data.title,
                PromptMaster.category == (prompt_data.category or prompt.category),
                PromptMaster.is_deleted == False,
                PromptMaster.id != prompt_id,
            ).first()

            if existing_prompt:
                logger.warning(f"Prompt with title '{prompt_data.title}' already exists")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "status": "failure",
                        "message": f"Prompt with title '{prompt_data.title}' already exists",
                        "data": None
                    }
                )

        # Update fields
        if prompt_data.category:
            prompt.category = prompt_data.category
        if prompt_data.title:
            prompt.title = prompt_data.title
        if prompt_data.description is not None:
            prompt.description = prompt_data.description
        if prompt_data.prompt_content:
            prompt.prompt_content = prompt_data.prompt_content
        if prompt_data.icon:
            prompt.icon = prompt_data.icon

        prompt.last_updated_by = current_user.id

        db.commit()
        db.refresh(prompt)

        logger.info(f"Prompt master {prompt_id} updated successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Prompt master updated successfully",
                "data": {
                    "id": prompt.id,
                    "category": prompt.category,
                    "title": prompt.title,
                    "description": prompt.description,
                    "prompt_content": prompt.prompt_content,
                },
            },
        )

    except HTTPException as http_exc:
        logger.error(f"HTTP Exception while updating prompt: {http_exc.detail}")
        raise http_exc

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error while updating prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": f"Failed to update prompt: {str(e)}",
                "data": None
            }
        )


async def get_prompt_masters(
    search_query: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    db: Session = None,
    current_user: User = None,
):
    logger.info(f"Fetching prompt masters by superadmin: {current_user.email}")

    try:
        query = db.query(PromptMaster).filter(PromptMaster.is_deleted == False)

        # Search by title or description
        if search_query:
            query = query.filter(
                (PromptMaster.title.ilike(f"%{search_query}%"))
                | (PromptMaster.description.ilike(f"%{search_query}%"))
            )

        # Filter by category
        if category:
            try:
                category_enum = PromptCategoryEnum[category.upper()]
                query = query.filter(PromptMaster.category == category_enum)
            except KeyError:
                logger.warning(f"Invalid category: {category}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "failure",
                        "message": f"Invalid category. Must be one of: {', '.join([c for c in PromptCategoryEnum])}",
                        "data": None
                    }
                )

        # Get total count
        total_count = query.count()

        # Apply ordering and pagination
        prompts = (
            query.order_by(asc(PromptMaster.id))
            .offset(offset)
            .limit(limit)
            .all()
        )

        logger.info(f"Retrieved {len(prompts)} prompt masters")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Prompt masters retrieved successfully",
                "data": [
                    {
                        "id": p.id,
                        "category": p.category,
                        "title": p.title,
                        "description": p.description,
                        "prompt_content": p.prompt_content,
                        "icon": p.icon
                    }
                    for p in prompts
                ],
                "pagination": {
                    "total_count": total_count,
                    "limit": limit,
                    "offset": offset,
                    "returned_count": len(prompts),
                },
            },
        )

    except HTTPException as http_exc:
        raise http_exc

    except SQLAlchemyError as db_exc:
        logger.error(f"Database error while fetching prompts: {str(db_exc)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to retrieve prompts from database",
                "data": None
            }
        )

    except Exception as e:
        logger.error(f"Unexpected error while fetching prompts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": f"Failed to fetch prompts: {str(e)}",
                "data": None
            }
        )


async def get_prompt_master(prompt_id: int, db: Session, current_user: User):
    logger.info(f"Fetching prompt master ID {prompt_id} by superadmin: {current_user.email}")

    try:
        prompt = db.query(PromptMaster).filter(
            PromptMaster.id == prompt_id,
            PromptMaster.is_deleted == False,
        ).first()

        if not prompt:
            logger.warning(f"Prompt master with ID {prompt_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"Prompt master with ID {prompt_id} not found",
                    "data": None
                }
            )

        logger.info(f"Prompt master {prompt_id} retrieved successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Prompt master retrieved successfully",
                "data": {
                    "id": prompt.id,
                    "category": prompt.category,
                    "title": prompt.title,
                    "description": prompt.description,
                    "prompt_content": prompt.prompt_content,
                    "icon": prompt.icon
                },
            },
        )

    except HTTPException as http_exc:
        raise http_exc

    except SQLAlchemyError as db_exc:
        logger.error(f"Database error while fetching prompt: {str(db_exc)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to retrieve prompt from database",
                "data": None
            }
        )

    except Exception as e:
        logger.error(f"Unexpected error while fetching prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": f"Failed to fetch prompt: {str(e)}",
                "data": None
            }
        )


async def delete_prompt_master(prompt_id: int, db: Session, current_user: User):
    logger.info(f"Deleting prompt master ID {prompt_id} by superadmin: {current_user.email}")

    try:
        prompt = db.query(PromptMaster).filter(PromptMaster.id == prompt_id).first()

        if not prompt:
            logger.warning(f"Prompt master with ID {prompt_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"Prompt master with ID {prompt_id} not found",
                    "data": None
                }
            )

        if prompt.is_deleted:
            logger.warning(f"Prompt master with ID {prompt_id} is already deleted")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={
                    "status": "failure",
                    "message": "Prompt is already deleted",
                    "data": None
                }
            )

        # Soft delete
        prompt.is_deleted = True
        prompt.deleted_at = datetime.utcnow()

        db.commit()

        logger.info(f"Prompt master {prompt_id} deleted successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Prompt master deleted successfully",
                "data": {"id": prompt_id},
            },
        )

    except HTTPException as http_exc:
        logger.error(f"HTTP Exception while deleting prompt: {http_exc.detail}")
        raise http_exc

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error while deleting prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": f"Failed to delete prompt: {str(e)}",
                "data": None
            }
        )


async def copy_master_prompts_to_user(
    db: Session,
    current_user
):
    logger.info(f"Copying master prompts to user: {current_user.email}")

    try:
        master_prompts = db.query(PromptMaster).filter(
            PromptMaster.is_deleted == False
        ).all()

        if not master_prompts:
            logger.warning("No master prompts found to copy.")
            return 0

        user_prompts = [
            PromptUser(
                user_id=current_user.id,
                category=prompt.category,
                title=prompt.title,
                description=prompt.description,
                prompt_content=prompt.prompt_content,
                icon=prompt.icon,
                created_by=current_user.email,
                last_updated_by=current_user.email
            )
            for prompt in master_prompts
        ]

        db.bulk_save_objects(user_prompts)

        logger.info(
            f"Successfully copied {len(user_prompts)} prompts "
            f"to user ID: {current_user.id}"
        )

        return len(user_prompts)

    except SQLAlchemyError as e:
        logger.error(
            f"Database error while copying prompts: {str(e)}"
        )
        raise e

    except Exception as e:
        logger.error(
            f"Unexpected error while copying prompts: {str(e)}"
        )
        raise e
