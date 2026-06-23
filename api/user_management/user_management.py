from datetime import timedelta, timezone
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
import sqlalchemy
from sqlalchemy import desc, or_
from api.ai_consumption.ai_token_credit import assign_prorated_credit
from api.auth.authentication import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token, create_activate_token, create_refresh_token, decrypt_data, encrypt_data, send_set_pass_email
from api.prompt.prompt_master import copy_master_prompts_to_user
from api.roleplay_assistant.content_generation import admin
from logger import *
from models.rbac_models import Role, UserRole
from models.users import CompanyContext, Organization, Profile, SessionLog, User
from schemas.user_management_schema import OrganizationResponse, RepresentativeResponse
from utils.utils import get_user


async def get_user_profile(user_id, db, current_user):
    logger.info(f"Fetching user profile for email {current_user.email}")
    user_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    if user_profile:
        logger.info(f"Fetched user profile successfully for user_id {user_id}")
        context = {
            "id": user_profile.id,
            "email": current_user.email,
            "first_name": user_profile.first_name,
            "last_name": user_profile.last_name,
        }
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status":"success",
                "message":"User profile fetched successfully",
                "data":context  
            }
        )
    


async def update_user_profile(user_id, update_user, db, current_user):
    logger.info(f"Updating user profile for email {current_user.email}")
    # work on that section once figma is created
    pass


async def create_org_members(sales_reps, db, current_user):
    logger.info(f"Creating {sales_reps.user_type} by orgadmin: {current_user.email}")
    
    allowed_roles = ["superadmin", "org_admin"]

    email_exists = db.query(User).filter(User.email == sales_reps.email).first()
    if email_exists:
        logger.error(f"User with email {sales_reps.email} already exists.")
        raise HTTPException(
            status_code=400,
            detail={
                "status":"failure",
                "message": "Email already registered",
                "data":None
            }
        )

    try:
        new_rep = User(
            username =  encrypt_data(sales_reps.username),
            email = sales_reps.email,
            user_type = sales_reps.user_type,
            password = 'pending',
            organization_id = current_user.organization_id,
            field_manager_id = sales_reps.assigned_by if sales_reps.assigned_by else None,
            content_creator_access = sales_reps.content_creator_access,
            created_at = dt.now(),
            created_by = current_user.email,
            last_updated_at = dt.now(),
            last_updated_by = current_user.email

        )
        db.add(new_rep)
        db.flush()  # Ensure new_rep.id is available without committing

        # Create Profile for the user
        new_rep_profile = Profile(
            user_id=new_rep.id,
            full_name = sales_reps.full_name,
            acc_status="Inactive", 
            created_at = dt.now(), 
            created_by = current_user.email, 
            last_updated_at = dt.now(), 
            last_updated_by = current_user.email
        )
        db.add(new_rep_profile)

        role_id = db.query(Role.id).filter(Role.name == new_rep.user_type).scalar()

        user_role = UserRole(
            user_id = new_rep.id,
            role_id = role_id
        )
        db.add(user_role)
        admin = db.query(User).filter(User.user_type == "org_admin").first()
        await assign_prorated_credit(db, new_rep, admin)
        await copy_master_prompts_to_user(db=db, current_user=new_rep)
        
        db.commit()

        if sales_reps.user_type in ["sales_reps", "field_manager", "content_creator", "exec_viewer"]:
            token = create_activate_token(sales_reps.email)
            send_set_pass_email(sales_reps.username, sales_reps.email, token, sales_reps.user_type)
            logger.info(f"Set password email sent to {sales_reps.email}")

        logger.info(f'Member having email {sales_reps.email} created successfully')

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Member created successfully",
                "data": None
            }
        )

    except HTTPException as http_exe:
        raise http_exe
    
    except sqlalchemy.exc.IntegrityError as e:
        error_message = f"Integrity Error: {str(e)}"
        logger.error(error_message)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
            "status": "failure",
            "message": "User with this email already exists.",
            "data": None
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
            "status": "failure",
            "message": "Unexpected error occured.",
            "data": None
            }
        )


