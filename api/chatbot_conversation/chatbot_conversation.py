import json
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from models.conversation_models import ChatBotConversation, ChatBotMessages
from logger import *
from models.courses_models import CourseConvMessage, CourseConversation
from schemas.chatbot_schema import ChatBotConversationResponse, ChatBotMessageResponse
from api.roleplay_assistant.general_chatbot import GeneralChatBot
from schemas.course_schema import CourseConversationResponse, CourseMessageResponse

chatbot = GeneralChatBot()

async def new_conversation(request, id, db, current_user):
    logger.info(f"Generating new conversation for {current_user.email}")

    url_path = str(request.url.path)

    try:
        if "courses" in url_path.lower():
            conv = CourseConversation(
                title="New Chat",
                course_id=id,
                created_by=current_user.id,
                last_updated_by=current_user.id
            )

            response_model = CourseConversationResponse

        else:
            conv = ChatBotConversation(
                user_id=current_user.id,
                title="New Chat",
                created_by=current_user.email,
                last_updated_by=current_user.email
            )

            response_model = ChatBotConversationResponse

        db.add(conv)
        db.commit()
        db.refresh(conv)

        conversation = response_model.from_orm_model(conv).model_dump()
        conversation["id"] = str(conversation["id"])

        logger.info(f"New conversation generated successfully for user {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "New conversation generated successfully",
                "data": conversation
            }
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while generationg new conversation",
                "data": None
            }
        )


async def get_conversations(request, id, db, current_user):
    logger.info(f"Fetching conversation list of user: {current_user.email}")

    url_path = str(request.url.path)
    try:
        if "courses" in url_path:
            conversations = db.query(CourseConversation).filter(
                CourseConversation.course_id == id,
                CourseConversation.created_by == current_user.id
            ).order_by(
                CourseConversation.last_updated_at.desc()
            ).all()

            response_model = CourseConversationResponse

        else:
            conversations = db.query(ChatBotConversation).filter_by(
                user_id=current_user.id
            ).order_by(
                ChatBotConversation.last_updated_at.desc()
            ).all()

            response_model = ChatBotConversationResponse
        conversations = [
            response_model.from_orm_model(conversation).model_dump()
            for conversation in conversations
        ]

        logger.info("Conversation list fetched successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": f"Conversation list fetched successfully for user: {current_user.email}",
                "data": conversations
            }
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while fetching list conversations",
                "data": None
            }
        )


async def get_conversation(conversation_id, request, db, current_user):
    logger.info(f"Fetching conversation with conversation id: {conversation_id} for user {current_user.email}")

    url_path = str(request.url.path)

    try:
        if "courses" in url_path:
            messages = db. query(CourseConvMessage).filter_by(cs_conv_id=conversation_id).all()
            response_model = CourseMessageResponse
        else:
            messages = db.query(ChatBotMessages).filter_by(conversation_id=conversation_id).order_by(ChatBotMessages.created_at).all()
            response_model = ChatBotMessageResponse
        messages = [response_model.model_validate(message).model_dump() for message in messages]

        logger.info(f"Conversation with conversation id: {conversation_id} for user {current_user.email} fetched successfully")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Conversation fetched successfully",
                "data": messages
            }
        )
    
    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while fetching conversation",
                "data": None
            }
        )


async def save_message(conversation_id, message, request=None, db = None, current_user=None):
    logger.info(f"Adding message in conversation id: {conversation_id} by user {current_user.email}")

    url_path = str(request.url.path) if request else ""
    try:
        sender = getattr(message, "sender", getattr(message, "role", None))
        content = getattr(message, "message", getattr(message, "content", None))

        if not content or not content.strip():
            return  # skip empty messages

        if "courses" in url_path  or getattr(message, "is_course", False):
            msg = CourseConvMessage(
                cs_conv_id=conversation_id,
                sender=sender,
                message=content
            )

        else:
            msg = ChatBotMessages(
                conversation_id=conversation_id,
                role=message.role,
                content=message.content,
                source_file_key=message.source_file_key,
                created_by=current_user.email
            )

        db.add(msg)
        db.commit()
        db.refresh(msg)

        logger.info(f"Message added successfully by user {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Message added successfully",
                "data": {"id": msg.id}
            }
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "An error occured while adding message in conversation",
                "data": None
            }
        )
