# auth/rbac.py
from typing import Set
from sqlalchemy.orm import Session
from models.rbac_models import Permission, Role, RolePermission, UserRole  # yields a Session

def get_permissions_for_user(db: Session, user_id: int) -> Set[str]:
    
    # Query DB each request. Returns set of permission codes
    rows = db.query(Permission.code).join(RolePermission).join(Role).join(UserRole).filter(UserRole.user_id == user_id).all()
    return {row[0] for row in rows}
