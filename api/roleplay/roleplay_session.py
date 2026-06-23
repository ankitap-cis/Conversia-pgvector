from collections import defaultdict
import re
import tempfile
from fastapi import HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import and_, func, or_
from api.precall_plan.export_precall_plan import generate_debrief_report_pdf_bytes
from models.roleplay_models import DebriefReport, DebriefSkillScore, EvaluationField, RoleplaySession, RoleplaySessionMessage
from logger import *
from models.users import Profile, User
from schemas.roleplay_schema import RoleplaySessionResponse
from datetime import datetime as dt, timedelta
from sqlalchemy.orm import joinedload, selectinload


async def submit_roleplay_session(bot_state_id, session_data, db, current_user):
    logger.info(f"Submitting roleplay session for user: {current_user.email}")
    try:
        session = RoleplaySession(
            bot_state_id=session_data.bot_state_id,
            performer_id=current_user.id,
            organization_id=current_user.organization_id,
            scenario_id=session_data.scenario_id,
            created_by=current_user.email,
            last_updated_by=current_user.email
        )

        db.add(session)
        db.flush()  # To get session.id

        for msg in session_data.messages:
            db.add(RoleplaySessionMessage(
                session_id=session.id,
                sender=msg.sender,
                message=msg.message
            ))

        db.commit()

        logger.info(f"Roleplay session {session.id} submitted successfully")
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Roleplay session submitted successfully", 
                "data": {
                    "session_id": session.id,
                    "bot_state_id": bot_state_id              
                }
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error submitting roleplay session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to submit roleplay session",
                "data": None
            }
        )


def get_start_date(time_range: str):
    today = dt.utcnow().date()
    if time_range == "Last 7 days":
        return today - timedelta(days=6)
    elif time_range == "Last 30 days":
        return today - timedelta(days=29)
    elif time_range == "Last 90 days":
        return today - timedelta(days=89)
    elif time_range == "Last 6 months":
        return today - timedelta(days=182)
    elif time_range == "Last year":
        return today - timedelta(days=364)
    return None


