import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, abort
import os
import secrets
import threading
import smtplib
from urllib.parse import urlencode
from email.mime.text import MIMEText
from sqlalchemy import text
import requests
import jwt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

from dotenv import load_dotenv
from extensions import db
from models import Survey, Metric, ChatMessage, DeviceLog, User2, AdminUser

load_dotenv()


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# Create a Flask app
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

APP_ENV = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "production")).strip().lower()
IS_PRODUCTION = APP_ENV == "production"
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "").strip()
if not FLASK_SECRET_KEY and IS_PRODUCTION:
    raise ValueError("FLASK_SECRET_KEY must be set in production.")
app.secret_key = FLASK_SECRET_KEY or "dev-only-change-me"

session_timeout_minutes = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=session_timeout_minutes)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_SECURE"] = env_bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)


# Database connection (Render provides DATABASE_URL in env vars)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "connect_args": {
        "connect_timeout": 10,
        "options": "-c statement_timeout=30000"
    }
}

db.init_app(app)


# --- auth and access helpers ---
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


_admin_table_checked = False


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
        return AdminUser.query.filter_by(username=username.strip().lower()).first() is not None
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


def get_entra_authority():
    tenant_id = os.getenv("ENTRA_TENANT_ID", "").strip()
    authority = os.getenv("ENTRA_AUTHORITY", "").strip()
    if authority:
        return authority.rstrip("/")
    if tenant_id:
        return f"https://login.microsoftonline.com/{tenant_id}"
    return None


def is_entra_sso_enabled():
    return bool(
        os.getenv("ENTRA_CLIENT_ID")
        and os.getenv("ENTRA_CLIENT_SECRET")
        and get_entra_authority()
    )


def get_entra_redirect_uri():
    configured = os.getenv("ENTRA_REDIRECT_URI", "").strip()
    if configured:
        return configured
    return url_for("entra_auth_callback", _external=True)


def get_entra_openid_configuration():
    authority = get_entra_authority()
    if not authority:
        raise ValueError("ENTRA authority is not configured.")

    discovery_url = f"{authority}/v2.0/.well-known/openid-configuration"
    response = requests.get(discovery_url, timeout=10)
    response.raise_for_status()
    return response.json()


def validate_entra_id_token(id_token):
    openid_config = get_entra_openid_configuration()
    client_id = os.getenv("ENTRA_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("ENTRA_CLIENT_ID environment variable is not set.")

    jwk_client = jwt.PyJWKClient(openid_config["jwks_uri"])
    signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=client_id,
        issuer=openid_config["issuer"],
    )


def extract_entra_username(claims):
    return (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or claims.get("name")
    )


def get_entra_state_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="entra-oidc-state")


def build_entra_state(nonce):
    serializer = get_entra_state_serializer()
    payload = {
        "nonce": nonce,
    }
    return serializer.dumps(payload)


def parse_entra_state(state_token, max_age_seconds=600):
    serializer = get_entra_state_serializer()
    return serializer.loads(state_token, max_age=max_age_seconds)


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
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


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


# To ignore warnings of openxyl, excel sheet weird format
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# --- bootstrap / seed helpers ---
def seed_users():
    ensure_admin_table_exists()
    break_glass_admin = get_break_glass_admin_username()
    # Only seed the admin account if it doesn't already exist
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



# Load and transform Excel data lazily to keep Azure startup fast.
file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Vessel_Device_Installation_Tracker NV.xlsx')
column_names = ['Vessel Name/ ID', 'Spec', 'Devices', 'Installation Status', 'Date of Installation', 'Savings/year (fuel efficiency)', 'Savings/year (Maitenance)', 'Co2 savings ton/year']

df = pd.DataFrame()
list_df = pd.DataFrame()
summary_df = pd.DataFrame()
summary2_df = pd.DataFrame()
summary3_df = pd.DataFrame()
summary4_df = pd.DataFrame()
summary_raw = pd.DataFrame()
listvessel_df = pd.DataFrame()
listdevice_df = pd.DataFrame()
vessel_devices = pd.DataFrame()

