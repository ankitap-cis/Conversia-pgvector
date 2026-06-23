import json
from typing import List, Literal, Optional, Union
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session
from api.auth.permission import require_permission
from api.roleplay.general_support import general_support
from api.roleplay.roleplay_session import (
    export_debrief_report, 
    save_debrief_report, 
    submit_roleplay_session, 
    get_roleplay_sessions,
    get_roleplay_session,
    download_roleplay_session,
    team_performance_dashboard,
    team_performance_graphs
)
from connection import get_db
from schemas.roleplay_schema import AssignBulkScenarioForm, AssignEvaluationCriteriaForm, DebriefReportSchema, PersonaForm, RoleplaySessionCreate, ScenarioForm, AssignScenarioForm, SupportForm
from utils.utils import check_admin_role, get_current_user
from .roleplay import (
    create_ai_scenario,
    create_persona, 
    edit_persona, 
    get_personas, 
    get_persona,
    delete_persona, 
    create_scenario, 
    edit_scenario, 
    get_scenarios, 
    get_scenario,
    delete_scenario,
    delete_persona_scenario,
    assign_scenario,
    assign_bulk_scenario,
    fetch_assigned_scenarios,
    remove_user_scenario
)
from logger import *


roleplay_router = APIRouter()


@roleplay_router.post("/create-persona")
async def create_persona_api(
    thumbnail: str = Form(...),
    role: str = Form(...),
    primary_goal: str = Form(...),
    challenges: str = Form(...),
    objections: str = Form(...),
    motivations: str = Form(...),
    fears: str = Form(...),
    communication_style: str = Form(...),
    behavioral_tendencies: str = Form(...),
    avatar_image: Optional[Union[UploadFile, str]] = File(None),
    avatar_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = require_permission("persona.create")
):
    persona_data = PersonaForm(
        thumbnail=thumbnail,
        role=role,
        primary_goal=primary_goal,
        challenges=challenges,
        objections=objections,
        motivations=motivations,
        fears=fears,
        communication_style=communication_style,
        behavioral_tendencies=behavioral_tendencies,
        avatar_id=avatar_id
    )
    return await create_persona(persona_data, avatar_image, db, current_user)


@roleplay_router.put("/edit-persona/{persona_id}")
async def edit_persona_api(
    persona_id: int,
    thumbnail: str = Form(...),
    role: str = Form(...),
    primary_goal: str = Form(...),
    challenges: str = Form(...),
    objections: str = Form(...),
    motivations: str = Form(...),
    fears: str = Form(...),
    communication_style: str = Form(...),
    behavioral_tendencies: str = Form(...),
    avatar_image: Optional[Union[UploadFile, str]] = File(None),
    avatar_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = require_permission("persona.update")
):
    persona_data = PersonaForm(
        thumbnail=thumbnail,
        role=role,
        primary_goal=primary_goal,
        challenges=challenges,
        objections=objections,
        motivations=motivations,
        fears=fears,
        communication_style=communication_style,
        behavioral_tendencies=behavioral_tendencies,
        avatar_id=avatar_id
    )
    return await edit_persona(persona_id, persona_data, avatar_image, db, current_user)


@roleplay_router.get("/get-personas")
async def get_personas_api(search_query: Optional[str] = None, limit: int = 10, offset: int = 0, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("persona.list")):
    return await get_personas(search_query, limit, offset, db, current_user)


