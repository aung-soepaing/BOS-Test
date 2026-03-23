"""Startup and bootstrap helpers for local execution."""

import os
from werkzeug.security import generate_password_hash
from auth_core import ensure_admin_table_exists, get_break_glass_admin_username
from config import env_bool
from extensions import db
from models import AdminUser, User2

def seed_users():
    """Seed the break-glass admin account and admin role records."""

    ensure_admin_table_exists()
    break_glass_admin = get_break_glass_admin_username()
    # Only seed the admin account if it doesn't already exist.
    existing_admin = User2.query.filter_by(username=break_glass_admin).first()
    if not existing_admin:
        admin_password = os.getenv("ADMIN_PASSWORD")
        if not admin_password:
            raise ValueError("ADMIN_PASSWORD environment variable is not set.")
        hashed_pw = generate_password_hash(admin_password)
        new_admin = User2(username=break_glass_admin, password_hash=hashed_pw)
        db.session.add(new_admin)

    # Ensure base admin is always marked as admin role.
    if not AdminUser.query.filter_by(username=break_glass_admin).first():
        db.session.add(AdminUser(username=break_glass_admin))

    db.session.commit()


def initialize_database(app):
    """Create tables and seed required startup data."""

    with app.app_context():
        db.create_all()
        seed_users()


def run_dev_server(app, is_production):
    """Run the Flask development server using environment settings."""

    debug_mode = env_bool("FLASK_DEBUG", False) and not is_production
    host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=debug_mode)