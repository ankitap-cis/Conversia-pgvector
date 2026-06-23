from typing import Optional
import bcrypt
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
import jwt
from pydantic import EmailStr
from sqlalchemy import or_
from api.ai_consumption.ai_token_credit import assign_prorated_credit
from api.prompt.prompt_master import copy_master_prompts_to_user
from default_samples import default_samples
from logger import *
from models.users import Organization, Profile, User
from datetime import datetime as dt, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from utils.s3_bucket_helper import generate_presigned_url, get_s3_client
from utils.utils import get_user, send_email
import configparser
from cryptography.fernet import Fernet
from api.roleplay_assistant.features.course_services import admin_coursefile_to_vectordb
from api.roleplay_assistant.assistant import admin_scenariofile_to_vectordb
from models.rbac_models import UserRole


config = configparser.ConfigParser()
config.read("config.ini")


ACCESS_TOKEN_EXPIRE_MINUTES = config['token']['access_token_expire_minutes']
REFRESH_TOKEN_EXPIRE_DAYS = config['token']['refresh_token_expire_days']
REMEMBER_ME_DAYS = config['token']['remember_me_days']
ACTIVATE_TOKEN_EXPIRE_DAYS = config['token']['activate_token_expire_days']
RESET_TOKEN_EXPIRE_MINUTES = config['token']['reset_token_expire_minutes']
SECRET_KEY = config['secret_key']['key']
ALGORITHM = config['algorithm']['algorithm']
BASE_URL = config['fast_api_server']['base_url']
CRYPTOGRAPHY_KEY = config['cryptography_key']['key']


cipher_suite = Fernet(CRYPTOGRAPHY_KEY)


# Encryption Methods
def encrypt_data(data: str) -> str:
    return cipher_suite.encrypt(data.encode()).decode()


def decrypt_data(encrypted_data: str) -> str:
    return cipher_suite.decrypt(encrypted_data.encode()).decode()


