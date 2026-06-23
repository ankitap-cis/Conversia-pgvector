import asyncio
import configparser
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, desc, or_
from sqlalchemy.orm import aliased
from logger import *
from models.courses_models import Course, CourseSalesRep
from models.users import User, Organization
from schemas.course_schema import AssignBulkCoursesForm, CourseResponse
from utils.s3_bucket_helper import delete_file_from_s3, generate_presigned_url, get_s3_client, upload_file_to_s3
from api.roleplay_assistant.features.course_services import course_chatbot
import re
from datetime import datetime
from openai import AsyncOpenAI
from api.ai_consumption.ai_token_credit import deduct_ai_credits


config = configparser.ConfigParser()
config.read('config.ini')
OPENAI_API_KEY = config['openAI_config']['key']
model = config['openAI_config']['model']

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def create_course(course_data, course_image, course_file, db, current_user):
    logger.info(f"Creating course with title: {course_data.title} by admin: {current_user.email}")
    try:
        if course_image and not isinstance(course_image, str):
            s3_key = f"Organizations/{current_user.organization_id}/courses/images/{course_image.filename}"
            course_image_s3_key = await upload_file_to_s3(s3_key, course_image)

        if course_file and not isinstance(course_file, str):
            file_s3_key = f"Organizations/{current_user.organization_id}/courses/files/{course_file.filename}"
            course_file_s3_key = await upload_file_to_s3(file_s3_key, course_file)

        # Create a new course instance
        new_course = Course(
            title=course_data.title,
            audience=course_data.audience,
            description=course_data.description,
            additional_info=course_data.additional_info,
            image_url=course_image_s3_key if course_image else None,
            course_file_url=course_file_s3_key if course_file else None,
            instructor_id=current_user.id,
            created_by=current_user.id,
            last_updated_by=current_user.id
        )

        db.add(new_course)
        db.commit()
        db.refresh(new_course)

        s3_client = await get_s3_client()
        file_path = await generate_presigned_url(s3_client,course_file_s3_key)
        result = await course_chatbot.add_course_document_async(
            course_title=new_course.title,
            course_id=new_course.id,
            org_id=current_user.organization_id,
            file_path=file_path,
        )

        response, token_usage= await course_chatbot.generate_course_summary_async(
            course_id=new_course.id,
            org_id=current_user.organization_id
        )

        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=token_usage['input_tokens'] if token_usage else 0,
            output_tokens=token_usage['output_tokens'] if token_usage else 0,
            stt_minutes=0.0,
            tts_minutes=0.0
        )

        new_course.course_summary = response
        db.add(new_course)
        db.commit()
        db.refresh(new_course)

        if result["success"]:
            logger.info(f"Course content added to vectorstore: {result}")
        else:
            logger.warning(f"Failed to add course content to vectorstore: {result}")

        logger.info(f"Course created successfully: {new_course.title}")
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Course created successfully",
                "data": {"course_id": new_course.id}
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error creating course: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to create course",
                "data": None
            }
        )