initiative_desc_map = {}
kpis = []
kpis_section = []
vessels10 = {"names": [], "values": []}
donutdev = {
  "labels": ["IWTM P10", "EFMS", "MGPS", "LED", "Nautilus Log", "Shore Generator"],
  "values": [216, 289, 400, 320, 80, 50]
}

_excel_data_loaded = False
_excel_data_lock = threading.Lock()


# --- excel loading helpers ---
def _num(i, j):
  v = pd.to_numeric(summary_raw.iat[i, j], errors='coerce')
  return 0 if pd.isna(v) else float(v)


def load_excel_data():
  global df, list_df, summary_df, summary2_df, summary3_df, summary4_df
  global summary_raw, initiative_desc_map, kpis, kpis_section
  global listvessel_df, listdevice_df, vessel_devices, vessels10

  df = pd.read_excel(file_path, engine='openpyxl', names=column_names, skiprows=7, usecols="B:I")
  list_df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Tracker', skiprows=6, nrows=470, usecols="B:J")

  summary_df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Summary', skiprows=0, nrows=18, usecols="A:F")
  summary2_df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Summary', skiprows=15, nrows=3, usecols="B:C")
  summary3_df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Summary', skiprows=0, nrows=4, usecols="I:K")
  summary4_df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Summary', skiprows=1, nrows=17, usecols="Y:Z")

  # Convert to dict { "EFMS": "Energy & Fuel...", ... }
  initiative_desc_map = dict(zip(summary4_df.iloc[:, 0], summary4_df.iloc[:, 1]))

  # --- KPIs for Home (Summary!C21:C23) ---
  # We read the sheet without headers so we can address Excel cells by (row-1, col-1)
  summary_raw = pd.read_excel(file_path, engine='openpyxl', sheet_name='Summary', header=None)

  kpi_devices_raw = int(_num(24, 2))  # C25 (row index -1, col index -1)
  kpi_gain_raw = _num(4, 9) * 100  # J5
  kpi_co2_raw = _num(23, 2)  # C24

  # Clean / round:
  kpi_devices = int(round(kpi_devices_raw))
  kpi_gain = round(kpi_gain_raw, 2)
  kpi_co2 = round(kpi_co2_raw, 0)

  # Prepare a list for the template (we'll animate these later)
  kpis = [
    {"title": "Initiatives", "value": kpi_devices, "suffix": "", "back": ["8 initiatives certified", "9 initiatives on POC"]},
    {"title": "2025 Fuel Gain", "value": kpi_gain, "suffix": "%", "back": ["Scope 1 Only. Goal 2026:", "20% Fuel savings"]},
    {"title": "CO₂ Savings", "value": kpi_co2, "suffix": " t", "back": ["Expected savings", "based on fuel savings"]},
  ]

  # --- KPIs for KPI section (Summary!J7, J8, J4) ---
  kpi_tfc_raw = _num(6, 9)  # J7
  kpi_vessels_raw = _num(7, 9)  # J8
  kpi_update_raw = _num(3, 9) * 90  # J4

  kpi_tfc = int(round(kpi_tfc_raw))
  kpi_vessels = int(round(kpi_vessels_raw))
  kpi_update = int(round(kpi_update_raw))

  kpis_section = [
    {"title": "Last 12 months TFC", "value": kpi_tfc, "suffix": " t"},
    {"title": "Number of Vessels", "value": kpi_vessels, "suffix": ""},
    {"title": "Updated Info", "value": kpi_update, "suffix": "%"},
  ]

  # Load the list of vessel and devices
  listvessel_df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Summary', skiprows=26, nrows=72, usecols="A")
  listdevice_df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Summary', skiprows=1, nrows=17, usecols="A")

  # Filter the relevant vessels
  vessels_of_interest = df[df['Vessel Name/ ID'].astype(str).str.contains('Britoil|ENA Habitat|BOS|Lewek Hydra|Nautical Aisia|Nautical Anisha|Paragon Sentinel', na=False)]

  # Extract relevant columns
  vessel_devices = vessels_of_interest[['Vessel Name/ ID', 'Devices', 'Installation Status', 'Savings/year (fuel efficiency)', 'Savings/year (Maitenance)', 'Co2 savings ton/year']]

  # Convert all savings columns to numeric, forcing errors to NaN
  vessel_devices['Savings/year (fuel efficiency)'] = pd.to_numeric(vessel_devices['Savings/year (fuel efficiency)'], errors='coerce')
  vessel_devices['Savings/year (Maitenance)'] = pd.to_numeric(vessel_devices['Savings/year (Maitenance)'], errors='coerce')
  vessel_devices['Co2 savings ton/year'] = pd.to_numeric(vessel_devices['Co2 savings ton/year'], errors='coerce')

  # Calculate total savings for each vessel
  vessel_devices['Total Savings'] = vessel_devices['Savings/year (fuel efficiency)'].fillna(0) + vessel_devices['Savings/year (Maitenance)'].fillna(0) + vessel_devices['Co2 savings ton/year'].fillna(0)

  # Create chart file used by the app
  top_vessels = vessel_devices.groupby('Vessel Name/ ID')['Total Savings'].sum().nlargest(10).reset_index()
  plt.figure(figsize=(10, 6))
  plt.bar(top_vessels['Vessel Name/ ID'], top_vessels['Total Savings'], color='blue')
  plt.xlabel('Vessel Name')
  plt.ylabel('Total Savings')
  plt.title('Top 10 Vessels with Best Performance')
  plt.xticks(rotation=45)
  plt.tight_layout()
  plt.savefig('static/top_vessels_chart.png')
  plt.close()

  # --- Top 10 Vessel Savings (Summary!A99:B108) ---
  vessels10r = summary_raw.loc[98:107, 0].dropna().astype(str).tolist()
  savings10r = pd.to_numeric(summary_raw.loc[98:107, 1], errors="coerce").fillna(0).tolist()
  vessels10 = {"names": vessels10r, "values": savings10r}


