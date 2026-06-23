# auth/permissions.py
from fastapi import Depends, HTTPException, status, Request
from typing import Callable, Optional
from sqlalchemy.orm import Session

from connection import get_db
from utils.utils import get_current_user   # your existing auth dep
from .rbac import get_permissions_for_user

def require_permission(
    permission_code: str,
    resource_owner_check: Optional[Callable[[int, Session, int], bool]] = None,
    resource_param_name: Optional[str] = None
):
    """
    permission_code: e.g. 'courses.update'
    resource_owner_check: optional function(user_id, db, resource_id) -> bool
    resource_param_name: optionally pass the exact path-param name to extract (e.g. "course_id").
    """
    def dependency(
        request: Request,
        current_user = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        # superadmin bypass if your user has this flag
        if getattr(current_user, "is_superadmin", False):
            return True

        # load permissions from DB on every request
        perms = get_permissions_for_user(db, current_user.id)
        if permission_code in perms:
            return True

        # optional ownership check fallback
        if resource_owner_check:
            # if explicit resource_param_name provided, use it; otherwise try common names
            resource_id = None
            if resource_param_name:
                if resource_param_name in request.path_params:
                    try:
                        resource_id = int(request.path_params[resource_param_name])
                    except Exception:
                        resource_id = None
            else:
                for key in ("id", "course_id", "scenario_id", "persona_id", "evaluation_id", "precallplan_id"):
                    if key in request.path_params:
                        try:
                            resource_id = int(request.path_params[key])
                        except Exception:
                            resource_id = None
                        break

            if resource_id is not None and resource_owner_check(current_user.id, db, resource_id):
                return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail={
                "status":"failure",
                "message":"Permission denied",
                "data":None
            }
        )
    return Depends(dependency)


# auth/ownership.py
from sqlalchemy.orm import Session
from models.courses_models import Course  # adapt import path to your project

def owns_course(user_id: int, db: Session, course_id: int) -> bool:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        return False
    return bool(course.owner_id == user_id)