async def update_course(course_id, course_data, course_image, course_file, db, current_user):
    logger.info(f"Updating course with ID: {course_id} by admin: {current_user.email}")
    try:
        Creator = aliased(User)
        course = db.query(Course).join(Creator, Creator.id == Course.created_by).filter(Course.id == course_id, Creator.organization_id == current_user.organization_id).first()
        if not course:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "Course not found",
                    "data": None
                }
            )

        if course_image and not isinstance(course_image, str):
            s3_key = f"Organizations/{current_user.organization_id}/courses/images/{course_image.filename}"
            course.image_url = await upload_file_to_s3(s3_key, course_image)

        if course_file and not isinstance(course_file, str):
            course_chatbot.delete_course_content(course_id=course.id, org_id=current_user.organization_id)
            file_s3_key = f"Organizations/{current_user.organization_id}/courses/files/{course_file.filename}"
            course.course_file_url = await upload_file_to_s3(file_s3_key, course_file)


            s3_client = await get_s3_client()
            file_path = await generate_presigned_url(s3_client, course.course_file_url)
            result = await course_chatbot.add_course_document_async(
                course_title=course.title,
                course_id=course.id,
                org_id=current_user.organization_id,
                file_path=file_path,
            )

            if result["success"]:
                logger.info(f"Course document updated to vectorstore: {result}")
            else:
                logger.warning(f"Failed to updated course document to vectorstore: {result}")

        # Update course fields
        course.title = course_data.title or course.title
        course.audience = course_data.audience or course.audience
        course.description = course_data.description or course.description
        course.additional_info = course_data.additional_info or course.additional_info
        course.last_updated_by = current_user.id

        response, token_usage= await course_chatbot.generate_course_summary_async(
            course_id=course.id,
            org_id=current_user.organization_id
        )

        await deduct_ai_credits(
            db=db,
            user_id=current_user.id,
            input_tokens=token_usage['input_tokens'] if token_usage else 0,
            output_tokens=token_usage['output_tokens'] if token_usage else 0,
            stt_minutes=0.0,
            tts_minutes=0.0
        )

        course.course_summary = response

        db.add(course)
        db.commit()
        db.refresh(course)
        logger.info(f"Course updated successfully: {course.title}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Course updated successfully",
                "data": {"course_id": course.id}
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error updating course: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to update course",
                "data": None
            }
        )


async def get_courses(search_query, limit, offset, source, db, current_user):
    logger.info(f"Fetching courses by admin: {current_user.email}")
    try:
        # Base query
        query = db.query(Course).filter(Course.is_deleted == False)

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            Creator = aliased(User)
            query = query.join(Creator, Creator.id == Course.created_by)

            # HOME → include superadmin
            if source == "home":
                query = query.filter(
                    or_(
                        Creator.organization_id == current_user.organization_id,
                        Creator.user_type == "superadmin"
                    )
                )

            # SETTINGS → only org scenarios
            elif source == "settings":
                query = query.filter(
                    Creator.organization_id == current_user.organization_id
                )

        elif current_user.user_type == "sales_reps":
            query = query.join(CourseSalesRep).filter(
                CourseSalesRep.sales_rep_id == current_user.id
            )

        if search_query:
            query = query.filter(
                Course.title.ilike(f"%{search_query}%")
            )
        
        total_courses = query.count()
        courses = query.order_by(desc(Course.last_updated_at)).offset(offset).limit(limit).all()

        if not courses:
            logger.warning("No courses found")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No courses found",
                    "data": None
                }
            )
        s3_client = await get_s3_client()
        course_data = [
            {
                **CourseResponse.model_validate(course).model_dump(),
                "image_url": await generate_presigned_url(s3_client, course.image_url) if course.image_url else None,
                "course_file_url": await generate_presigned_url(s3_client, course.course_file_url) if course.course_file_url else None
            } for course in courses
        ]

        logger.info(f"Fetched courses successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Courses fetched successfully",
                "data": {"content": course_data, "total": total_courses}
            }
        )

    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error fetching courses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to fetch courses",
                "data": None
            }
        )


async def get_course(course_id, db, current_user):
    logger.info(f"Fetching course with ID: {course_id} by admin: {current_user.email}")
    try:
        # base query
        Creator = aliased(User)
        query = db.query(Course).join(Creator, Creator.id == Course.created_by)

        if current_user.user_type in ["org_admin", "content_creator", "exec_viewer", "field_manager"]:
            query = query.filter(
                Course.id == course_id, 
                Creator.organization_id == current_user.organization_id
            )

        elif current_user.user_type == "sales_reps":
            query = query.join(CourseSalesRep, CourseSalesRep.course_id == Course.id).filter(
                Course.id == course_id, CourseSalesRep.sales_rep_id == current_user.id
            )

        course = query.first()
        if not course:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "Course not found",
                    "data": None
                }
            )

        s3_client = await get_s3_client()

        course_data = CourseResponse.model_validate(course).model_dump()
        course_data["image_url"] = await generate_presigned_url(s3_client, course.image_url) if course.image_url else None
        course_data["course_file_url"] = await generate_presigned_url(s3_client, course.course_file_url) if course.course_file_url else None

        org_id = current_user.organization_id
        # result = db.execute({"organization_id": org_id})
        org = db.query(Organization).filter(Organization.id == org_id).first()
        course_prompt =  org.courses_prompt if org else None

        logger.info(f"Fetched course successfully: {course.title}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Course fetched successfully",
                "data": course_data,
                "course_prompt": course_prompt,
                "course_summary": course.course_summary
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error fetching course: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to fetch course",
                "data": None
            }
        )