async def edit_org_member_role(rep_id, sales_reps, db, current_user):
    logger.info(f"Updationg role for {sales_reps.email}  by orgadmin {current_user.email}")

    existing_member = db.query(User).filter(User.id == rep_id, User.organization_id == current_user.organization_id).first()
    if not existing_member:
            raise HTTPException(
                status_code=404,
                detail={
                "status": "failure",
                "message": "User not found",
                "data": None
            }
        )
    
    old_role = existing_member.user_type
    new_role = sales_reps.user_type

    user_role = db.query(UserRole).filter(UserRole.user_id == rep_id).first()
    role_id = db.query(Role.id).filter(Role.name == new_role).scalar()
    user_role.role_id = role_id
    
    existing_member.content_creator_access = sales_reps.content_creator_access

    existing_member.user_type = sales_reps.user_type
    if sales_reps.assigned_by:
        existing_member.field_manager_id = sales_reps.assigned_by
    existing_member.last_updated_at = dt.now()
    existing_member.last_updated_by = current_user.email

    if old_role == "sales_reps" and new_role != "sales_reps":
        # Utilizing from circular import error
        from api.courses.courses import remove_user_courses_bulk
        from api.roleplay.roleplay import remove_user_scenarios_bulk

        logger.info(f"Removing courses & scenarios for sales rep {existing_member.email}")

        await remove_user_scenarios_bulk(existing_member.id, db, current_user)
        await remove_user_courses_bulk(existing_member.id, db, current_user)
        existing_member.field_manager_id = None
    db.commit()

    logger.info(f"Role for {sales_reps.email} updated successfully by orgadmin {current_user.email}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Role updated successfully",
                "data": None
            }
        )


async def get_org_members(search_query, limit, offset, db, current_user):
    logger.info(f"Fetching users by admin {current_user.email}")
    
    query = db.query(
        User.id,
        User.username,
        User.email,
        User.user_type,
        User.content_creator_access,
        Profile.full_name,
        Profile.acc_status
    ).join(Profile, Profile.user_id == User.id)

    query = query.filter(User.organization_id == current_user.organization_id, User.user_type != 'org_admin', User.archive == False)

    if current_user.user_type == 'field_manager':
        query = query.filter(User.field_manager_id == current_user.id, User.user_type == "sales_reps")

    if search_query:
        ilike_pattern = f"%{search_query}%"
        query = query.filter(User.email.ilike(ilike_pattern))

    total = query.count()
    representatives = query.order_by(desc(User.created_at)).offset(offset).limit(limit).all()

    if not representatives:
        logger.warning(f"No representatives found for {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "No users found.",
                "data": []
            }
        )

    representatives_data = [RepresentativeResponse.model_validate({
        **representative._mapping,
        "username": decrypt_data(representative.username),
        }).model_dump() for representative in representatives]
    logger.info(f"Representatives fetched successfully by user: {current_user.email}")

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Representative fetched successfully",
            "data": {"content": representatives_data, "total": total}
        }
    )


async def get_sales_rep(rep_id, db, current_user):
    logger.info(f"Fetching representive with id {rep_id} by admin {current_user.email}")
    representative = db.query(
            User.id,
            User.username,
            User.email,
            User.user_type,
            User.field_manager_id.label("assigned_by"),
            User.content_creator_access,
            Profile.full_name,
            Profile.acc_status
        ).join(
            Profile, Profile.user_id == User.id
        ).filter(
            User.id == rep_id, User.organization_id == current_user.organization_id
        ).first()

    if not representative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "failure",
                "message": "No user found.",
                "data": None
            }
        )
    representative_data = RepresentativeResponse.model_validate(representative._mapping).model_dump()
    representative_data["username"] = decrypt_data(representative_data["username"])

    logger.info(f"Representative fetched successfully by user: {current_user.email}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Representative fetched successfully",
            "data": representative_data
        }
    )


async def remove_sales_rep(rep_id, db, current_user):
    logger.info(f"Archieving user with id {rep_id} by {current_user.email}")
    try:
        # Get full User object with related Profile
        rep = db.query(User).join(Profile).filter(User.id == rep_id).first()

        if rep:
            rep.archive = True
            if rep.profile:  # assuming User has a `profile` relationship
                rep.profile.acc_status = "Suspend"
            else:
                logger.warning(f"User {rep_id} has no associated profile")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "status": "failure",
                        "message": "User profile doesn't exists",
                        "data": rep_id
                    }
                )

            db.commit()

            logger.info(f"User {rep_id} archived and account suspended successfully")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "Representative deleted successfully",
                    "data": rep_id
                }
            )

        else:
            logger.warning(f"User with id {rep_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "User doesn't exists",
                    "data": rep_id
                }
            )

    except HTTPException as httpexe:
        raise httpexe

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to archive user {rep_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An exception occured while deleting sales rep",
                "data": None
            }
        )