def ensure_excel_data_loaded():
        global _excel_data_loaded
        if _excel_data_loaded:
                return
        with _excel_data_lock:
                if _excel_data_loaded:
                        return
                try:
                        load_excel_data()
                        _excel_data_loaded = True
                except Exception:
                        raise

def get_vessel_summary(vessel_name):
    ensure_excel_data_loaded()

    # Find the row index where vessel_name appears in column A
    start_idx = list_df[list_df.iloc[:, 1] == vessel_name].index
    if len(start_idx) == 0:
        return None  # Vessel not found

    start = start_idx[0]  # First occurrence
    end = start + 1

    # Loop to find the next non-empty cell in column A
    while end < len(list_df) and pd.isna(list_df.iloc[end, 0]):
        end += 1

    # Extract the relevant part of the DataFrame
    summaryBIS_df = list_df.iloc[start:end].copy()
    return summaryBIS_df


# --- JSON/data API routes ---
@app.route('/get_vessel_summary', methods=['POST'])
def get_vessel_summary_route():
    vessel_name = request.json.get('vesselName')
    summaryBIS_df = get_vessel_summary(vessel_name)

    # Replace NaNs with empty strings
    summaryBIS_df = summaryBIS_df.fillna('')

    # Remove unnamed columns (those usually from index column)
    column_names2 = [
        'N',
        'Vessel Name/ ID',
        'Spec',
        'Devices',
        'Installation Status',
        'Date of Installation',
        'Savings/year (fuel efficiency)',
        'Savings/year (Maitenance)',
        'Co2 savings ton/year' ]
    summaryBIS_df.columns = column_names2

    # Return as clean HTML
    return summaryBIS_df.to_html(index=False, classes='table table-bordered table-striped', border=0)

