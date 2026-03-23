from flask import request, session

def register_lifecycle_hooks(app, is_admin_username):
    @app.before_request
    def sync_admin_flag():
        username = session.get("user")
        if username:
            if session.get("auth_provider") == "entra":
                session["is_admin"] = bool(session.get("entra_is_admin", False))
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