async def get_organizations(search_query, limit, offset, db, current_user):
    logger.info(f"Fetching organization by superadmin: {current_user.email}")
    try:
        query = db.query(User, Profile.acc_status, Profile.full_name, Organization.org_name).join(Profile, Profile.user_id == User.id).join(Organization, Organization.admin_id == User.id).filter(User.user_type == 'org_admin')
        if search_query:
            ilike_pattern = f"%{search_query}%"
            query = query.filter(
                or_(
                    User.email.ilike(ilike_pattern),
                    Profile.full_name.ilike(ilike_pattern)  # optional
                )
            )
        
        total = query.count()
        organizations = query.order_by(desc(User.last_updated_at)).offset(offset).limit(limit).all()

        if not organizations:
            logger.warning(f"No organizations found for {current_user.email}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "No organizations found.",
                    "data": []
                }
            )
        organizations_data = [OrganizationResponse.model_validate({
            **organization.User.__dict__,
            "acc_status": organization.acc_status,
            "full_name": organization.full_name,  # Add full_name here
            "org_name": organization.org_name
            }).model_dump() for organization in organizations]
        logger.info(f"Organization fetched successfully by superadmin: {current_user.email}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Organization fetched successfully",
                "data": {"content": organizations_data, "total": total}
            }
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while fetching organizations",
                "data": None
            }
        )


async def update_organization_data(organization_id, form, db, current_user):
    logger.info(f"Updating organization data of if {organization_id} by superadmin {current_user.email}")
    result = db.query(User, Profile, Organization)\
    .join(Organization, Organization.admin_id == User.id)\
    .join(Profile, Profile.user_id == User.id)\
    .filter(User.id == organization_id)\
    .first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "failure",
                "message": "No organization found with id",
                "data": None
            }
        )
    
    user, profile, organization = result

    if hasattr(form, "acc_status"):
        profile.acc_status = form.acc_status
    
    if hasattr(form, "org_name"):
        organization.org_name = form.org_name

    if hasattr(form, "llm_model"):
        organization.llm_model = form.llm_model

    if hasattr(form, "master_prompt"):
        organization.master_prompt = form.master_prompt

    if hasattr(form, "evaluation_prompt"):
        organization.evaluation_prompt = form.evaluation_prompt

    if hasattr(form, "precall_prompt"):
        organization.precall_prompt = form.precall_prompt

    if hasattr(form, "chatbot_prompt"):
        organization.chatbot_prompt = form.chatbot_prompt

    if hasattr(form, "courses_prompt"):
        organization.courses_prompt = form.courses_prompt

    if hasattr(form, "email_prompt"):
        organization.email_prompt = form.email_prompt

    if hasattr(form, "summarizer_prompt"):
        organization.summarizer_prompt = form.summarizer_prompt

    if hasattr(form, "content_creator_prompt"):
        organization.content_creator_prompt = form.content_creator_prompt

    if hasattr(form, "field_intelligence_prompt"):
        organization.field_intelligence_prompt = form.field_intelligence_prompt

    try:
        db.commit()
        db.refresh(profile)
        db.refresh(organization)

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update organization: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failure",
                "message": "Internal server error",
                "data": None
            }
        )

    logger.info(f"Organization with id {organization_id} updated successfully by superadmin {current_user.email}")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Organization and profile updated successfully",
            "data": {
                "organization_id": organization.id
            }
        }
    )
    

async def get_organization(organization_id, db, current_user):
    logger.info(f"Fetching organization by superadmin {current_user.email}")
    try:
        result = (
            db.query(
                User.id,
                User.username,
                User.email,
                Profile.full_name,
                Profile.acc_status,
                Organization.org_name,
                Organization.llm_model,
                Organization.master_prompt,
                Organization.evaluation_prompt,
                Organization.precall_prompt,
                Organization.chatbot_prompt,
                Organization.courses_prompt,
                Organization.email_prompt,
                Organization.summarizer_prompt,
                Organization.content_creator_prompt,
                Organization.field_intelligence_prompt
            )
            .join(Profile, Profile.user_id == User.id)
            .join(Organization, Organization.admin_id == User.id)
            .filter(User.id == organization_id)
            .first()
        )

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"No organization found with id {organization_id}",
                    "data": None
            }
            )

        org_data = OrganizationResponse.model_validate(result._asdict()).model_dump()

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Organization details fetched successfully",
                "data": org_data
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
                "message": "An exception occured while fetching organization",
                "data": None
            }
        )


