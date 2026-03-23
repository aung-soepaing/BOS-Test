import os
from functools import wraps
from flask import abort, session
from extensions import db
from models import AdminUser

_admin_table_checked = False

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