async def get_roleplay_sessions(view_mode, eval_filters, time_range, user_id, db, current_user):
    logger.info(f"Fetching roleplay sessions for user: {current_user.email}")
    try:
        sessions_data = []
        graph_data = []
        score_sum = 0
        valid_score_count = 0
        pass_count = 0


        # Determine target user
        if user_id is None:
            target_user_id = current_user.id
        else:
            # Permission check
            if current_user.user_type not in ['org_admin', 'content_creator', 'exec_viewer', "field_manager"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status": "failure",
                        "message": "You are not allowed to view other users' sessions",
                        "data": None
                    }
                )
            target_user_id = user_id

        start_date = get_start_date(time_range)

        sessions = db.query(RoleplaySession).options(
            joinedload(RoleplaySession.debrief_report),
            joinedload(RoleplaySession.scenario)
        ).filter(RoleplaySession.performer_id == target_user_id).order_by(
            RoleplaySession.created_at.desc()
        )

        if start_date:
            sessions = sessions.filter(RoleplaySession.created_at >= start_date)

        sessions = sessions.all()

        if not sessions:
            logger.warning("No roleplay sessions found")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "success",
                    "message": "No roleplay sessions found",
                    "data": None
                }
            )

        for session in sessions:
            debrief = session.debrief_report
            ai_score = None

            if debrief and debrief.ai_score is not None:
                ai_score = debrief.ai_score
                score_sum += ai_score
                valid_score_count += 1
                if ai_score >= 8:
                    pass_count += 1

        if view_mode == 'graph':
            logger.info("Fetching roleplay sessions in graph view mode")

            all_dates_set = set()
            raw_graph_data = []

            # Collecting data per evaluation title and gather all dates
            for eval_title in eval_filters:
                if eval_title == "Average Score":
                    query = db.query(
                        func.date(RoleplaySession.created_at).label('date'),
                        func.avg(DebriefReport.ai_score).label('average_score')
                    ).join(
                        DebriefReport, RoleplaySession.id == DebriefReport.session_id
                    ).filter(
                        RoleplaySession.performer_id == target_user_id
                    )
                else:
                    query = db.query(
                        func.date(RoleplaySession.created_at).label('date'),
                        func.avg(DebriefSkillScore.score).label('average_score')
                    ).join(
                        DebriefReport, RoleplaySession.id == DebriefReport.session_id
                    ).join(
                        DebriefSkillScore, DebriefReport.id == DebriefSkillScore.debrief_report_id
                    ).filter(
                        RoleplaySession.performer_id == target_user_id,
                        DebriefSkillScore.skill_name == eval_title
                    )

                if start_date:
                    query = query.filter(RoleplaySession.created_at >= start_date)

                results = query.group_by(
                    func.date(RoleplaySession.created_at)
                ).order_by(
                    func.date(RoleplaySession.created_at)
                ).all()

                date_score_map = {}
                for result in results:
                    date_str = result.date.isoformat()
                    all_dates_set.add(date_str)
                    date_score_map[date_str] = round(float(result.average_score), 1) if result.average_score is not None else None

                raw_graph_data.append({
                    "title": "Average Score" if eval_title == "Average Score" else eval_title,
                    "data_map": date_score_map
                })

            # Normalize all graph lines to have all the same dates
            all_dates_sorted = sorted(list(all_dates_set))
            for item in raw_graph_data:
                normalized_data = []
                for date in all_dates_sorted:
                    normalized_data.append({
                        "date": date,
                        "average_score": item["data_map"].get(date, None)
                    })
                graph_data.append({
                    "title": item["title"],
                    "data": normalized_data
                })

        elif view_mode == 'sessions':
            logger.info("Fetching roleplay sessions in detailed view mode")

            for session in sessions:
                top_skill = None
                low_skill = None
                debrief = session.debrief_report if session.debrief_report else None
                skill_scores = debrief.skill_scores if debrief and debrief.skill_scores else []
                if skill_scores:
                    top_skill = max(skill_scores, key=lambda s: s.score, default=None)
                    low_skill = min(skill_scores, key=lambda s: s.score, default=None)

                sessions_data.append({
                    "session_id": session.id,
                    "scenario_title": session.scenario.title if session.scenario else None,
                    "ai_score": debrief.ai_score if debrief and debrief.ai_score is not None else None,
                    "created_at": session.created_at.isoformat(),
                    "top_skill": {
                        "skill_name": top_skill.skill_name if top_skill else None,
                        "score": top_skill.score if top_skill else None
                    },
                    "low_skill": {
                        "skill_name": low_skill.skill_name if low_skill else None,
                        "score": low_skill.score if low_skill else None
                    }
                })

        total_sessions = len(sessions)
        average_ai_score = round(score_sum / valid_score_count, 1) if valid_score_count > 0 else 0.0
        pass_rate = round((pass_count / valid_score_count) * 100, 1) if valid_score_count > 0 else 0.0
        performer = (
            db.query(Profile.full_name)
            .select_from(User)
            .join(Profile, Profile.user_id == User.id)
            .filter(User.id == target_user_id)
            .scalar()
        )


        dashboard_metrics = {
            "fullname": performer,
            "average_ai_score": average_ai_score,
            "total_sessions": total_sessions,
            "pass_rate": f"{pass_rate}%"
        }

        logger.info(f"Fetched {len(sessions_data)} roleplay sessions for user: {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Roleplay sessions fetched successfully",
                "data": {
                    "dashboard": dashboard_metrics,
                    "sessions": sessions_data,
                    "graph_data": graph_data
                }
            }
        )

    except Exception as e:
        logger.error(f"Error fetching roleplay sessions: {e}")
        raise HTTPException(    
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to fetch roleplay sessions",
                "data": None
            }
        )


async def get_roleplay_session(session_id, db, current_user):
    logger.info(f"Fetching roleplay session by user: {current_user.email}")
    try:
        session = db.query(RoleplaySession).filter(
            RoleplaySession.performer_id == current_user.id, RoleplaySession.id == session_id
        ).first()

        if not session:
            logger.warning("No roleplay session found")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "success",
                    "message": "No roleplay sessions found",
                    "data": None
                }
            )

        session_data = RoleplaySessionResponse.model_validate({
                **session.__dict__,
                "messages": [msg.__dict__ for msg in session.messages]
            }).model_dump()
        

        logger.info("Roleplay session fetched successfully.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Roleplay session fetched successfully",
                "data": session_data
            }
        )

    except Exception as e:
        logger.error(f"Error fetching roleplay session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to fetch roleplay session",
                "data": None
            }
        )


