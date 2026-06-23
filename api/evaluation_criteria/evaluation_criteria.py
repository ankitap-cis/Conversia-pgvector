from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, desc, or_
from sqlalchemy.exc import SQLAlchemyError
from logger import *
from datetime import datetime as dt
from models.roleplay_models import Evaluation, EvaluationField, ScenarioSalesRep
from models.users import User
from schemas.evaluation_schema import EvaluationFieldResponse, EvaluationResponse
from fastapi import Depends
from sqlalchemy.orm import Session, aliased
from connection import get_db
from models.roleplay_models import EvaluationField, Scenario
from typing import List




async def create_eval_criteria(eval_criteria, db, current_user):
    logger.info(f"Creating evaluation criteria by admin: {current_user.email}")
    try:
        # Create Evaluation Criteria (Main Entity)
        new_criteria = Evaluation(
            title=eval_criteria.title,
            description=eval_criteria.description,
            created_by=current_user.email
        )
        db.add(new_criteria)
        db.commit()
        db.refresh(new_criteria)

        # Add Evaluation Criteria Fields (Max 8)
        criteria_fields = []
        if len(eval_criteria.fields) > 8:
            raise HTTPException(
                status_code=400,
                detail= {
                    "status": "failure",
                    "message": "You can add up to 8 criteria fields only.",
                    "data": None
                }
            )

        for field in eval_criteria.fields:
            new_field = EvaluationField(
                title_area=field.title_area,
                rating=field.rating,
                weight=field.weight,
                comment=field.comment,
                evaluation_id=new_criteria.id
            )
            db.add(new_field)
            criteria_fields.append(new_field)

        db.commit()

        logger.info(f"Evaluation Criteria created successfully by admin: {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Evaluation Criteria created successfully",
                "data": {"id": new_criteria.id}
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An exception occurred while creating Evaluation Criteria.",
                "data": None
            }
        )


async def edit_eval_criteria(criteria_id, eval_criteria, db, current_user):
    logger.info(f"Editing Evaluation Criteria ID {criteria_id} by admin: {current_user.email}")
    try:
        existing_criteria = db.query(Evaluation).filter(Evaluation.id == criteria_id).first()
        if not existing_criteria:
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "failure",
                    "message": "Evaluation Criteria not found",
                    "data": None
                }
            )

        # Update base Evaluation fields (excluding 'fields')
        if eval_criteria.title is not None:
            existing_criteria.title = eval_criteria.title

        if eval_criteria.description is not None:
            existing_criteria.description = eval_criteria.description

        existing_criteria.last_updated_by = current_user.email
        existing_criteria.last_updated_at = dt.now()

        # Update EvaluationField records
        if eval_criteria.fields is not None:
            if len(eval_criteria.fields) > 8:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "status": "failure",
                        "message": "You can add up to 8 criteria fields only.",
                        "data": None
                    }
                )

            # Delete old fields
            db.query(EvaluationField).filter(EvaluationField.evaluation_id == criteria_id).delete()

            # Add new fields (Pydantic object access)
            for field in eval_criteria.fields:
                new_field = EvaluationField(
                    title_area=field.title_area,
                    rating=field.rating,
                    weight=field.weight,
                    comment=field.comment,
                    evaluation_id=criteria_id
                )
                db.add(new_field)

        db.commit()
        logger.info(f"Evaluation Criteria ID {criteria_id} updated successfully by admin: {current_user.email}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Evaluation Criteria updated successfully",
                "data": {"id": criteria_id}
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating Evaluation Criteria: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failure",
                "message": "An error occurred while updating the Evaluation Criteria.",
                "data": None
            }
        )