# Utility functions
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = dt.now(timezone.utc) + (expires_delta if expires_delta else timedelta(minutes=5))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = dt.now(timezone.utc) + (expires_delta if expires_delta else timedelta(days=7))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_activate_token(email: str):
    expire = dt.now(timezone.utc) + timedelta(days=int(ACTIVATE_TOKEN_EXPIRE_DAYS))
    to_encode = {"sub": email, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_reset_token(email: str):
    expire = dt.now(timezone.utc) + timedelta(minutes=int(RESET_TOKEN_EXPIRE_MINUTES))
    to_encode = {"sub": email, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def authenticate_user(db: Session, email: EmailStr, password: str):
    user = await get_user(db, email)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


def send_reset_email(username, email, token):
    subject = 'Reset Password Email Conversia'
    reset_link = f"{BASE_URL}/auth/reset-password?token={token}"
    body = f"""
        Here is your reset password link:-
        {reset_link}
    """

    response = send_email(
        email,
        subject=subject,
        data={"name": username, "email": email, "link": reset_link},
        template="reset_password.html"
    )
    return response


def send_activation_email(username, email, token):
    subject = 'Welcome to Conversia – Let’s Get You Started!'
    activation_link = f"{BASE_URL}/auth/activate-account?token={token}"
    body = f"""
        Here is your account activaton link:-
        {activation_link}
    """

    response = send_email(
        email,
        subject=subject,
        data={"name": username, "email": email, "link": activation_link},
        template="set_password.html"
    )

    return response


def send_set_pass_email(username, email, token, user_role):
    subject = 'Welcome to Conversia – Let’s Get You Started!'
    set_pass_link = f"{BASE_URL}/auth/set-password?token={token}"
    body = f"""
        Here is your account activaton and set password link for the role as {user_role}:-
        {set_pass_link}
    """

    response = send_email(
        email,
        subject=subject,
        data={"name": username, "email": email, "link": set_pass_link},
        template="set_password.html"
    )
    return response


async def register(user, db, current_user):
    logger.info(f"Registering user: {user}")
    try:
        existing_user = db.query(User).filter( or_(User.email == user.email, User.username == user.username)).first()
        if existing_user:
            raise HTTPException(
                status_code=400,
                detail={
                    "status":"failure",
                    "message": "Email or username already registered",
                    "data":None
                }
            )

        hashed_password = hash_password(user.password) if "password" in str(user) else ""

        is_superadmin_created = current_user and current_user.user_type == "superadmin"
        creator_email = current_user.email if is_superadmin_created  else user.email

        new_user = User(
            username = encrypt_data(user.username),
            email = user.email,
            password = hashed_password,
            user_type = "org_admin",
            created_at = dt.now(),
            created_by = creator_email,
            last_updated_at = dt.now(),
            last_updated_by = creator_email
        )
        db.add(new_user)
        db.flush()  # Ensure new_user.id is available without committing

        # Create Profile for the user
        profile = Profile(
            user_id=new_user.id,
            full_name=user.full_name,
            acc_status="Inactive", 
            created_at = dt.now(), 
            created_by = creator_email, 
            last_updated_at = dt.now(), 
            last_updated_by = creator_email
        )
        db.add(profile)

        organization = Organization(
            admin_id = new_user.id,
            org_name = user.org_name,
            master_prompt = user.master_prompt,
            evaluation_prompt = user.evaluation_prompt,
            precall_prompt = user.precall_prompt,
            chatbot_prompt = user.chatbot_prompt,
            courses_prompt = user.courses_prompt,
            email_prompt = user.email_prompt,
            summarizer_prompt = user.summarizer_prompt,
            field_intelligence_prompt = user.field_intelligence_prompt,
            content_creator_prompt = user.content_creator_prompt,
            llm_model = user.llm_model,
            created_at = dt.now(), 
            created_by = creator_email, 
            last_updated_at = dt.now(), 
            last_updated_by = creator_email
        )
        db.add(organization)
        db.flush()

        new_user.organization_id = organization.id

        user_role = UserRole(
            user_id = new_user.id,
            role_id = 1
        )
        db.add(user_role)

        token = create_activate_token(user.email)
        if token:
            if is_superadmin_created:
                response = send_set_pass_email(user.username, user.email, token, user_role="org_admin")
                if response:
                    logger.info(f'Set password email sent successfully to user: {user.email}')
                else:
                    logger.warning("Facing issues while sending emails")
            else:
                response = send_activation_email(user.username, user.email, token)
                if response:
                    logger.info(f'Account activation mail send successfully to user: {user.email}')
                else:
                        logger.warning("Facing issues while sending emails")
        
        await assign_prorated_credit(db, new_user, current_user)
        await default_samples(db, new_user)
        await copy_master_prompts_to_user(db=db, current_user=new_user)

        db.commit()  
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": f"Account activation mail send successfully to user: {user.email}",
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        db.rollback()
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status":"failure",
                "message": "An exception occured while registering user",
                "data":None
            }
        )


