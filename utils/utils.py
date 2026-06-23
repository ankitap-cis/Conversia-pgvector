import os
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
import smtplib
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jinja2 import Environment, FileSystemLoader
import jwt
from pydantic import EmailStr
from sqlalchemy.orm import Session
from connection import get_db
from models.users import User
from schemas.authentication_schema import UserInDB
from logger import *
import configparser


config = configparser.ConfigParser()
config.read("config.ini")

oauth2_scheme = HTTPBearer()

ALGORITHM = config['algorithm']['algorithm']
SECRET_KEY = config['secret_key']['key']
REFRESH_KEY = config['refresh_key']['key']

GMAIL_USER = config['email']['smtp_email']
GMAIL_PASSWORD = config['email']['smtp_password']
SMTP_SERVER = config['email']['smtp_server']
SMTP_PORT = config['email']['smtp_port']


UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)  # Ensure directory exists


async def get_user(db: Session, email: EmailStr):
    user = db.query(User).filter_by(email = email).one_or_none()
    if user:
        user_dict = {
            "id": user.id,
            "organization_id": user.organization_id,
            "org_name": user.organization.org_name if user.organization and user.organization.org_name else None,
            "name": user.username,
            "full_name": user.profile.full_name.capitalize() if user.profile and user.profile.full_name else None,
            "email": user.email,
            "hashed_password": user.password,
            "user_type": user.user_type,
            "archive":user.archive,
            "acc_status": user.profile.acc_status,
            "content_creator_access": user.content_creator_access,
        }
        return UserInDB(**user_dict)
    return None


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()), db: Session = Depends(get_db)):
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication scheme. Must use Bearer",
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp"]}
        )

        username: str = payload.get("email")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid authentication credentials",
            )

        current_user = await get_user(db, username)
        return current_user

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "failure",
                "message": "Token has expired",
                "data": None
            }
        )

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "failure",
                "message": "Invalid token",
                "data": None
            }
        )


async def check_admin_role(current_user: Session = Depends(get_current_user)):
    """Check if the current user is an admin."""
    if current_user.user_type != "org_admin":  # Adjust this field based on your database schema
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "failure", 
                "message": "Access denied. Admins only.",
                "data": None
            }
        )
    return current_user


async def check_superadmin_role(current_user: Session = Depends(get_current_user)):
    """Check if current user is a superadmin"""
    if current_user.user_type != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "status": "failure",
                "message": "Access denied. Superadmin only.",
                "data": None
            }
        )
    return current_user



def send_email(
    email: str,
    subject: str,
    body: str = None,
    data: dict = None,
    attachment=None,
    template: str = None
):
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = email
    msg['Subject'] = subject

    # Render HTML email template if provided
    if template:
        env = Environment(loader=FileSystemLoader("templates"))
        template_obj = env.get_template(template)
        rendered_html = template_obj.render(data=data or {})
        msg.attach(MIMEText(rendered_html, 'html'))
    elif body:
        msg.attach(MIMEText(body, 'plain'))

    # Attach PDF or other file if provided
    if attachment:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename=invoice_{email}.pdf",
        )
        msg.attach(part)

    try:
        PORT = 465  # SSL
        server = smtplib.SMTP_SSL(SMTP_SERVER, PORT)
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, email, msg.as_string())
        server.quit()
        logger.info(f'{subject} sent successfully')
        return True

    except Exception as e:
        logger.error(f"Email sending failed: {e}")
        return False


# Add to utils.py
async def get_current_user_ws(token: str, db: Session):
    logger.info(f"Validating WS token: {token[:20]}...")
    
    if not token:
        logger.warning("No token provided")
        return None
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        logger.info(f"Token decoded, email: {payload.get('email')}")
        
        email = payload.get("email")
        if not email:
            logger.warning("No email in token payload")
            return None
            
        user = await get_user(db, email)
        if not user:
            logger.warning(f"No user found for email: {email}")
            return None
            
        logger.info(f"User validated: {user.email}")
        return user
        
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.PyJWTError as e:
        logger.error(f"JWT error: {e}")
        return None
