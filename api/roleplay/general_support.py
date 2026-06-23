from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from logger import *
from models.users import User
from utils.utils import send_email


async def general_support(data, db: Session, current_user):
    logger.info(f"Sending support mail to superadmin by {current_user.email}")
    
    try:
        subject = f"Help and Support feedback from {current_user.email}"
        body = data.content
        support_email = "jmolina@conversia-ai.io"
        send_email(support_email, subject, body)

        logger.info("Support email sent successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Support email sent successfully",
                "data": None
            }
        )
    
    except HTTPException as http_exe:
        logger.warning(f"Support request failed: {http_exe.detail}")
        raise http_exe

    except Exception as e:
        logger.error(f"Error sending support email: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail={
                "status": "success",
                "message": "Internal Server Error",
                "data": None
            }
        )