def get_device_summary(device_name):
    ensure_excel_data_loaded()

    # Step 1: Filter relevant rows
    filtered_df = list_df[
        (list_df.iloc[:, 3] == device_name) &
        (list_df.iloc[:, 4].isin(["Done", "In Process"]))
    ].copy()

    # Step 2: For each row, find the corresponding vessel name by looking upwards
    vessel_names = []
    for idx in filtered_df.index:
        vessel_name = None
        search_idx = idx
        while search_idx >= 0:
            val = list_df.iloc[search_idx, 1]  # Column C is index 1
            if pd.notna(val):
                vessel_name = val
                break
            search_idx -= 1
        vessel_names.append(vessel_name)

    # Step 3: Add this info to the result
    filtered_df.insert(0, "Vessel Name", vessel_names)

    # Optional: Keep only the meaningful columns
    return filtered_df[["Vessel Name", filtered_df.columns[4], filtered_df.columns[5],filtered_df.columns[6],filtered_df.columns[7],filtered_df.columns[8],filtered_df.columns[9]]]  # Vessel, Device, Status


@app.route('/get_device_summary', methods=['POST'])
def get_device_summary_route():
    device_name = request.json.get('deviceName')
    filtered_df = get_device_summary(device_name)

    # Replace NaNs with empty strings
    filtered_df = filtered_df.fillna('').infer_objects(copy=False)

    # Remove unnamed columns (those usually from index column)
    column_names3 = [
        'Vessel Name',
        'Devices',
        'Installation Status',
        'Date of Installation',
        'Savings/year (fuel efficiency)',
        'Savings/year (Maitenance)',
        'Co2 savings ton/year' ]
    filtered_df.columns = column_names3

    # Return as clean HTML
    return filtered_df.to_html(index=False, classes='table table-bordered table-striped', border=0)


# --- Fuel Consumption Data (Monthly) ---
fuel_data = {
    "months": ["Janvier", "Fevrier", "Mars", "April", "Mai", "Juin", "Juillet", "Aout"],
    "DEFIANCE":[53.26, 101.05, 134.43, 157.72, 164.31, 148.86, 146.98, 114.46],
    "PRINCIPLE":[194.55, 111.68, 206.97, 152.42, 162.69, 176.43, 194.75, 143.17],
    "PRIME":[119.5, 155.3, 198.36, 150.38, 179.65, 179.63, 154.3, 166.73],
    "PRELUDE":[125.3, 136.7, 164.0, 110.0, 124.7, 155.8, 140.9, 85.8] }

goal_data = {
    "months": ["Janvier", "Fevrier", "Mars", "April", "Mai", "Juin", "Juillet", "Aout"],
    "AVERAGE": [123.1525, 126.1825, 175.94, 142.63, 157.8375, 165.18, 159.2325, 127.54],
    "GOAL":    [104.679625, 100.946, 123.158, 114.104, 126.27, 132.144, 127.386, 114.786]
}

# Latest values (last element of each list)
fuel_latest = fuel_data["DEFIANCE"][-1]   # last DEFIANCE value
avg_latest = goal_data["AVERAGE"][-1]
goal_latest = goal_data["GOAL"][-1]

# --- Oil lub and CW Water Data (Monthly) ---
oil_data = {
    "weeks": ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6", "Week 7", "Week 8"],
    "OIL_WATER":[87.5, 54, 50.5, 55, 46, 35, 31, 28.1],
    "PPM_2um":[91, 79, 56, 53, 29, 17, 16, 9.8],
}

cw_data = {
    "weeks": ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6", "Week 7", "Week 8"],
    "CONDUCTIVITY": [94, 84, 79, 87, 72, 82, 65, 31.2],
    "GOAL":    [25, 25, 25, 25, 25, 25, 25, 25]
}

# Latest values (last element of each list)
oil_latest = 100-oil_data["OIL_WATER"][-1]   # last DEFIANCE value
ppm_latest = 100-oil_data["PPM_2um"][-1]
cond_latest = 100-cw_data["CONDUCTIVITY"][-1]

# Top-10 and donut chart values are prepared by load_excel_data().


