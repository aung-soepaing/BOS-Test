import os
from datetime import timedelta


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def configure_app(app):
    app_env = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "production")).strip().lower()
    is_production = app_env == "production"

    flask_secret_key = os.getenv("FLASK_SECRET_KEY", "").strip()
    if not flask_secret_key and is_production:
        raise ValueError("FLASK_SECRET_KEY must be set in production.")
    app.secret_key = flask_secret_key or "dev-only-change-me"
    session_timeout_minutes = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=session_timeout_minutes)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    app.config["SESSION_COOKIE_SECURE"] = env_bool("SESSION_COOKIE_SECURE", is_production)
    return {"app_env": app_env, "is_production": is_production}


def configure_database(app):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",
        },
    }
