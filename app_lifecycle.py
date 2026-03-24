from flask import request, session
from auth_core import is_sso_user_admin

def register_lifecycle_hooks(app, is_admin_username):
    @app.before_request
    def sync_admin_flag():
        username = session.get("user")
        if username:
            if session.get("auth_provider") == "entra":
                # Re-check SSO user role from database to reflect role changes immediately
                session["is_admin"] = is_sso_user_admin(username)
                session["entra_is_admin"] = session["is_admin"]
            else:
                session["is_admin"] = is_admin_username(username)

    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response