async def delete_course(course_id, db, current_user):
    logger.info(f"Deleting course with ID: {course_id} by admin: {current_user.email}")
    try:
        Creator = aliased(User)
        course = db.query(Course).join(Creator, Creator.id == Course.created_by).filter(Course.id == course_id, Creator.organization_id == current_user.organization_id).first()
        if not course:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "Course not found",
                    "data": None
                }
            )
        
        if course.image_url and "default_samples" not in course.image_url.lower():
            deletion_successful = await delete_file_from_s3(course.image_url)
            if not deletion_successful:
                logger.error(f"Failed to delete course image from S3: {course.image_url}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "status": "error",
                        "message": "Failed to delete course image",
                        "data": None
                    }
                )
        
        if course.course_file_url and "default_samples" not in course.course_file_url.lower():
            deletion_successful = await delete_file_from_s3(course.course_file_url)
            if not deletion_successful:
                logger.error(f"Failed to delete course file from S3: {course.course_file_url}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "status": "error",
                        "message": "Failed to delete course file",
                        "data": None
                    }
                )

        # 🔹 Soft delete DB record
        course.is_deleted = True
        course.deleted_at = datetime.utcnow()

        db.commit()
        logger.info(f"Course deleted successfully: {course.title}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Course deleted successfully",
                "data": None
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error deleting course: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to delete course",
                "data": None
            }
        )


async def assign_course(course, db, current_user):
    logger.info(f"Assigning course ID: {course.course_id} to sales reps by admin: {current_user.email}")
    try:
        course_record = db.query(Course).filter(Course.id == course.course_id).first()
        if not course_record:
            logger.error(f"Course with ID {course.course_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "Course not found",
                    "data": None
                }
            )
        
        # Check if User exists
        users = db.query(User).filter(User.id.in_(course.sales_rep_ids)).all()
        existing_user_ids = {user.id for user in users}

        # Identify invalid user IDs
        invalid_user_ids = set(course.sales_rep_ids) - existing_user_ids
        if invalid_user_ids:
            logger.error(f"Users not found: {invalid_user_ids}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"Users not found: {list(invalid_user_ids)}",
                    "data": None
                }
            )
        
        # Check if already assigned
        existing_assignments = db.query(CourseSalesRep).filter(
            CourseSalesRep.course_id == course.course_id,
            CourseSalesRep.sales_rep_id.in_(course.sales_rep_ids)
        ).all()
        already_assigned_ids = {assignment.sales_rep_id for assignment in existing_assignments}
        logger.warning(f"Already assigned sales reps: {already_assigned_ids}")

        # Prepare new assignments
        new_assignments = [
            CourseSalesRep(
                course_id=course.course_id,
                sales_rep_id=sales_rep_id,
                assigned_by=current_user.id
            )
            for sales_rep_id in course.sales_rep_ids if sales_rep_id not in already_assigned_ids
        ]

        # Insert new assignments
        if new_assignments:
            db.bulk_save_objects(new_assignments)
            db.commit()

        logger.info(f"Course assigned to users{list(set(course.sales_rep_ids) - already_assigned_ids)} by admin {current_user.email}")  
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Course assigned successfully",
                "data": {
                    "scenario_id": course.course_id,
                    "assigned_users": list(set(course.sales_rep_ids) - already_assigned_ids),
                    "already_assigned_users": list(already_assigned_ids)
                }
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error assigning course: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to assign course",
                "data": None
            }
        )