# --- web routes: public ---
@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    ensure_excel_data_loaded()

    return render_template(
        'index.html',
        username=session.get("user"),
        vessel_devices=vessel_devices,
        list_df=list_df,
        summary_df=summary_df,
        summary2_df=summary2_df,
        summary3_df=summary3_df,
        initiative_desc_map=initiative_desc_map,
        listvessel_df=listvessel_df,
        listdevice_df=listdevice_df,
        kpis=kpis,
        kpis_section=kpis_section,
        fuel_data=fuel_data,
        goal_data=goal_data,
        fuel_latest=fuel_latest,
        avg_latest=avg_latest,
        goal_latest=goal_latest,
        oil_data=oil_data,
        cw_data=cw_data,
        oil_latest = oil_latest, 
        ppm_latest = ppm_latest, 
        cond_latest = cond_latest,
        vessels10 = vessels10,
        donutdev = donutdev,
    )


# --- web routes: auth/session ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('index'))

    step = "login"
    error = None

    if request.method == 'POST':
        if 'username' in request.form and 'password' in request.form:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            user = User2.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                default_password = f"BOS{username.lower()}*"
                if password == default_password:
                    session['pending_user'] = username
                    step = "change_password"

                else:
                    session['user'] = username
                    session['is_admin'] = is_admin_username(username)
                    session['auth_provider'] = 'local'
                    session.permanent = True 
                    log = Metric(metric_name=username, value=0)
                    db.session.add(log)
                    db.session.commit()
                    return redirect(url_for('index'))
            else:
                error = "Invalid username or password"

        elif 'new_password' in request.form and 'confirm_password' in request.form:
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            username = session.get('pending_user')

            if not username:
                return redirect(url_for('login'))

            if new_password != confirm_password:
                error = "Passwords do not match."
                step = "change_password"
            else:
                user = User2.query.filter_by(username=username).first()
                if user:
                    user.password_hash = generate_password_hash(new_password)
                    db.session.commit()
                    session.pop('pending_user')
                    session['user'] = username
                    session['is_admin'] = is_admin_username(username)
                    session['auth_provider'] = 'local'
                    session.permanent = True

                    log = Metric(metric_name=f"{username}_password_changed", value=1)
                    db.session.add(log)
                    db.session.commit()
                    return redirect(url_for('index'))

    return render_template('login.html', step=step, error=error, sso_enabled=is_entra_sso_enabled())


@app.route('/auth/entra/login')
def entra_login():
    if not is_entra_sso_enabled():
        flash("SSO is not configured. Contact an administrator.", "error")
        return redirect(url_for('login'))

    nonce = secrets.token_urlsafe(24)
    state = build_entra_state(nonce)

    try:
        openid_config = get_entra_openid_configuration()
    except Exception:
        flash("Unable to start Microsoft SSO at the moment.", "error")
        return redirect(url_for('login'))

    params = {
        'client_id': os.getenv('ENTRA_CLIENT_ID', '').strip(),
        'response_type': 'code',
        'redirect_uri': get_entra_redirect_uri(),
        'response_mode': 'query',
        'scope': 'openid profile email',
        'state': state,
        'nonce': nonce,
    }
    authorize_url = f"{openid_config['authorization_endpoint']}?{urlencode(params)}"
    return redirect(authorize_url)