async def login(form_data, db):
    try:
        user = await authenticate_user(db, form_data.email, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status":"failure",
                    "message": "Incorrect username or password",
                    "data":None
                }
            )

        if user.user_type == "sales_reps":
            acc_status = (
                db.query(Profile.acc_status)
                .join(User, Profile.user_id == User.id)
                .filter(
                    User.email == db.query(User.created_by)
                                    .filter(User.email == form_data.email)
                                    .scalar_subquery()
                )
                .scalar()
            )
            if acc_status == "Suspend":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status":"failure",
                        "message":"Unable to logged in as your admin account is suspended.",
                        "data":None
                    }
                )

        if user.archive == True:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status":"failure",
                    "message": "Account deleted, Please contact support",
                    "data":None
                }
            )

        if user.acc_status == "Suspend":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status":"failure",
                    "message": "Account suspended, Please contact support",
                    "data":None
                }
            )
        
        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        if profile.acc_status == "Inactive":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status":"failure",
                    "message":"Account is not active. Please contact support.",
                    "data":None
                }
            )
        
        # Determine token duration
        if getattr(form_data, "remember_me", False):
            access_token_expires = timedelta(days=int(REMEMBER_ME_DAYS))
            refresh_token_expires = timedelta(days=int(REMEMBER_ME_DAYS))
        else:
            access_token_expires = timedelta(minutes=int(ACCESS_TOKEN_EXPIRE_MINUTES))
            refresh_token_expires = timedelta(days=int(REFRESH_TOKEN_EXPIRE_DAYS))

        access_token = create_access_token(
            data={"sub": user.email}, expires_delta=access_token_expires
        )

        token_payload = {
            "user_id": user.id,
            "email": user.email,
            "role": user.user_type,
            "impersonated": False
        }

        access_token = create_access_token(
            data=token_payload,
            expires_delta=access_token_expires
        )

        refresh_token = create_refresh_token(
            data={"sub": user.email}, expires_delta=refresh_token_expires
        )

        logger.info('User logged in successfully')
        context= {
            "user_id": user.id,
            "username":decrypt_data(user.name) if user.user_type !="superadmin" else user.name,
            "email": user.email,
            "full_name": user.full_name,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "role": user.user_type,
            "content_creator_access": user.content_creator_access,
        }

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "User logged in successfully.",
                "data": context
            }
        )

    except TypeError as te:
        logger.error(str(te))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": str(te),
                "data": None
            }
        )

    except HTTPException as http_exc:
        # Re-raise HTTPException so FastAPI handles it correctly
        raise http_exc

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status":"failure",
                "message": "Account is not active. Please contact support.",
                "data":None
            }
        )


async def request_password_reset(fp_request, db):
    logger.info(f"Requesting password reset by user: {fp_request.email}")
    try:
        user = await get_user(db, email=fp_request.email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "User not found",
                    "data": None
                }
            )
        
        if user.archive == True:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Account deleted, Please contact support",
                    "data": None
                }
            )

        if user.acc_status == "Suspend":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": "Account suspended, Please contact support",
                    "data": None
                }
            )

        token = create_reset_token(user.email)
        response = send_reset_email(decrypt_data(user.name), user.email, token)
        if not response:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "status": "failure",
                    "message": "Facing issues while sending emails",
                    "data": None
                }
            )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": f"Password reset link has been sent to your email {fp_request.email}",
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
                "message": "An error occured while sending emails",
                "data": None
            }
        )


async def set_password(data, db):
    logger.info("Setting password")
    reset_password_response = await reset_password(data, db)
    if reset_password_response.status_code != 200: 
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while setting password",
                "data": None
            }
        )
    
    activate_account_response = await activate_account(data.token, db)
    if activate_account_response.status_code != 200: 
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while activaiting account",
                "data": None
            }
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "message": "Account activation and setting password completed successfully",
            "data": None
        }
    )


async def reset_password(data, db):
    try:
        payload = jwt.decode(data.token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "status": "failure",
                    "message": "Invalid token",
                    "data": None
                }
            )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "failure",
                "message": "Token has expired",
                "data": None
            }
        )

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "failure",
                "message": "Invalid token",
                "data": None
            }
        )

    user = await get_user(db, email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "failure",
                "message": "User not found",
                "data": None
            }
        )

    hashed_password = hash_password(data.new_password)

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user:
        user.password = hashed_password
        db.commit()
        db.refresh(user)

        logger.info(f"Password has been reset successfully for user: {email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Password has been reset successfully",
                "data": None
            }
        )


