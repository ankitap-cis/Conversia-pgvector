import os
import tempfile
from fastapi import HTTPException, status
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from fastapi.responses import StreamingResponse
from io import BytesIO
from logger import *
from models.users import User
from utils.utils import send_email


env = Environment(loader=FileSystemLoader("templates"))


async def generate_precall_plan_pdf_bytes(sections) -> bytes:
    template = env.get_template("export_precall_plan.html")
    html_out = template.render(sections=sections)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        HTML(string=html_out).write_pdf(f.name)
        f.seek(0)
        pdf_bytes = f.read()

    os.remove(f.name)
    return pdf_bytes


async def generate_debrief_report_pdf_bytes(section) -> bytes:
    template = env.get_template("debrief_report.html")
    html_out = template.render(section=section)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        HTML(string=html_out).write_pdf(f.name)
        f.seek(0)
        pdf_bytes = f.read()

    os.remove(f.name)
    return pdf_bytes


async def export_precall_plan_report(sections, current_user):
    logger.info(f"Precall plan report exported by {current_user.email}")
    try:
        pdf_bytes = await generate_precall_plan_pdf_bytes(sections)
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=Precall-Report.pdf"}
        )
    except Exception as e:
        logger.error(f"Error exporting report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Could not export report",
                "data": None
            }
        )


async def send_feedback_report(sections, feedback, db, current_user):
    logger.info(f"Sending Precall plan feedback by {current_user.email}")
    try:
        pdf_bytes = await generate_precall_plan_pdf_bytes(sections)

        await send_email_with_feedback(
            feedback=feedback,
            pdf_bytes=pdf_bytes,
            db= db,
            current_user_email=current_user.email
        )

        return {"status": "success", "message": "Feedback sent with PDF attached."}

    except Exception as e:
        logger.error(f"Failed to send feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to send feedback email.",
                "data": None
            }
        )


async def send_debrief_feedback_report(sections, feedback, db, current_user):
    logger.info(f"Sending Precall plan feedback by {current_user.email}")
    try:
        pdf_bytes = await generate_debrief_report_pdf_bytes(sections)

        await send_email_with_feedback(
            feedback=feedback,
            pdf_bytes=pdf_bytes,
            db= db,
            current_user_email=current_user.email
        )

        return {"status": "success", "message": "Feedback sent with PDF attached."}

    except Exception as e:
        logger.error(f"Failed to send feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to send feedback email.",
                "data": None
            }
        )


async def send_email_with_feedback(feedback: str, pdf_bytes: bytes, db, current_user_email: str):
    subject = f"Pre-call Plan Feedback from {current_user_email}"
    email = "jmolina@conversia-ai.io"

    # Email content
    body = f"""
        User: {current_user_email}
        Feedback: {feedback}
    """

    # Send email
    send_email(email, subject, body, attachment=pdf_bytes)
