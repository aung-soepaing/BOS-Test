import os
import secrets
from urllib.parse import urlencode
import requests
from flask import flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.security import check_password_hash, generate_password_hash

from auth_helpers import (
    build_entra_state,
    extract_entra_username,
    get_entra_openid_configuration,
    get_entra_redirect_uri,
    is_entra_sso_enabled,
    parse_entra_state,
    validate_entra_id_token,
)
from extensions import db
from models import Metric, User2

def register_auth_routes(app, admin_only, is_admin_username):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if "user" in session:
            return redirect(url_for("index"))

        step = "login"
        error = None

        if request.method == "POST":
            if "username" in request.form and "password" in request.form:
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")

                user = User2.query.filter_by(username=username).first()
                if user and check_password_hash(user.password_hash, password):
                    default_password = f"BOS{username.lower()}*"
                    if password == default_password:
                        session["pending_user"] = username
                        step = "change_password"
                    else:
                        session["user"] = username
                        session["is_admin"] = is_admin_username(username)
                        session["auth_provider"] = "local"
                        session.permanent = True
                        log = Metric(metric_name=username, value=0)
                        db.session.add(log)
                        db.session.commit()
                        return redirect(url_for("index"))
                else:
                    error = "Invalid username or password"

            elif "new_password" in request.form and "confirm_password" in request.form:
                new_password = request.form.get("new_password")
                confirm_password = request.form.get("confirm_password")
                username = session.get("pending_user")

                if not username:
                    return redirect(url_for("login"))

                if new_password != confirm_password:
                    error = "Passwords do not match."
                    step = "change_password"
                else:
                    user = User2.query.filter_by(username=username).first()
                    if user:
                        user.password_hash = generate_password_hash(new_password)
                        db.session.commit()
                        session.pop("pending_user")
                        session["user"] = username
                        session["is_admin"] = is_admin_username(username)
                        session["auth_provider"] = "local"
                        session.permanent = True

                        log = Metric(metric_name=f"{username}_password_changed", value=1)
                        db.session.add(log)
                        db.session.commit()
                        return redirect(url_for("index"))

        return render_template(
            "login.html", step=step, error=error, sso_enabled=is_entra_sso_enabled()
        )

    @app.route("/auth/entra/login")
    def entra_login():
        if not is_entra_sso_enabled():
            flash("SSO is not configured. Contact an administrator.", "error")
            return redirect(url_for("login"))

        nonce = secrets.token_urlsafe(24)
        state = build_entra_state(app.secret_key, nonce)

        try:
            openid_config = get_entra_openid_configuration()
        except Exception:
            flash("Unable to start Microsoft SSO at the moment.", "error")
            return redirect(url_for("login"))

        params = {
            "client_id": os.getenv("ENTRA_CLIENT_ID", "").strip(),
            "response_type": "code",
            "redirect_uri": get_entra_redirect_uri(
                url_for("entra_auth_callback", _external=True)
            ),
            "response_mode": "query",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
        }
        authorize_url = f"{openid_config['authorization_endpoint']}?{urlencode(params)}"
        return redirect(authorize_url)

    @app.route("/auth/entra/callback")
    def entra_auth_callback():
        if not is_entra_sso_enabled():
            flash("SSO is not configured. Contact an administrator.", "error")
            return redirect(url_for("login"))

        returned_state = request.args.get("state")
        if not returned_state:
            flash("Invalid SSO state. Please try logging in again.", "error")
            return redirect(url_for("login"))

        try:
            state_payload = parse_entra_state(app.secret_key, returned_state)
            expected_nonce = state_payload.get("nonce")
            if not expected_nonce:
                raise ValueError("Missing nonce in SSO state payload.")
        except (BadSignature, SignatureExpired, ValueError):
            flash("Invalid or expired SSO state. Please try logging in again.", "error")
            return redirect(url_for("login"))

        if request.args.get("error"):
            details = request.args.get(
                "error_description", "Microsoft sign-in was canceled or failed."
            )
            flash(details, "error")
            return redirect(url_for("login"))

        code = request.args.get("code")
        if not code:
            flash("Microsoft sign-in did not return an authorization code.", "error")
            return redirect(url_for("login"))

        try:
            openid_config = get_entra_openid_configuration()
            token_response = requests.post(
                openid_config["token_endpoint"],
                data={
                    "client_id": os.getenv("ENTRA_CLIENT_ID", "").strip(),
                    "client_secret": os.getenv("ENTRA_CLIENT_SECRET", "").strip(),
                    "code": code,
                    "redirect_uri": get_entra_redirect_uri(
                        url_for("entra_auth_callback", _external=True)
                    ),
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            id_token = token_payload.get("id_token")
            if not id_token:
                raise ValueError("ID token was not returned by Entra ID.")

            claims = validate_entra_id_token(id_token)
            if claims.get("nonce") != expected_nonce:
                raise ValueError("Invalid SSO nonce in ID token.")

            username = extract_entra_username(claims)
            if not username:
                raise ValueError("Unable to determine username from Entra ID token.")

            username = username.strip().lower()
            session["user"] = username
            session["entra_is_user"] = True
            session["entra_is_admin"] = False
            session["is_admin"] = False
            session["auth_provider"] = "entra"
            session.permanent = True

            log = Metric(metric_name=f"{username}_entra_login", value=1)
            db.session.add(log)
            db.session.commit()
        except Exception:
            app.logger.exception("Entra callback failed")
            flash("Microsoft sign-in failed. Please try again or use local login.", "error")
            return redirect(url_for("login"))

        return redirect(url_for("index"))

    @app.route("/auth/diagnostics")
    @admin_only
    def auth_diagnostics():
        auth_provider = session.get("auth_provider")
        username = session.get("user", "Not logged in")

        diagnostics = {
            "username": username,
            "auth_provider": auth_provider,
            "is_admin": session.get("is_admin", False),
            "is_logged_in": "user" in session,
        }

        if auth_provider == "entra":
            diagnostics["entra_info"] = {
                "entra_is_user": session.get("entra_is_user", False),
                "entra_is_admin": session.get("entra_is_admin", False),
                "assignment_model": "Enterprise Application assignment only",
            }

        if auth_provider == "local":
            diagnostics["local_info"] = {
                "status": "Local authentication active",
                "note": "For local users, roles are managed via the /roles admin page",
            }

        if (
            request.accept_mimetypes.get("application/json", 0)
            > request.accept_mimetypes.get("text/html", 0)
        ):
            return jsonify(diagnostics)

        return render_template("auth_diagnostics.html", diagnostics=diagnostics)

    @app.route("/logout")
    def logout():
        auth_provider = session.get("auth_provider")
        session.pop("user", None)
        session.pop("is_admin", None)
        session.pop("auth_provider", None)
        session.pop("entra_is_user", None)
        session.pop("entra_is_admin", None)

        if auth_provider == "entra" and is_entra_sso_enabled():
            try:
                openid_config = get_entra_openid_configuration()
                end_session_endpoint = openid_config.get("end_session_endpoint")
                if end_session_endpoint:
                    logout_url = (
                        f"{end_session_endpoint}?{urlencode({'post_logout_redirect_uri': url_for('login', _external=True)})}"
                    )
                    return redirect(logout_url)
            except Exception:
                pass

        return redirect(url_for("login"))