async def activate_account(token, db):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
        email = payload.get("sub")
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status":"failure",
                    "message":"Invalid token",
                    "data":None
                }
            )

        user = db.query(User).filter(User.email == email).first()      

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "User not found",
                    "data": None
                }
            )

        # Fetch profile for the user
        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "Profile not found.",
                    "data": None
                }
            )

        # Update profile acc_status
        profile.acc_status = "Active"
        db.commit()

        logger.info(f"Account activated successfully for user: {email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Profile updated successfully.",
                "data": {"acc_status": profile.acc_status}
            }
        )

    except jwt.ExpiredSignatureError as e:
        db.rollback()
        logger.error(e)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status":"failure",
                "message":"Activation link has expired",
                "data":None          
            }
        )

    except jwt.InvalidTokenError as e:
        db.rollback()
        logger.error(e)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status":"failure",
                "message":"Invalid activation link",
                "data":None          
            }
        )

    except HTTPException as http_exe:
        db.rollback()
        raise http_exe

    except Exception as e:
        db.rollback()
        logger.error(e)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status":"failure",
                "message":"An error occurred while activating the account",
                "data":None
            }
        )


async def resend_activation_email(email, db):
    try:
        # Fetch user and profile in one query using join()
        user_profile = (
            db.query(User, Profile)
            .join(Profile, User.id == Profile.user_id)
            .filter(User.email == email)
            .first()
        )

        if not user_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": "User or profile not found",
                    "data": None
                }
            )

        user, profile = user_profile  # Unpacking tuple

        if profile.acc_status == "Inactive":
            token = create_activate_token(email)
            response = send_activation_email(user.username, email, token)
            if response:
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "status":"success",
                        "message":"Account activation email resent successfully",
                        "data":None
                    }
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "status":"failure",
                        "message": "Facing issues while sending emails.",
                        "data":None
                    }
                )

        else:
            logger.info(f"Account already activated for user: {email}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status":"success",
                    "message":"Account is already activated",
                    "data":None
                }
            )

    except HTTPException as http_exe:
        raise http_exe

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status":"failure",
                "message":"An error occurred while resending the activation email",
                "data":None
            }
        )


async def change_password(password, db, current_user):
    user = db.query(User).filter(User.email == current_user.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status":"failure",
                "message":"User not found",
                "data":None
            }
        )

    if not verify_password(password.current_password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status":"failure",
                "message":"Current password does not match",
                "data":None
            }
        )

    if password.new_password != password.confirm_new_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status":"failure",
                "message":"New password and confirmation password do not match",
                "data":None
            }
        )

    user.password =  hash_password(password.new_password)
    db.commit()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status":"success",
            "message":"Password updated successfully",
            "data":None
        }
    )


async def refresh_token(refresh_token, db):
    logger.info("Regenerating access token.")
    try:
        refresh_token = refresh_token.current_refresh_token
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])

        user_email = payload.get("email") or payload.get("sub")
        if not user_email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "status": "failure",
                    "message": "Invalid token",
                    "data": None
                }
            )

        # Fetch user from DB
        user = db.query(User).filter(User.email == user_email).first()
        if not user or user.archive or user.profile.acc_status == "Suspend":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": "failure",
                    "message": "User not found or deactivated",
                    "data": None
                }
            )

        # Check impersonation flag
        if payload.get("impersonated"):
            logger.info(f"Refreshing impersonated session for {user_email}")

            new_payload = {
                "user_id": payload.get("user_id", user.id),
                "email": user_email,
                "role": payload.get("role", user.user_type),
                "impersonated": True,
                "original_user_id": payload.get("original_user_id"),
                "original_user_email": payload.get("original_user_email"),
            }
        else:
            logger.info(f"Refreshing normal session for {user_email}")
            new_payload = {
                "user_id": user.id,
                "email": user_email,
                "role": user.user_type,
                "impersonated": False
            }

        # Generate new access token
        new_access_token = create_access_token(
            data=new_payload,
            expires_delta=timedelta(minutes=int(ACCESS_TOKEN_EXPIRE_MINUTES))
        )

        logger.info("Access token regenerated successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Access token regenerated successfully",
                "data": {
                    "access_token": new_access_token,
                    "token_type": "bearer",
                    "impersonated": new_payload["impersonated"]
                }
            }
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status":"failure",
                "message":"Refresh token expired",
                "data":None
            }
        )

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status":"failure",
                "message":"Invalid refresh token",
                "data":None
            }
        )