async def get_field_managers(db, current_user):
    logger.info(f"Fetching field managers by admin {current_user.email}")

    query = db.query(
        User.id,
        User.username,
        User.email,
        User.user_type,
        Profile.full_name,
        Profile.acc_status
    ).join(Profile, Profile.user_id == User.id)

    query = query.filter(User.organization_id == current_user.organization_id, User.user_type == 'field_manager', User.archive == False)

    field_managers = query.order_by(desc(User.created_at)).all()

    if not field_managers:
        logger.warning(f"No field manager found for {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "No field_manager found.",
                "data": []
            }
        )

    field_managers_data = [RepresentativeResponse.model_validate({
        **field_manager._mapping,
        "username": decrypt_data(field_manager.username),
        }).model_dump() for field_manager in field_managers]
    logger.info(f"Field managers fetched successfully by user: {current_user.email}")

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Field managers fetched successfully",
            "data": field_managers_data
        }
    )



async def impersonate_user(data, db, current_user):
    target_user_email = db.query(User.email).filter_by(id = data.user_id).first()[0]
    logger.info(f"Impersonating org_admin account {target_user_email} by superadmin {current_user.email}")
    requester_id = current_user.id
    requester_email = current_user.email
    requester_role = current_user.user_type

    if requester_role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail={
                "status": "failure",
                "message": "Not allowed to impersonate",
                "data": None
            }
        )
    
    target_user = await get_user(db, target_user_email)

    # Build impersonation token
    impersonation_token = create_access_token({
        "user_id": target_user.id,
        "email": target_user.email,
        "role": target_user.user_type,
        "impersonated": True,
        "original_user_id": requester_id,
        "original_user_email": requester_email
    }, expires_delta=timedelta(minutes=int(ACCESS_TOKEN_EXPIRE_MINUTES)))

    # Refresh token (long-lived)
    impersonation_refresh_token = create_refresh_token(
        data={
            "user_id": target_user.id,
            "email": target_user.email,
            "role": target_user.user_type,
            "impersonated": True,
            "original_user_id": requester_id,
            "original_user_email": requester_email,
        },
        expires_delta=timedelta(days=7),  # Example: 7 days
    )

    context= {
        "user_id": target_user.id,
        "username":decrypt_data(target_user.name) if target_user.user_type !="superadmin" else target_user.name,
        "email": target_user.email,
        "full_name": target_user.full_name,
        "access_token": impersonation_token,
        "refresh_token": impersonation_refresh_token,
        "token_type": "bearer",
        "role": target_user.user_type,
        "impersonate": True
    }

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "User logged in successfully.",
            "data": context
        }
    )


async def stop_impersonation(db, current_user):
    logger.info("Stopping impersonation")
    actor_email_ctx.set(current_user.email)
    subject_email_ctx.set(current_user.email)
    
    return {
        "status": "success",
        "message": f"Impersonation stopped. Now acting as {current_user.email}"
    }


async def create_update_session_log(payload, db, current_user):
    logger.info(f"Adding/Updating session count for user {current_user.email}")
    try:
        existing = db.query(SessionLog).filter(SessionLog.user_id == current_user.id).first()

        if existing:
            # Update the existing record
            existing.name = current_user.full_name if current_user.full_name else '-'
            existing.chat_sessions = existing.chat_sessions + payload.chat_sessions
            existing.chat_total_duration = existing.chat_total_duration + payload.chat_total_duration
            existing.role_play_sessions = existing.role_play_sessions + payload.role_play_sessions
            existing.role_play_total_duration = existing.role_play_total_duration + payload.role_play_total_duration
            existing.pre_call_plan_sessions = existing.pre_call_plan_sessions + payload.pre_call_plan_sessions
            existing.last_updated_by = current_user.email
        else:
            # Create new record
            new_log = SessionLog(
                user_id=current_user.id,
                name=current_user.full_name if current_user.full_name else '-',
                chat_sessions=payload.chat_sessions,
                chat_total_duration=payload.chat_total_duration,
                role_play_sessions=payload.role_play_sessions,
                role_play_total_duration=payload.role_play_total_duration,
                pre_call_plan_sessions=payload.pre_call_plan_sessions,
                created_by=current_user.email,
                last_updated_by=current_user.email,
            )
            db.add(new_log)

        db.commit()

        logger.info("Session log created/updated successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success", 
                "message": "Session log created or updated successfully",
                "data": None
            }
        )
    
    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure", 
                "message": "An exception occured while generating session log",
                "data": None
            }
        )


