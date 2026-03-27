import os
from functools import wraps
from flask import abort, session
from extensions import db
from models import AdminUser, SSOUserRole

_admin_table_checked = False
_sso_role_table_checked = False


def _to_bool(value):
    """Normalize mixed DB/session values to strict boolean."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)

def org_only(f):
    """Decorator: block access for 'Demo' account to protected routes."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("user") == "Demo":
            abort(403, description="Demo users cannot access this resource.")
        return f(*args, **kwargs)
    return wrapper

def get_break_glass_admin_username():
    username = os.getenv("BREAK_GLASS_ADMIN_USERNAME", "admin").strip().lower()
    return username or "admin"

def get_admin_usernames():
    raw_admins = os.getenv("ADMIN_USERS", "admin")
    admins = {u.strip().lower() for u in raw_admins.split(",") if u.strip()}
    admins.add(get_break_glass_admin_username())
    return admins

def ensure_admin_table_exists():
    global _admin_table_checked
    if _admin_table_checked:
        return
    try:
        AdminUser.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        return
    _admin_table_checked = True

def is_admin_in_db(username):
    if not username:
        return False
    try:
        ensure_admin_table_exists()
        return (
            AdminUser.query.filter_by(username=username.strip().lower()).first()
            is not None
        )
    except Exception:
        # If table is not available yet, fall back to env-based admin list.
        return False

def is_admin_username(username):
    if not username:
        return False
    normalized = username.strip().lower()
    return normalized in get_admin_usernames() or is_admin_in_db(normalized)

def admin_only(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin", False):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def ensure_sso_user_role_table_exists():
    """Ensure the SSOUserRole table exists in the database."""
    global _sso_role_table_checked
    if _sso_role_table_checked:
        return
    try:
        SSOUserRole.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        return
    _sso_role_table_checked = True


def is_sso_user_admin(username):
    """Check if an SSO user has admin role assigned in the database."""
    if not username:
        return False
    try:
        ensure_sso_user_role_table_exists()
        user_role = SSOUserRole.query.filter_by(username=username.strip().lower()).first()
        return _to_bool(user_role.is_admin) if user_role else False
    except Exception:
        # If table is not available yet, default to non-admin.
        return False


def get_sso_user_role(username):
    """Retrieve the SSOUserRole record for a user, creating one if needed."""
    if not username:
        return None
    try:
        ensure_sso_user_role_table_exists()
        normalized = username.strip().lower()
        user_role = SSOUserRole.query.filter_by(username=normalized).first()
        if not user_role:
            user_role = SSOUserRole(username=normalized, is_admin=False)
            db.session.add(user_role)
            db.session.commit()
        else:
            # Repair non-boolean legacy values (e.g. "False" stored as text).
            normalized_flag = _to_bool(user_role.is_admin)
            if user_role.is_admin != normalized_flag:
                user_role.is_admin = normalized_flag
                db.session.commit()
        return user_role
    except Exception:
        return None


def set_sso_user_admin(username, is_admin):
    """Set admin role for an SSO user."""
    if not username:
        return False
    try:
        ensure_sso_user_role_table_exists()
        normalized = username.strip().lower()
        admin_flag = _to_bool(is_admin)
        user_role = SSOUserRole.query.filter_by(username=normalized).first()
        if not user_role:
            user_role = SSOUserRole(username=normalized, is_admin=admin_flag)
            db.session.add(user_role)
        else:
            user_role.is_admin = admin_flag
        db.session.commit()
        return True
    except Exception:
        return False