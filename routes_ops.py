"""Operational route registrations (health/readiness probes)."""

from flask import jsonify
from sqlalchemy import text

def register_ops_routes(app, db):
    """Register liveness and readiness endpoints."""

    @app.route("/healthz")
    def healthz():
        return jsonify({"status": "ok"}), 200

    @app.route("/readyz")
    def readyz():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ready"}), 200
        except Exception:
            app.logger.exception("Readiness check failed")
            return jsonify({"status": "not_ready"}), 503