async def assign_bulk_courses(user_id, course_form, db, current_user):
    logger.info(f"Assigning bulk courses to user ID: {user_id} by admin: {current_user.email}")
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "User not found",
                    "data": None
                }
            )

        # Check if courses exist
        courses = db.query(Course).filter(Course.id.in_(course_form.course_ids)).all()
        existing_course_ids = {course.id for course in courses}

        invalid_course_ids = set(course_form.course_ids) - existing_course_ids
        if invalid_course_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"Courses not found: {list(invalid_course_ids)}",
                    "data": None
                }
            )

        # Check for existing assignments
        existing_assignments = db.query(CourseSalesRep).filter(
            CourseSalesRep.sales_rep_id == user_id,
            CourseSalesRep.course_id.in_(course_form.course_ids)
        ).all()
        already_assigned_ids = {assignment.course_id for assignment in existing_assignments}
        logger.warning(f"Already assigned courses: {already_assigned_ids} to user ID: {user_id}")
        
        new_assignments = [
            CourseSalesRep(
                course_id=course_id,
                sales_rep_id=user_id,
                assigned_by=current_user.id
            )
            for course_id in course_form.course_ids if course_id not in already_assigned_ids
        ]

        if new_assignments:
            db.bulk_save_objects(new_assignments)
            db.commit()

        logger.info(f"Bulk courses assigned to user ID: {user_id} by admin {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Bulk courses assigned successfully",
                "data": {
                    "assigned_courses": list(set(course_form.course_ids) - already_assigned_ids),
                    "already_assigned_courses": list(already_assigned_ids)
                }
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error assigning bulk courses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to assign bulk courses",
                "data": None
            }
        )


async def get_assigned_courses(user_id, db, current_user):
    logger.info(f"Fetching assigned courses for user ID: {user_id} by admin: {current_user.email}")
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "User not found",
                    "data": None
                }
            )

        assigned_courses = db.query(Course).join(
            CourseSalesRep, Course.id == CourseSalesRep.course_id
        ).filter(CourseSalesRep.sales_rep_id == user_id).all()

        if not assigned_courses:
            logger.warning(f"No courses assigned to user ID: {user_id}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No courses assigned to this user",
                    "data": []
                }
            )
        
        s3_client = await get_s3_client()

        course_data = [
            {
                **CourseResponse.model_validate(course).model_dump(),
                "image_url": await generate_presigned_url(s3_client, course.image_url) if course.image_url else None,
                "course_file_url": await generate_presigned_url(s3_client, course.course_file_url) if course.course_file_url else None
            } for course in assigned_courses
        ]

        logger.info(f"Fetched assigned courses successfully for user ID: {user_id}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Assigned courses fetched successfully",
                "data": course_data
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error fetching assigned courses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to fetch assigned courses",
                "data": None
            }
        )


async def remove_assigned_course(user_id, course_id, db, current_user):
    logger.info(f"Removing assigned course ID: {course_id} from user ID: {user_id} by admin: {current_user.email}")
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "User not found",
                    "data": None
                }
            )

        course = db.query(Course).filter(Course.id == course_id).first()
        if not course:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "Course not found",
                    "data": None
                }
            )

        assignment = db.query(CourseSalesRep).filter(
            CourseSalesRep.sales_rep_id == user_id,
            CourseSalesRep.course_id == course_id
        ).first()

        if not assignment:
            logger.warning(f"No assignment found for user ID: {user_id} and course ID: {course_id}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "failure",
                    "message": "No assignment found for this user and course",
                    "data": None
                }
            )

        db.delete(assignment)
        db.commit()
        logger.info(f"Assigned course removed successfully for user ID: {user_id} and course ID: {course_id}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Assigned course removed successfully",
                "data": None
            }
        )
    
    except HTTPException as http_exc:
        logger.error(f"HTTP error occurred: {str(http_exc.detail)}")
        raise http_exc

    except Exception as e:
        logger.error(f"Error removing assigned course: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "message": "Failed to remove assigned course",
                "data": None
            }
        )


