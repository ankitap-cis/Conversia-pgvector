from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from api.auth.authentication import (
    register, 
    login, 
    set_password, 
    reset_password, 
    request_password_reset, 
    activate_account, 
    resend_activation_email, 
    change_password,
    refresh_token
)
from connection import get_db
from schemas.authentication_schema import ChangePass, GenerateRefreshAndAccessTokenSchema, LoginSchema, PasswordReset, PasswordResetRequest, RegisterationSchema
from utils.utils import check_superadmin_role, get_current_user


auth_router = APIRouter()


# @auth_router.post('/register')
# async def register_api(user: RegisterationSchema, db: Session = Depends(get_db)):
#     return await register(user, db, current_user=None)


@auth_router.post('/register-admin')
async def register_admin_api(user: RegisterationSchema, db: Session = Depends(get_db), current_user: Session = Depends(check_superadmin_role)):
    return await register(user, db, current_user)


@auth_router.post('/login')
async def login_api(form_data: LoginSchema, db: Session = Depends(get_db)):
    return await login(form_data, db)


@auth_router.post('/forgot-password')
async def request_password_reset_api(fp_request: PasswordResetRequest, db: Session = Depends(get_db)):
    return await request_password_reset(fp_request, db)


@auth_router.post('/reset-password')
async def reset_password_api(data: PasswordReset, db: Session = Depends(get_db)):
    return await reset_password(data, db)


@auth_router.post('/set-password')
async def set_password_api(data: PasswordReset, db: Session = Depends(get_db)):
    return await set_password(data, db)


@auth_router.get("/activate", response_model=None)
async def activate_account_api(token: str, db: Session = Depends(get_db)):
    return await activate_account(token, db)


@auth_router.get("/resend-email", response_model=None)
async def resend_activation_mail_api(email: str, db: Session = Depends(get_db)):
    return await resend_activation_email(email, db)


@auth_router.post("/change-password")
async def change_password_api(password: ChangePass, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await change_password(password, db, current_user)

@auth_router.post("/refresh-token")
async def refresh_token_api(token: GenerateRefreshAndAccessTokenSchema, db: Session = Depends(get_db)):
    return await refresh_token(token, db)


@auth_router.get("/users/me")
async def read_users_me(current_user: Session = Depends(get_current_user)):
    return current_user