async def get_all_eval_criteria(search_query, limit, offset, db, current_user):
    logger.info(f"Fetching all evaluation criteria by admin {current_user.email}")
    try:
        query = db.query(Evaluation).filter(Evaluation.is_deleted == False)

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            Creator = aliased(User)
            query = query.join(Creator, Creator.email == Evaluation.created_by).filter(Creator.organization_id == current_user.organization_id)
        
        elif current_user.user_type == "sales_reps":
            # query = query.filter(Evaluation.scenario.sales_reps.any(ScenarioSalesRep.sales_rep_id == current_user.id))
            Creator = aliased(User)
            query = query.join(Creator, Creator.email == Evaluation.created_by).filter(Creator.organization_id == current_user.organization_id)

        if search_query:
            pattern = f"%{search_query}%"
            query = query.filter(Evaluation.title.ilike(pattern))

        total = query.count()
        criteria = query.order_by(desc(Evaluation.last_updated_at)).limit(limit).offset(offset).all()

        if not criteria:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No evaluation criteria found.",
                    "data": []
                }
            )

        evaluation_data = [
            EvaluationResponse.model_validate({
                **criterion.__dict__,  # Convert SQLAlchemy model to a dictionary
                "evaluation_fields": [
                    EvaluationFieldResponse.model_validate(field.__dict__).model_dump()
                    for field in criterion.fields
                ]
            }).model_dump()
            for criterion in criteria
        ]

        logger.info(f"Evaluation Criteria fetched successfully by admin: {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Evaluation Criteria fetched successfully.",
                "data": {"content": evaluation_data, "total": total}
            }
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching evaluation criteria: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching evaluation criteria. Please try again later.",
                "data": None
            }
        )

    except HTTPException as http_exc:
        raise http_exc # Re-raise HTTPException so FastAPI handles it correctly

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


async def get_eval_criteria(criteria_id: int, db, current_user):
    logger.info(f"Fetching evaluation criteria with ID: {criteria_id} by {current_user.email}")
    try:
        criteria = db.query(Evaluation).filter(Evaluation.id == criteria_id).first()
        if not criteria:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No evaluation criteria found.",
                    "data": None
                }
            )

        evaluation_data = EvaluationResponse.model_validate({
            **criteria.__dict__,
            "evaluation_fields": [
                EvaluationFieldResponse.model_validate(field.__dict__).model_dump()
                for field in criteria.fields
            ]
        }).model_dump()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Evaluation criteria fetched successfully.",
                "data": evaluation_data
            }
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching evaluation criteria {criteria_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching evaluation criteria. Please try again later.",
                "data": None
            }
        )

    except HTTPException as http_exc:
        raise http_exc # Re-raise HTTPException for FastAPI to handle correctly

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


def get_criteria_from_db(scenario_id: int, db: Session) -> List[str]:
    # Get the evaluation_id from the scenario
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    # Get criteria from evaluation_fields using the evaluation_id
    fields = db.query(EvaluationField.title_area)\
        .filter(EvaluationField.evaluation_id == scenario.evaluation_id).all()

    if not fields:
        raise HTTPException(status_code=404, detail="No evaluation fields found")

    return [field.title_area for field in fields]


async def delete_eval_criteria(criteria_id, db, current_user):
    logger.info(f"Deleting evalution criteria having id {criteria_id} by admin {current_user.email}")
    try:
        in_use = db.query(Scenario).filter(Scenario.evaluation_id == criteria_id, Scenario.is_deleted == False).count() > 0
        if in_use:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Cannot delete: Evaluation criteria is currently used in one or more scenarios.",
                    "data": None
                }
            )
        
        Creator = aliased(User)
        eval_criteria = db.query(Evaluation).join(Creator, Creator.email == Evaluation.created_by).filter(Evaluation.id == criteria_id, Creator.organization_id == current_user.organization_id).first()
        if not eval_criteria:
            logger.warning(f"No evaluation found having id {criteria_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No evalution criteria found",
                    "data": None
                }
            )
        # 🔹 Soft delete DB record
        eval_criteria.is_deleted = True
        eval_criteria.deleted_at = dt.now()

        db.commit()

        logger.info(f"Evaluation criteria deleted successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Evaluation criteria deleted successfully",
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
                "message": "An exception occured while deleting evalution criteria",
                "data": None
            }
        )


async def get_unique_eval_title(db: Session, current_user):
    logger.info(f"Fetching unique evaluation titles by {current_user.email}")
    try:
        result = db.query(
            EvaluationField.title_area
            ).distinct().filter(
                EvaluationField.evaluation.has(Evaluation.created_by == db.query(User.email).filter(User.organization_id == current_user.organization_id, User.user_type == "org_admin").scalar_subquery())
            ).all()
        
        if not result:
            logger.info("No unique evaluation titles found.")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No unique evaluation titles found.",
                    "data": []
                }
            )
        
        titles = [row[0] for row in result]
        logger.info(f"Unique evaluation titles fetched successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Unique evaluation titles fetched successfully.",
                "data": titles
            }
        )

    except Exception as e:
        logger.error(f"Error fetching unique evaluation titles: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching unique evaluation titles.",
                "data": None
            }
        )
