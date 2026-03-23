"""Application composition root.
This module wires configuration, extensions, lifecycle hooks, and route modules.
"""

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from auth_core import (
    admin_only,
    ensure_admin_table_exists,
    get_admin_usernames,
    get_break_glass_admin_username,
    is_admin_username,
    org_only,
)
from app_lifecycle import register_lifecycle_hooks
from config import configure_app, configure_database
from extensions import db
import excel_service
from routes_admin import register_admin_routes
from routes_auth import register_auth_routes
from routes_data import register_data_routes
from routes_home import register_home_routes
from routes_ops import register_ops_routes
from startup import initialize_database, run_dev_server

load_dotenv()

# Create the Flask app and apply proxy-aware request handling.
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app_runtime = configure_app(app)
APP_ENV = app_runtime["app_env"]
IS_PRODUCTION = app_runtime["is_production"]
configure_database(app)

# Initialize extensions.
db.init_app(app)
register_lifecycle_hooks(app, is_admin_username)

# Register route modules.
register_admin_routes(
    app,
    admin_only,
    ensure_admin_table_exists,
    get_admin_usernames,
    get_break_glass_admin_username,
)
register_data_routes(app, excel_service, org_only, admin_only)
register_auth_routes(app, admin_only, is_admin_username)
register_home_routes(app, excel_service)
register_ops_routes(app, db)

if __name__ == "__main__":
    initialize_database(app)
    run_dev_server(app, IS_PRODUCTION)
