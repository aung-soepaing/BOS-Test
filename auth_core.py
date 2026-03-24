import os
from functools import wraps
from flask import abort, session
from extensions import db
from models import AdminUser, SSOUserRole

_admin_table_checked = False
_sso_role_table_checked = False

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
        return user_role.is_admin if user_role else False
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
        user_role = SSOUserRole.query.filter_by(username=normalized).first()
        if not user_role:
            user_role = SSOUserRole(username=normalized, is_admin=is_admin)
            db.session.add(user_role)
        else:
            user_role.is_admin = is_admin
        db.session.commit()
        return True
    except Exception:
        return False