async def get_organization_session_logs(db, current_user):
    try:
 
        # Fetch all logs for users in same organization
        logs = (
            db.query(SessionLog)
            .join(User, User.id == SessionLog.user_id)
            .filter(User.organization_id == current_user.organization_id)
            .all()
        )
 
        if not logs:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "failure",
                    "message": "No session logs found for this organization",
                    "data": []
                }
            )
 
        response_data = []
 
        for log in logs:
            response_data.append({
                "user_id": log.user_id,
                "name": log.name,
                "chat_sessions": log.chat_sessions,
                "chat_total_duration": log.chat_total_duration,
                "role_play_sessions": log.role_play_sessions,
                "role_play_total_duration": log.role_play_total_duration,
                "pre_call_plan_sessions": log.pre_call_plan_sessions,
                "created_by": log.created_by,
                "last_updated_by": log.last_updated_by
            })
 
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Organization session logs fetched successfully",
                "data": response_data
            }
        )
 
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching organization session logs",
                "error": str(e)
            }
        )


async def set_company_context(company_data, db, current_user):
    logger.info(f"Setting company context for user {current_user.email}")
    try:
        # Check if context already exists for the user
        existing_context = db.query(CompanyContext).filter(CompanyContext.organization_id == current_user.organization_id).first()

        if existing_context:
            logger.info(f"Existing company context found for user {current_user.email}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "success",
                    "message": "Company context already exists",
                    "data": None
                }
            )
        
        new_context = CompanyContext(
            organization_id=current_user.organization_id,
            organization_overview=company_data.organization_overview,
            customer_segments=company_data.customer_segments,
            int_user_ext_stakeholder=company_data.int_user_ext_stakeholder,
            brand_voice=company_data.brand_voice,
            compliance_guardrails=company_data.compliance_guardrails,
            additional_context=company_data.additional_context,
            created_at=dt.now(timezone.utc),
            created_by=current_user.email,
            last_updated_at=dt.now(timezone.utc),
            last_updated_by=current_user.email
        )
        db.add(new_context)

        db.commit()

        logger.info(f"Company context set successfully for user {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Company context set successfully",
                "data": new_context.id
            }
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while setting company context",
                "data": None
            }
        )


async def update_company_context(company_data, db, current_user):
    logger.info(f"Updating company context for user {current_user.email}")
    try:
        context = db.query(CompanyContext).filter(CompanyContext.organization_id == current_user.organization_id).first()

        if not context:
            logger.warning(f"No existing company context found for user {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "No existing company context found to update",
                    "data": None
                }
            )

        # Update fields if they are provided in the request
        for field in ['organization_overview', 'customer_segments', 'int_user_ext_stakeholder', 'brand_voice', 'compliance_guardrails', 'additional_context']:
            if hasattr(company_data, field) and getattr(company_data, field) is not None:
                setattr(context, field, getattr(company_data, field))

        context.last_updated_at = dt.now(timezone.utc)
        context.last_updated_by = current_user.email

        db.commit()

        logger.info(f"Company context updated successfully for user {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Company context updated successfully",
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
                "message": "An error occurred while updating company context",
                "data": None
            }
        )


async def get_company_context(db, current_user, return_raw: bool = False):
    logger.info(f"Getting company context for user {current_user.email}")
    try:
        context = db.query(CompanyContext).filter(CompanyContext.organization_id == current_user.organization_id).first()

        if not context:
            logger.warning(f"No company context found for user {current_user.email}")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "failure",
                    "message": "No company context found",
                    "data": None
                }
            )

        context_data = {
            "id": context.id,
            "organization_overview": context.organization_overview,
            "customer_segments": context.customer_segments,
            "int_user_ext_stakeholder": context.int_user_ext_stakeholder,
            "brand_voice": context.brand_voice,
            "compliance_guardrails": context.compliance_guardrails,
            "additional_context": context.additional_context
        }

        logger.info(f"Company context fetched successfully for user {current_user.email}")

        if return_raw:
            return context_data

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Company context fetched successfully",
                "data": context_data
            }
        )

    except Exception as e:
        logger.error(str(e))
        if return_raw:
            raise e 

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occurred while fetching company context",
                "data": None
            }
        )