async def download_roleplay_session(session_id, user_id, db, current_user):
    logger.info(f"Downloading roleplay session by user: {current_user.email}")
    try:
        # Determine target user
        if user_id is None:
            target_user_id = current_user.id
        else:
            # Permission check
            if current_user.user_type not in ['org_admin', 'content_creator', 'exec_viewer', "field_manager"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status": "failure",
                        "message": "You are not allowed to view other users' sessions",
                        "data": None
                    }
                )
            target_user_id = user_id

        session = db.query(RoleplaySession).filter(
            RoleplaySession.performer_id == target_user_id, RoleplaySession.id == session_id
        ).first()

        if not session:
            logger.warning("No roleplay session found")
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "success",
                    "message": "No roleplay sessions found",
                    "data": None
                }
            )

        session_data = RoleplaySessionResponse.model_validate({
                **session.__dict__,
                "messages": [msg.__dict__ for msg in session.messages]
            }).model_dump()

        # Format header
        lines = [
            "Conversation Transcript",
            f"Exported at: {dt.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "Messages:"
        ]

        # Format each message
        for msg in session_data["messages"]:
            sender = msg.get("sender", "unknown").capitalize()
            message = msg.get("message", "").replace("\n", "\n    ")  # indent newlines for clarity
            lines.append(f"{sender}:\n    {message}\n")

        lines.append("--- End of Conversation ---")

        # Write to temporary text file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as tmp:
            tmp.write("\n".join(lines))
            file_path = tmp.name

        return FileResponse(
            path=file_path,
            filename="conversation_transcript.txt",
            media_type="text/plain"
        )

    except Exception as e:
        logger.error(f"Error fetching roleplay session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to download roleplay session",
                "data": None
            }
        )


async def save_debrief_report(session_id, report_data, db, current_user):
    logger.info(f"Saving debrief report for session ID: {session_id} by user: {current_user.email}")
    try:
        # Checking if session exists
        session = db.query(RoleplaySession).filter(RoleplaySession.id == session_id).first()
        if not session:
            logger.error(f"Roleplay session {session_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "status": "failure",
                    "message": f"Roleplay session {session_id} not found",
                    "data": None
                }
            )

        # Checking if debrief already exists for this session
        existing_debrief = db.query(DebriefReport).filter(DebriefReport.session_id == session_id).first()
        if existing_debrief:
            logger.warning(f"Debrief report for session {session_id} already exists")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": "failure",
                    "message": f"Debrief report for session {session_id} already exists",
                    "data": None
                }
            )

        debrief = DebriefReport(
            session_id=session_id,
            scenario_title=report_data.scenario_title,
            ai_score=report_data.ai_score,
            pass_score=report_data.pass_score,
            general_insights=report_data.general_insights,
            created_by=current_user.email,
            last_updated_by=current_user.email
        )

        db.add(debrief)
        db.flush()  # To get the ID
        logger.info(f"Debrief report created with ID: {debrief.id}")
        
        for skill in list(report_data.skill_scores):  # make a copy to avoid mutation issues
            db.add(DebriefSkillScore(
                debrief_report_id=debrief.id,
                skill_name=str(skill.name),
                score=int(skill.score),
                comment=str(skill.comment) if skill.comment else None
            ))

        db.commit()
        logger.info(f"Debrief report for session {session_id} saved successfully")

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "success",
                "message": "Debrief report saved successfully",
                "data": {
                    "debrief_id": debrief.id,
                    "session_id": session_id
                }
            }
        )
    except HTTPException as http_exe:
        raise http_exe

    except Exception as e:
        db.rollback()
        logger.error(f"Error saving debrief report for session {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to save debrief report",
                "data": None
            }
        )


async def export_debrief_report(session_id, db, current_user):
    logger.info(f"Exporting debrief report for session ID: {session_id} by user: {current_user.email}")

    debrief_report = db.query(DebriefReport).filter(DebriefReport.session_id == session_id).first()
    if not debrief_report:
        logger.error(f"Debrief report for session {session_id} not found")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "status": "success",
                "message": f"Debrief report for session {session_id} not found",
                "data": None
            }
        )

    # Preparing session data for PDF generation
    session = {
        "overall_feedback": {
            "scenario_title": debrief_report.scenario_title,
            "ai_score": debrief_report.ai_score,
            "pass_score": debrief_report.pass_score,
            "general_feedback": debrief_report.general_insights
        },
        "evaluation": {
            skill.skill_name: {
                "score": skill.score,
                "explanation": skill.comment
            }
            for skill in debrief_report.skill_scores
        }
    }
    pdf_bytes = await generate_debrief_report_pdf_bytes(session)
    if not pdf_bytes:
        logger.error("Failed to generate PDF bytes for debrief report")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to generate PDF for debrief report",
                "data": None
            }
        )

     # Save the PDF to a temporary file for download
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(pdf_bytes)
        temp_pdf_path = temp_pdf.name

    logger.info(f"Debrief report for session {session_id} exported successfully")
    return FileResponse(
        path=temp_pdf_path,
        filename=f"debrief_report_{session_id}.pdf",
        media_type="application/pdf"
    )