@roleplay_router.get("/get-persona/{persona_id}")
async def get_persona_api(persona_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_persona(persona_id, db, current_user)


@roleplay_router.delete("/delete-persona/{persona_id}")
async def delete_persona_api(persona_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("persona.delete")):
    return await delete_persona(persona_id, db, current_user)


@roleplay_router.post("/create-scenario")
async def create_scenario_api(
    title: str = Form(...),
    description: str = Form(...), 
    ai_trainer_opening: str = Form(...),
    selling_methodology: Optional[str] = Form(None),  # Optional field
    ideal_sales_outcome: str = Form(...),
    topics_to_cover: str = Form(...),
    current_state: str = Form(...),
    barriers_to_change: str = Form(...),
    critical_questions: str = Form(...),
    persona_id: int = Form(...),
    evaluation_id: int = Form(...),
    scenario_image: Optional[Union[UploadFile, str]] = File(None),
    scenario_file: Optional[Union[UploadFile, str]] = File(None), 
    db: Session = Depends(get_db), 
    current_user: Session = Depends(get_current_user),
    _ = require_permission("scenario.create")
):
    
    scenario_data = ScenarioForm(
        current_state=current_state,
        topics_to_cover=topics_to_cover,
        persona_id=persona_id,
        evaluation_id=evaluation_id,
        barriers_to_change=barriers_to_change,
        selling_methodology=selling_methodology,
        ideal_sales_outcome=ideal_sales_outcome,
        ai_trainer_opening=ai_trainer_opening,
        title=title,
        description=description,
        critical_questions=critical_questions
    )

    return await create_scenario(scenario_data, scenario_image,scenario_file, db, current_user)


@roleplay_router.put("/edit-scenario/{scenario_id}")
async def edit_scenario_api(
    scenario_id: int, 
    title: str = Form(...),
    description: str = Form(...), 
    ai_trainer_opening: str = Form(...),
    selling_methodology: Optional[str] = Form(None),
    ideal_sales_outcome: str = Form(...),
    topics_to_cover: str = Form(...),
    current_state: str = Form(...),
    barriers_to_change: str = Form(...),
    persona_id: int = Form(...),
    evaluation_id: int = Form(...),
    critical_questions: str = Form(...),
    scenario_image: Union[UploadFile, str] = File(None),
    scenario_file: Optional[Union[UploadFile, str, None]] = File(None),
    db: Session = Depends(get_db), 
    current_user: Session = Depends(get_current_user),
    _ = require_permission("scenario.update")
):
    scenario_data = ScenarioForm(
        current_state=current_state,
        topics_to_cover=topics_to_cover,
        persona_id=persona_id,
        evaluation_id=evaluation_id,
        barriers_to_change=barriers_to_change,
        selling_methodology=selling_methodology,
        ideal_sales_outcome=ideal_sales_outcome,
        ai_trainer_opening=ai_trainer_opening,
        title=title,
        description=description,
        critical_questions=critical_questions
    )
    return await edit_scenario(scenario_id, scenario_data, scenario_image, scenario_file, db, current_user)


@roleplay_router.get("/get-scenarios")
async def get_scenarios_api(search_query: Optional[str] = None, limit: int = 10, offset: int = 0, source: Literal["home", "settings"] = Query("home"),  db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("scenario.list")):
    return await get_scenarios(search_query, limit, offset, source, db, current_user)


@roleplay_router.get("/get-scenario/{scenario_id}")
async def get_scenario_api(scenario_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await get_scenario(scenario_id, db, current_user)


@roleplay_router.delete("/delete-scenario/{scenario_id}")
async def delete_scenario_api(scenario_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("scenario.delete")):
    return await delete_scenario(scenario_id, db, current_user)

@roleplay_router.delete("/delete-persona-scenario/{scenario_id}")
async def delete_persona_scenario_api(scenario_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await delete_persona_scenario(scenario_id, db, current_user)

@roleplay_router.post("/assign-scenario")
async def assign_scenario_api(scenario: AssignScenarioForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("scenario.assign")):
    return await assign_scenario(scenario, db, current_user)


@roleplay_router.post("/assign-bulk-scenario/{user_id}")
async def assign_bulk_scenario_api(user_id: int, scenario_form: AssignBulkScenarioForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("scenario.bulk_assign")):
    return await assign_bulk_scenario(user_id, scenario_form, db, current_user)


@roleplay_router.get("/{user_id}/assigned-scenarios")
async def fetch_assigned_scenarios_api(user_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("scenario.get_assigned")):
    return await fetch_assigned_scenarios(user_id, db, current_user)


@roleplay_router.delete("/{user_id}/remove-scenario/{scenario_id}")
async def remove_user_scenario_api(user_id: int, scenario_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user), _ = require_permission("scenario.remove_assigned")):
    return await remove_user_scenario(user_id, scenario_id, db, current_user)


@roleplay_router.post("/support")
async def general_support_api(data: SupportForm, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await general_support(data, db, current_user)


@roleplay_router.post("/submit-roleplay-session/{bot_state_id}")
async def submit_roleplay_session_api(bot_state_id: str, session_data: RoleplaySessionCreate, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await submit_roleplay_session(bot_state_id, session_data, db, current_user)


# role permission left
# Retrieves roleplay sessions based on current user
@roleplay_router.get("/get-roleplay-sessions")
async def get_roleplay_sessions_api(
    view_mode: str = "graph", 
    filters: List[str] = Query(default=["Average Score"]), 
    time_range: Optional[str] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db), 
    current_user: Session = Depends(get_current_user),
    _ = require_permission("roleplay_session.list")):
    return await get_roleplay_sessions(view_mode, filters, time_range, user_id, db, current_user)


@roleplay_router.get("/get-roleplay-session/{session_id}")
async def get_roleplay_session_api(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user),
    _ = require_permission("roleplay_session.get")
):
    return await get_roleplay_session(session_id, db, current_user)


@roleplay_router.post("/export-roleplay-conversation/{session_id}")
async def download_roleplay_session_api(
    session_id: int,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
):
    return await download_roleplay_session(session_id, user_id, db, current_user)


@roleplay_router.post("/sessions/{session_id}/debrief")
async def save_debrief_report_api(session_id: int, report_data: DebriefReportSchema, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await save_debrief_report(session_id, report_data, db, current_user)


@roleplay_router.get("/export-debrief-report/{session_id}")
async def export_debrief_report_api(session_id: int, db: Session = Depends(get_db), current_user: Session = Depends(get_current_user)):
    return await export_debrief_report(session_id, db, current_user)


@roleplay_router.get("/team-performance-dashboard")
async def team_performance_dashboard_api(
    search_query: Optional[str] = None,
    filters: List[str] = Query(default=["Average Score"]),
    role_filter: Optional[str] = None,
    time_range: Optional[str] = None,
    team_filter: Optional[str] = None,
    limit: int = 10, offset: int = 0,
    db: Session = Depends(get_db), 
    current_user: Session = Depends(get_current_user),
    _ = require_permission("team_performance.view")
):
    return await team_performance_dashboard(search_query, filters, role_filter, team_filter, time_range, limit, offset, db, current_user)


@roleplay_router.get("/team-performance-graph")
async def team_performance_graphs_api(
    filters: List[str] = Query(default=["Average Score"]),
    role_filter: Optional[str] = None,
    time_range: Optional[str] = None,
    team_filter: Optional[str] = None,
    db: Session = Depends(get_db), 
    current_user: Session = Depends(get_current_user),
    _ = require_permission("team_performance.view")
):
    return await team_performance_graphs(filters, role_filter, team_filter, time_range, db, current_user)

@roleplay_router.post("/create-ai-scenario")
async def create_ai_scenario_api(
    scenario_persona_data: str = Form(...),
    avatar_image: str = Form(...),
    scenario_image: Optional[Union[UploadFile, str]] = File(None),
    scenario_file: Optional[Union[UploadFile, str]] = File(None),
    evaluation_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Session = Depends(get_current_user)
    #_ = require_permission("scenario.create")
):
    return await create_ai_scenario(scenario_persona_data, avatar_image,scenario_image, scenario_file,evaluation_id, db, current_user)
