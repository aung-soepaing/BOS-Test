from flask import flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash
from extensions import db
from models import AdminUser, DeviceLog, Metric, SSOUserRole, User2


def register_admin_routes(
    app,
    admin_only,
    ensure_admin_table_exists,
    get_admin_usernames,
    get_break_glass_admin_username,
):
    @app.route("/roles")
    @admin_only
    def roles():
        ensure_admin_table_exists()
        carnet = User2.query.order_by(User2.username.desc()).all()
        admin_usernames = set(get_admin_usernames()) | {row.username for row in AdminUser.query.all()}
        return render_template(
            "roles.html",
            carnet=carnet,
            admin_usernames=admin_usernames,
            break_glass_admin=get_break_glass_admin_username(),
        )

    @app.route("/roles/promote", methods=["POST"])
    @admin_only
    def promote_user_to_admin():
        ensure_admin_table_exists()
        username = request.form.get("username", "").strip()
        if not username:
            flash("Username is required.", "error")
            return redirect(url_for("roles"))

        user = User2.query.filter_by(username=username).first()
        if not user:
            flash(f"User '{username}' does not exist.", "error")
            return redirect(url_for("roles"))

        existing_admin = AdminUser.query.filter_by(username=username.lower()).first()
        if not existing_admin:
            db.session.add(AdminUser(username=username.lower()))
            db.session.commit()
            flash(f"User '{username}' promoted to Administrator.", "success")
        else:
            flash(f"User '{username}' is already an Administrator.", "info")

        return redirect(url_for("roles"))

    @app.route("/roles/demote", methods=["POST"])
    @admin_only
    def demote_user_from_admin():
        ensure_admin_table_exists()
        username = request.form.get("username", "").strip().lower()
        if not username:
            flash("Username is required.", "error")
            return redirect(url_for("roles"))

        if username == get_break_glass_admin_username():
            flash("Cannot demote the permanent break-glass administrator.", "error")
            return redirect(url_for("roles"))

        admin_record = AdminUser.query.filter_by(username=username).first()
        if not admin_record:
            flash(f"User '{username}' is not an Administrator.", "info")
            return redirect(url_for("roles"))

        admin_count = AdminUser.query.count()
        if admin_count <= 1:
            flash("Cannot demote the last administrator.", "error")
            return redirect(url_for("roles"))

        db.session.delete(admin_record)
        db.session.commit()
        flash(f"User '{username}' demoted to normal user.", "success")

        return redirect(url_for("roles"))

    @app.route("/admin/sso-roles")
    @admin_only
    def sso_roles():
        """Display all SSO users and their admin role assignments."""
        sso_users = SSOUserRole.query.order_by(SSOUserRole.username.desc()).all()
        return render_template(
            "admin_sso_roles.html",
            sso_users=sso_users,
        )

    @app.route("/admin/sso-roles/promote", methods=["POST"])
    @admin_only
    def promote_sso_user_to_admin():
        """Promote an SSO user to administrator."""
        username = request.form.get("username", "").strip()
        if not username:
            flash("Username is required.", "error")
            return redirect(url_for("sso_roles"))

        normalized = username.lower()
        user_role = SSOUserRole.query.filter_by(username=normalized).first()
        if not user_role:
            user_role = SSOUserRole(username=normalized, is_admin=True)
            db.session.add(user_role)
            db.session.commit()
            flash(f"SSO user '{username}' promoted to Administrator.", "success")
        elif user_role.is_admin:
            flash(f"SSO user '{username}' is already an Administrator.", "info")
        else:
            user_role.is_admin = True
            db.session.commit()
            flash(f"SSO user '{username}' promoted to Administrator.", "success")

        return redirect(url_for("sso_roles"))

    @app.route("/admin/sso-roles/demote", methods=["POST"])
    @admin_only
    def demote_sso_user_from_admin():
        """Demote an SSO user from administrator."""
        username = request.form.get("username", "").strip()
        if not username:
            flash("Username is required.", "error")
            return redirect(url_for("sso_roles"))

        normalized = username.lower()
        user_role = SSOUserRole.query.filter_by(username=normalized).first()
        if not user_role:
            flash(f"SSO user '{username}' not found.", "error")
            return redirect(url_for("sso_roles"))

        if not user_role.is_admin:
            flash(f"SSO user '{username}' is not an Administrator.", "info")
            return redirect(url_for("sso_roles"))

        user_role.is_admin = False
        db.session.commit()
        flash(f"SSO user '{username}' demoted to normal user.", "success")

        return redirect(url_for("sso_roles"))

    @app.route("/devlog")
    @admin_only
    def devlog():
        devlog_l = DeviceLog.query.order_by(DeviceLog.vessel_name.desc()).all()
        return render_template("devlog.html", devlogL=devlog_l)

    @app.route("/metrics")
    @admin_only
    def metrics():
        data = Metric.query.order_by(Metric.timestamp.desc()).all()
        return render_template("metrics.html", data=data)

    @app.route("/spinergie")
    def spinergie():
        return render_template("spinergie.html")

    @app.route("/admin")
    @admin_only
    def admin_dashboard():
        return render_template("admin.html")

    @app.route("/admin/add_user", methods=["GET", "POST"])
    @admin_only
    def admin_add_user():
        ensure_admin_table_exists()
        message = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            make_admin = request.form.get("is_admin") == "on"
            if username:
                default_password = f"BOS{username.lower()}*"
                existing = User2.query.filter_by(username=username).first()
                if existing:
                    if make_admin:
                        admin_record = AdminUser.query.filter_by(username=username.lower()).first()
                        if admin_record:
                            message = f"User {username} is already an Administrator."
                        else:
                            db.session.add(AdminUser(username=username.lower()))
                            db.session.commit()
                            message = f"User {username} promoted to Administrator."
                    else:
                        message = f"User {username} already exists!"
                else:
                    new_user = User2(
                        username=username,
                        password_hash=generate_password_hash(default_password),
                    )
                    db.session.add(new_user)
                    if make_admin:
                        db.session.add(AdminUser(username=username.lower()))
                    db.session.commit()
                    if make_admin:
                        message = f"User {username} created as Administrator."
                    else:
                        message = f"User {username} created."

        return render_template("admin_add_user.html", message=message)

    @app.route("/admin/reset_password", methods=["GET", "POST"])
    @admin_only
    def admin_reset_password():
        message = None
        success = False
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            new_password = request.form.get("new_password", "").strip()
            if not username or not new_password:
                message = "Both username and new password are required."
            elif len(new_password) < 8:
                message = "Password must be at least 8 characters."
            else:
                user = User2.query.filter_by(username=username).first()
                if user:
                    user.password_hash = generate_password_hash(new_password)
                    db.session.commit()
                    message = f"Password for '{username}' has been reset successfully."
                    success = True
                else:
                    message = f"User '{username}' does not exist."

        return render_template("admin_reset_password.html", message=message, success=success)