async def remove_user_courses_bulk(user_id, db, current_user):
    logger.info(f"Removing courses in bulk for user {user_id} by orgadmin {current_user.email}")

    course_list = db.query(Course.id).join(
        CourseSalesRep, Course.id == CourseSalesRep.course_id
    ).filter(CourseSalesRep.sales_rep_id == user_id).all()
    if course_list:
        course_ids = [row[0] for row in course_list]
        db.execute(
            delete(CourseSalesRep).where(
                CourseSalesRep.sales_rep_id == user_id,
                CourseSalesRep.course_id.in_(course_ids)
            )
        )

    logger.info(f"Courses in bulk for user {user_id} removed by orgadmin {current_user.email} successfully")


async def audio_course_rag(body, db, current_user):
    query = body.message
    course_id = body.course_id

    if not course_id:
        raise HTTPException(status_code=400, detail="Missing course_id")

    if not query:
        query = "Retrieve relevant information from the course documents."

    try:
        org_id = current_user.organization_id

        if not org_id and current_user.user_type == "sales_reps":
            user_record = db.query(User).filter(User.id == current_user.id).first()
            if user_record and user_record.created_by:
                creator_user = db.query(User).filter(
                    User.email == user_record.created_by
                ).first()
                if creator_user:
                    org_id = creator_user.organization_id

        if not org_id:
            raise HTTPException(status_code=400, detail="Organization not found")

        docs = course_chatbot._retrieve_course_documents(
            query=query,
            course_id=course_id,
            org_id=org_id,
            k=3
        )

        from api.user_management.user_management import get_company_context

        company_context = await get_company_context(
            db, current_user, return_raw=True
        )

        context_data = {"course_id": course_id, "org_id": org_id}
        docs = await course_chatbot.guardrails.validate_retrieved_docs_async(
            docs, context_data
        )

        formatted_chunks = []
        for i, doc in enumerate(docs):
            formatted_chunks.append(f"[Source {i+1}]\n{doc.page_content}")

        context = "\n\n".join(formatted_chunks)
        context = context[:3000]

        return {
            "status": "success",
            "context": context,
            "company_context": company_context
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in audio_course_rag: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

async def format_response(response, db, current_user):
    try:
        text = response

        if not text.strip():
            raise HTTPException(status_code=400, detail="Empty response")

        # ✅ Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)

        html = ""
        in_list = False

        buffer = []

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()

            if not sentence:
                continue

            # 👉 Bullet detection (optional)
            if re.match(r"^[-•*]\s+", sentence):
                if buffer:
                    html += f"<p style='margin-bottom:12px'>{' '.join(buffer)}</p>"
                    buffer = []

                if not in_list:
                    html += "<ul>"
                    in_list = True

                item = re.sub(r"^[-•*]\s+", "", sentence)
                html += f"<li style='margin-bottom:8px'>{item}</li>"

            else:
                if in_list:
                    html += "</ul>"
                    in_list = False

                # 👉 First sentence as heading
                if i == 0:
                    html += f"<h2>{sentence}</h2>"
                else:
                    buffer.append(sentence)

                # 👉 Break after 2 sentences
                if len(buffer) == 2:
                    html += f"<p style='margin-bottom:12px'>{' '.join(buffer)}</p>"
                    buffer = []

        # flush remaining
        if buffer:
            html += f"<p style='margin-bottom:12px'>{' '.join(buffer)}</p>"

        if in_list:
            html += "</ul>"

        formatted_html = f'<div class="ai-response">{html}</div>'

        return {
            "status": "success",
            "html": formatted_html
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