async def team_performance_dashboard(search_query, filters, role_filter, team_filter, time_range, limit, offset, db, current_user):
    logger.info(f"Fetching team performance dashboard for user: {current_user.email}")
    try:
        users_query = (
            db.query(User)
            .join(Profile)
            .filter(User.organization_id == current_user.organization_id)
        )
        if current_user.user_type == "field_manager":
            users_query = (
                users_query
                .filter(
                    or_(
                        User.id == current_user.id,  # field manager himself
                        and_(
                            User.user_type == "sales_reps",
                            User.field_manager_id == current_user.id
                        )
                    )
                )
            )
        
        if current_user.user_type in ["content_creator", "exec_viewer"]:
            users_query = users_query.filter(User.user_type != "org_admin")

        if role_filter:
            users_query = users_query.filter(User.user_type == role_filter)
        
        if team_filter:
            if team_filter == "unassigned":
                if team_filter:
                    users_query = users_query.filter(User.user_type == "sales_reps", User.field_manager_id.is_(None))
    
            else:  
                users_query = users_query.filter(or_(User.id == team_filter, User.field_manager_id == team_filter))

        # Filtering sessions for leaderboard name filter
        if search_query:
            users_query = users_query.filter(
                Profile.full_name.ilike(f"%{search_query}%")
            )

        total_users = users_query.count()
        users = (
            users_query.all()
        )
        user_ids = [u.id for u in users]
  
        # =====================================================
        # 🔹 SESSION QUERY (CHANGED: FETCH AFTER USERS)
        # =====================================================
        start_date = get_start_date(time_range)

        sessions_query = (
            db.query(RoleplaySession)
            .options(
                selectinload(RoleplaySession.debrief_report)
                .selectinload(DebriefReport.skill_scores),
                selectinload(RoleplaySession.scenario)
            )
            .filter(
                RoleplaySession.performer_id.in_(user_ids)
            )
        )

        if start_date:
            sessions_query = sessions_query.filter(
                RoleplaySession.created_at >= start_date
            )

        sessions = sessions_query.all()

        sessions_by_user = defaultdict(list)
        for session in sessions:
            sessions_by_user[session.performer_id].append(session)

        total_sessions = 0
        total_score_sum = 0
        total_score_count = 0
        evaluation_category_scores = defaultdict(list)
        active_members = set()

        for user_id, user_sessions in sessions_by_user.items():
            if user_sessions:
                active_members.add(user_id)

            for session in user_sessions:
                total_sessions += 1
                debrief = session.debrief_report
                if debrief and debrief.ai_score is not None:
                    total_score_sum += debrief.ai_score
                    total_score_count += 1
                    for score in debrief.skill_scores:
                        evaluation_category_scores[score.skill_name].append(score.score)

        team_average_score = (
            round(total_score_sum / total_score_count, 1)
            if total_score_count > 0 else 0.0
        )

        category_averages = {
            k: round(sum(v) / len(v), 1)
            for k, v in evaluation_category_scores.items()
        }

        lowest_category = min(category_averages.items(), key=lambda x: x[1], default=(None, 0))
        highest_category = max(category_averages.items(), key=lambda x: x[1], default=(None, 0))

        dashboard_data = {
            "total_sessions": total_sessions,
            "total_users": total_users,
            "active_members": len(active_members),
            "team_average_score": team_average_score,
            "category_averages": category_averages,
            "lowest_category": {
                "category": lowest_category[0],
                "score": lowest_category[1]
            },
            "highest_category": {
                "category": highest_category[0],
                "score": highest_category[1]
            }
        }

        leaderboard = []
        users = users_query.offset(offset).limit(limit).all()

        for user in users:
            user_sessions = sessions_by_user.get(user.id, [])
            scores = []
            category_score_map = defaultdict(list)

            for session in user_sessions:
                debrief = session.debrief_report
                if debrief and debrief.ai_score is not None:
                    scores.append(debrief.ai_score)
                    for skill in debrief.skill_scores:
                        category_score_map[skill.skill_name].append(skill.score)

            avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

            strongest_area = max(
                (
                    (k, round(sum(v) / len(v), 1))
                    for k, v in category_score_map.items()
                ),
                default=(None, 0)
            )

            development_area = min(
                (
                    (k, round(sum(v) / len(v), 1))
                    for k, v in category_score_map.items()
                ),
                default=(None, 0)
            )

            leaderboard.append({
                "id":user.id,
                "name": user.profile.full_name,
                "designation": user.user_type,
                "sessions": len(user_sessions),
                "avg_score": avg_score,
                "strongest_area": {
                    "category": strongest_area[0],
                    "score": strongest_area[1]
                },
                "development_area": {
                    "category": development_area[0],
                    "score": development_area[1]
                },
                "last_session": (
                    max(s.created_at for s in user_sessions).strftime("%b %d, %Y")
                    if user_sessions else None
                )
            })

        leaderboard = sorted(leaderboard, key=lambda x: x["avg_score"], reverse=True)

        logger.info(f"Team performance dashboard fetched successfully by org_admin: {current_user.email}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "success",
                "message": "Team performance dashboard fetched successfully",
                "data": {
                    "dashboard": dashboard_data,
                    "leaderboard": leaderboard  # will be empty if no user matches filter
                }
            }
        )

    except Exception as e:
        logger.error(f"Error fetching team performance dashboard: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "failure",
                "message": "Failed to fetch team performance dashboard",
                "data": None
            }
        )
    

