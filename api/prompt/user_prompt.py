from typing import Optional
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import asc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from logger import *
from models.prompt_models import PromptUser, PromptCategoryEnum
from models.users import User
from schemas.prompt_schema import (
    UpdateUserPromptForm
)


async def update_user_prompt(
    prompt_id: int, prompt_data: UpdateUserPromptForm, db: Session, current_user: User
):
    logger.info(f"Updating user prompt ID {prompt_id} by user: {current_user.email}")

    try:
        prompt = db.query(PromptUser).filter(
            PromptUser.id == prompt_id,
            PromptUser.user_id == current_user.id,
        ).first()

        if not prompt:
            logger.warning(f"User prompt with ID {prompt_id} not found for user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User prompt with ID {prompt_id} not found",
            )

        if prompt.is_deleted:
            logger.warning(f"Cannot update deleted user prompt with ID {prompt_id}")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Cannot update a deleted prompt",
            )

        # Check for duplicate title if title is being updated
        if prompt_data.title and prompt_data.title != prompt.title:
            existing_prompt = db.query(PromptUser).filter(
                PromptUser.user_id == current_user.id,
                PromptUser.title == prompt_data.title,
                PromptUser.is_deleted == False,
                PromptUser.id != prompt_id,
            ).first()

            if existing_prompt:
                logger.warning(f"User prompt with title '{prompt_data.title}' already exists")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Prompt with title '{prompt_data.title}' already exists",
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

        db.commit()
        db.refresh(prompt)

        logger.info(f"User prompt {prompt_id} updated successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "User prompt updated successfully",
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
        logger.error(f"HTTP Exception while updating user prompt: {http_exc.detail}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "status": "failure",
                "message": http_exc.detail,
                "data": None
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error while updating user prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user prompt: {str(e)}",
        )


async def get_user_prompts(
    search_query: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    db: Session = None,
    current_user: User = None,
):
    logger.info(f"Fetching user prompts by user: {current_user.email}")

    try:
        query = db.query(PromptUser).filter(
            PromptUser.user_id == current_user.id,
            PromptUser.is_deleted == False,
        )

        # Search by title or description
        if search_query:
            query = query.filter(
                (PromptUser.title.ilike(f"%{search_query}%"))
                | (PromptUser.description.ilike(f"%{search_query}%"))
            )

        # Filter by category
        if category:
            try:
                category_enum = PromptCategoryEnum[category.upper()]
                query = query.filter(PromptUser.category == category_enum)
            except KeyError:
                logger.warning(f"Invalid category: {category}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid category. Must be one of: {', '.join([c for c in PromptCategoryEnum])}",
                )

        # Get total count
        total_count = query.count()

        # Apply ordering and pagination
        prompts = (
            query.order_by(asc(PromptUser.id))
            .offset(offset)
            .limit(limit)
            .all()
        )

        logger.info(f"Retrieved {len(prompts)} user prompts")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "User prompts retrieved successfully",
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
        logger.error(f"Database error while fetching user prompts: {str(db_exc)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user prompts from database",
        )

    except Exception as e:
        logger.error(f"Unexpected error while fetching user prompts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch user prompts: {str(e)}",
        )


async def get_user_prompt(prompt_id: int, db: Session, current_user: User):
    logger.info(f"Fetching user prompt ID {prompt_id} by user: {current_user.email}")

    try:
        prompt = db.query(PromptUser).filter(
            PromptUser.id == prompt_id,
            PromptUser.user_id == current_user.id,
            PromptUser.is_deleted == False,
        ).first()

        if not prompt:
            logger.warning(f"User prompt with ID {prompt_id} not found for user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User prompt with ID {prompt_id} not found",
            )

        logger.info(f"User prompt {prompt_id} retrieved successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "User prompt retrieved successfully",
                "data": {
                    "id": prompt.id,
                    "user_id": prompt.user_id,
                    "category": prompt.category,
                    "title": prompt.title,
                    "description": prompt.description,
                    "prompt_content": prompt.prompt_content,
                    "icon": prompt.icon,
                },
            },
        )

    except HTTPException as http_exc:
        raise http_exc

    except SQLAlchemyError as db_exc:
        logger.error(f"Database error while fetching user prompt: {str(db_exc)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user prompt from database",
        )

    except Exception as e:
        logger.error(f"Unexpected error while fetching user prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch user prompt: {str(e)}",
        )


async def delete_user_prompt(prompt_id: int, db: Session, current_user: User):
    logger.info(f"Deleting user prompt ID {prompt_id} by user: {current_user.email}")

    try:
        prompt = db.query(PromptUser).filter(
            PromptUser.id == prompt_id,
            PromptUser.user_id == current_user.id,
        ).first()

        if not prompt:
            logger.warning(f"User prompt with ID {prompt_id} not found for user {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User prompt with ID {prompt_id} not found",
            )

        if prompt.is_deleted:
            logger.warning(f"User prompt with ID {prompt_id} is already deleted")
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Prompt is already deleted",
            )

        # Soft delete
        prompt.is_deleted = True

        db.commit()

        logger.info(f"User prompt {prompt_id} deleted successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "User prompt deleted successfully",
                "data": {"id": prompt_id},
            },
        )

    except HTTPException as http_exc:
        logger.error(f"HTTP Exception while deleting user prompt: {http_exc.detail}")
        raise http_exc

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error while deleting user prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user prompt: {str(e)}",
        )