@app.route('/auth/entra/callback')
def entra_auth_callback():
    if not is_entra_sso_enabled():
        flash("SSO is not configured. Contact an administrator.", "error")
        return redirect(url_for('login'))

    returned_state = request.args.get('state')
    if not returned_state:
        flash("Invalid SSO state. Please try logging in again.", "error")
        return redirect(url_for('login'))

    try:
        state_payload = parse_entra_state(returned_state)
        expected_nonce = state_payload.get('nonce')
        if not expected_nonce:
            raise ValueError("Missing nonce in SSO state payload.")
    except (BadSignature, SignatureExpired, ValueError):
        flash("Invalid or expired SSO state. Please try logging in again.", "error")
        return redirect(url_for('login'))

    if request.args.get('error'):
        details = request.args.get('error_description', 'Microsoft sign-in was canceled or failed.')
        flash(details, "error")
        return redirect(url_for('login'))

    code = request.args.get('code')
    if not code:
        flash("Microsoft sign-in did not return an authorization code.", "error")
        return redirect(url_for('login'))

    try:
        openid_config = get_entra_openid_configuration()
        token_response = requests.post(
            openid_config['token_endpoint'],
            data={
                'client_id': os.getenv('ENTRA_CLIENT_ID', '').strip(),
                'client_secret': os.getenv('ENTRA_CLIENT_SECRET', '').strip(),
                'code': code,
                'redirect_uri': get_entra_redirect_uri(),
                'grant_type': 'authorization_code',
            },
            timeout=10,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        id_token = token_payload.get('id_token')
        if not id_token:
            raise ValueError('ID token was not returned by Entra ID.')

        claims = validate_entra_id_token(id_token)
        if claims.get('nonce') != expected_nonce:
            raise ValueError('Invalid SSO nonce in ID token.')

        username = extract_entra_username(claims)
        if not username:
            raise ValueError('Unable to determine username from Entra ID token.')

        username = username.strip().lower()
        session['user'] = username
        session['entra_is_user'] = True
        session['entra_is_admin'] = False
        session['is_admin'] = False
        session['auth_provider'] = 'entra'
        session.permanent = True

        log = Metric(metric_name=f"{username}_entra_login", value=1)
        db.session.add(log)
        db.session.commit()
    except Exception:
        app.logger.exception("Entra callback failed")
        flash("Microsoft sign-in failed. Please try again or use local login.", "error")
        return redirect(url_for('login'))

    return redirect(url_for('index'))


@app.route("/auth/diagnostics")
@admin_only
def auth_diagnostics():
    """
    Admin-only endpoint to display authentication and authorization diagnostics.
    Shows current session info, resolved permissions, and token claim details for debugging.
    Returns JSON or HTML based on Accept header.
    """
    auth_provider = session.get('auth_provider')
    username = session.get('user', 'Not logged in')
    
    diagnostics = {
        'username': username,
        'auth_provider': auth_provider,
        'is_admin': session.get('is_admin', False),
        'is_logged_in': 'user' in session,
    }
    
    if auth_provider == 'entra':
        diagnostics['entra_info'] = {
            'entra_is_user': session.get('entra_is_user', False),
            'entra_is_admin': session.get('entra_is_admin', False),
            'assignment_model': 'Enterprise Application assignment only',
        }
    
    if auth_provider == 'local':
        diagnostics['local_info'] = {
            'status': 'Local authentication active',
            'note': 'For local users, roles are managed via the /roles admin page'
        }
    
    # Support both JSON and HTML rendering
    if request.accept_mimetypes.get('application/json', 0) > request.accept_mimetypes.get('text/html', 0):
        return jsonify(diagnostics)
    
    return render_template('auth_diagnostics.html', diagnostics=diagnostics)


@app.route("/survey", methods=["GET", "POST"])
def survey():
    ensure_excel_data_loaded()

    vessels = list(listvessel_df['BOS DUBAI'])
    devices = list(listdevice_df['Device'])

    if request.method == "POST":
        vessel_name = request.form.get("vessel")
        responses = {}
        for device in devices:
            responses[device] = request.form.get(device)

        new_survey = Survey(
            vessel_name=vessel_name,
            date=datetime.utcnow().date(),
            responses=responses
        )
        db.session.add(new_survey)
        db.session.commit()
        flash("Survey submitted successfully!", "success")
        return redirect(url_for("login"))

    return render_template('survey.html', vessels=vessels, devices=devices)

@app.route("/survey-results")
def survey_results():
    surveys = Survey.query.order_by(Survey.date.desc()).all()

    return render_template('survey_results.html', surveys=surveys)


@app.route('/logout')
def logout():
    auth_provider = session.get('auth_provider')
    session.pop('user', None)
    session.pop('is_admin', None)
    session.pop('auth_provider', None)
    session.pop('entra_is_user', None)
    session.pop('entra_is_admin', None)

    if auth_provider == 'entra' and is_entra_sso_enabled():
        try:
            openid_config = get_entra_openid_configuration()
            end_session_endpoint = openid_config.get('end_session_endpoint')
            if end_session_endpoint:
                logout_url = f"{end_session_endpoint}?{urlencode({'post_logout_redirect_uri': url_for('login', _external=True)})}"
                return redirect(logout_url)
        except Exception:
            pass

    return redirect(url_for('login'))


# --- web routes: admin role management ---
@app.route("/roles")
@admin_only
def roles():
    ensure_admin_table_exists()
    carnet = User2.query.order_by(User2.username.desc()).all()
    admin_usernames = set(get_admin_usernames()) | {row.username for row in AdminUser.query.all()}
    return render_template(
        'roles.html',
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


# --- web routes: admin dashboards/pages ---
@app.route("/devlog")
@admin_only
def devlog():
    devlogL = DeviceLog.query.order_by(DeviceLog.vessel_name.desc()).all()
    return render_template('devlog.html', devlogL=devlogL)

@app.route("/metrics")
@admin_only
def metrics():
    data = Metric.query.order_by(Metric.timestamp.desc()).all()
    return render_template('metrics.html', data=data)

@app.route("/spinergie")
def spinergie():
    return render_template('spinergie.html')

@app.route("/admin")
@admin_only
def admin_dashboard():
    return render_template('admin.html')


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
                    password_hash=generate_password_hash(default_password)
                )
                db.session.add(new_user)
                if make_admin:
                    db.session.add(AdminUser(username=username.lower()))
                db.session.commit()
                if make_admin:
                    message = f"User {username} created as Administrator."
                else:
                    message = f"User {username} created."

    return render_template('admin_add_user.html', message=message)

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

    return render_template('admin_reset_password.html', message=message, success=success)


# --- web routes: chat + notifications ---
@app.route("/chat", methods=["GET", "POST"])
@org_only  # ← this is where @org_only protects access to KPI content
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

    else:  # GET request
        messages = ChatMessage.query.order_by(ChatMessage.timestamp.asc()).all()
        return jsonify([
            {"user": m.user, "message": m.message, "time": m.timestamp.isoformat()}
            for m in messages
        ])


@app.route('/notify_new_device', methods=['POST'])
@admin_only
def notify_new_device():
    data = request.json
    vessel = data.get("vessel")
    device = data.get("device")

    # Build the email
    sender = os.getenv("SMTP_USER", "").strip()
    recipient = os.getenv("NOTIFICATION_EMAIL", "").strip()
    if not sender or not recipient:
        app.logger.error("Missing SMTP_USER or NOTIFICATION_EMAIL configuration")
        return jsonify({"status": "error", "message": "Notification settings are not configured."}), 503

    msg = MIMEText(f"🚢 New device added!\n\nVessel: {vessel}\nDevice: {device}")
    msg['Subject'] = "New Device Notification"
    msg['From'] = sender
    msg['To'] = recipient

    # Log into database
    log = DeviceLog(action="add_device", vessel_name=vessel, device_name=device)
    db.session.add(log)
    db.session.commit()

    try:
        # Connect to your mail server (Office365)
        with smtplib.SMTP(os.getenv("SMTP_SERVER", "smtp.office365.com"), int(os.getenv("SMTP_PORT", 587))) as server:
            server.starttls()
            server.login(sender, os.getenv("SMTP_PASS"))
            server.sendmail(sender, [recipient], msg.as_string())

        return jsonify({"status": "success", "message": "Notification sent"}), 200
    except Exception:
        app.logger.exception("Failed to send notification email")
        return jsonify({"status": "error", "message": "Notification send failed."}), 500

if __name__ == '__main__':
    with app.app_context():
      db.create_all()
      seed_users()
    debug_mode = env_bool("FLASK_DEBUG", False) and not IS_PRODUCTION
    host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=debug_mode)