async def team_performance_graphs(
    filters,
    role_filter,
    team_filter,
    time_range,
    db,
    current_user
):
    logger.info(f"Fetching team performance graphs for {current_user.email}")

    try:
        start_date = get_start_date(time_range)

        query = (
            db.query(RoleplaySession)
            .join(User, RoleplaySession.performer_id == User.id)
            .options(
                joinedload(RoleplaySession.debrief_report)
                .joinedload(DebriefReport.skill_scores)
            )
            .filter(User.organization_id == current_user.organization_id)
        )

        if current_user.user_type == "field_manager":
            query = query.filter(
                or_(
                    User.id == current_user.id,  # field manager himself
                    and_(
                        User.user_type == "sales_reps",
                        User.field_manager_id == current_user.id
                    )
                )
            )

        if role_filter:
            query = query.filter(User.user_type == role_filter)

        if team_filter:
            if team_filter == "unassigned":
                query = query.filter(
                    User.user_type == "sales_reps",
                    User.field_manager_id.is_(None)
                )
            else:
                query = query.filter(
                    or_(
                        User.id == team_filter,
                        User.field_manager_id == team_filter
                    )
                )

        if start_date:
            query = query.filter(RoleplaySession.created_at >= start_date)

        sessions = query.all()

        if not sessions:
            return JSONResponse(
                status_code=200,
                content={"graph_data": []}
            )

        # =====================================================
        # BUILD DATE RANGE
        # =====================================================
        all_dates = sorted({s.created_at.date() for s in sessions})
        graph_data = []

        # =====================================================
        # AVERAGE SCORE GRAPH
        # =====================================================
        if "Average Score" in filters:
            daily_avg = defaultdict(list)

            for s in sessions:
                if s.debrief_report and s.debrief_report.ai_score is not None:
                    daily_avg[s.created_at.date()].append(
                        s.debrief_report.ai_score
                    )

            graph_data.append({
                "title": "Team Average Score",
                "data": [
                    {
                        "date": d.strftime("%Y-%m-%d"),
                        "average_score": (
                            round(sum(daily_avg[d]) / len(daily_avg[d]), 1)
                            if d in daily_avg else None
                        )
                    }
                    for d in all_dates
                ]
            })

        # =====================================================
        # SKILL GRAPHS
        # =====================================================
        skills = [f for f in filters if f != "Average Score"]

        skill_map = defaultdict(lambda: defaultdict(list))

        for s in sessions:
            if not s.debrief_report:
                continue
            for skill in s.debrief_report.skill_scores:
                if skill.skill_name in skills:
                    skill_map[skill.skill_name][
                        s.created_at.date()
                    ].append(skill.score)

        for skill in skills:
            graph_data.append({
                "title": skill,
                "data": [
                    {
                        "date": d.strftime("%Y-%m-%d"),
                        "average_score": (
                            round(sum(skill_map[skill][d]) / len(skill_map[skill][d]), 1)
                            if d in skill_map[skill] else None
                        )
                    }
                    for d in all_dates
                ]
            })

        return JSONResponse(
            status_code=200,
            content={"graph_data": graph_data}
        )

    except Exception as e:
        logger.exception("Graph API failed")
        raise HTTPException(
            status_code=500,
            detail="Failed to load graph data"
        )

