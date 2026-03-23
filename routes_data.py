import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from flask import jsonify, redirect, render_template, request, session, url_for, flash
from extensions import db
from models import ChatMessage, DeviceLog, Survey


column_names2 = [
    "N",
    "Vessel Name/ ID",
    "Spec",
    "Devices",
    "Installation Status",
    "Date of Installation",
    "Savings/year (fuel efficiency)",
    "Savings/year (Maitenance)",
    "Co2 savings ton/year",
]

column_names3 = [
    "Vessel Name",
    "Devices",
    "Installation Status",
    "Date of Installation",
    "Savings/year (fuel efficiency)",
    "Savings/year (Maitenance)",
    "Co2 savings ton/year",
]


def register_data_routes(app, excel_service, org_only, admin_only):
    @app.route("/get_vessel_summary", methods=["POST"])
    def get_vessel_summary_route():
        vessel_name = request.json.get("vesselName")
        summary_bis_df = excel_service.get_vessel_summary(vessel_name)
        summary_bis_df = summary_bis_df.fillna("")
        summary_bis_df.columns = column_names2
        return summary_bis_df.to_html(index=False, classes="table table-bordered table-striped", border=0)

    @app.route("/get_device_summary", methods=["POST"])
    def get_device_summary_route():
        device_name = request.json.get("deviceName")
        filtered_df = excel_service.get_device_summary(device_name)
        filtered_df = filtered_df.fillna("").infer_objects(copy=False)
        filtered_df.columns = column_names3
        return filtered_df.to_html(index=False, classes="table table-bordered table-striped", border=0)

    @app.route("/survey", methods=["GET", "POST"])
    def survey():
        excel_service.ensure_excel_data_loaded()

        vessels = list(excel_service.listvessel_df["BOS DUBAI"])
        devices = list(excel_service.listdevice_df["Device"])

        if request.method == "POST":
            vessel_name = request.form.get("vessel")
            responses = {}
            for device in devices:
                responses[device] = request.form.get(device)

            new_survey = Survey(
                vessel_name=vessel_name,
                date=datetime.utcnow().date(),
                responses=responses,
            )
            db.session.add(new_survey)
            db.session.commit()
            flash("Survey submitted successfully!", "success")
            return redirect(url_for("login"))

        return render_template("survey.html", vessels=vessels, devices=devices)

    @app.route("/survey-results")
    def survey_results():
        surveys = Survey.query.order_by(Survey.date.desc()).all()
        return render_template("survey_results.html", surveys=surveys)

    @app.route("/chat", methods=["GET", "POST"])
    @org_only
    def chat():
        if request.method == "POST":
            data = request.get_json()
            msg = data.get("message", "").strip()
            user = session.get("user", "Anonymous")

            if msg:
                new_msg = ChatMessage(user=user, message=msg)
                db.session.add(new_msg)
                db.session.commit()

            return jsonify({"status": "ok"})

        messages = ChatMessage.query.order_by(ChatMessage.timestamp.asc()).all()
        return jsonify(
            [
                {"user": m.user, "message": m.message, "time": m.timestamp.isoformat()}
                for m in messages
            ]
        )

    @app.route("/notify_new_device", methods=["POST"])
    @admin_only
    def notify_new_device():
        data = request.json
        vessel = data.get("vessel")
        device = data.get("device")

        sender = os.getenv("SMTP_USER", "").strip()
        recipient = os.getenv("NOTIFICATION_EMAIL", "").strip()
        if not sender or not recipient:
            app.logger.error("Missing SMTP_USER or NOTIFICATION_EMAIL configuration")
            return jsonify({"status": "error", "message": "Notification settings are not configured."}), 503

        msg = MIMEText(f"🚢 New device added!\\n\\nVessel: {vessel}\\nDevice: {device}")
        msg["Subject"] = "New Device Notification"
        msg["From"] = sender
        msg["To"] = recipient

        log = DeviceLog(action="add_device", vessel_name=vessel, device_name=device)
        db.session.add(log)
        db.session.commit()

        try:
            with smtplib.SMTP(os.getenv("SMTP_SERVER", "smtp.office365.com"), int(os.getenv("SMTP_PORT", 587))) as server:
                server.starttls()
                server.login(sender, os.getenv("SMTP_PASS"))
                server.sendmail(sender, [recipient], msg.as_string())

            return jsonify({"status": "success", "message": "Notification sent"}), 200
        except Exception:
            app.logger.exception("Failed to send notification email")
            return jsonify({"status": "error", "message": "Notification send failed."}), 500
