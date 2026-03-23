# SustainaBOS

## Microsoft Entra ID SSO setup

The app now supports both local username/password login and Microsoft SSO.

Set these environment variables to enable SSO:

- ENTRA_TENANT_ID: Your Entra tenant ID (GUID).
- ENTRA_CLIENT_ID: Application (client) ID from app registration.
- ENTRA_CLIENT_SECRET: Client secret for the web app registration.
- ENTRA_REDIRECT_URI: Optional explicit callback URL. If omitted, the app uses /auth/entra/callback on the current host.
- ENTRA_AUTHORITY: Optional full authority URL. Defaults to https://login.microsoftonline.com/<ENTRA_TENANT_ID>.

Authorization for SSO users is controlled via Entra Enterprise Applications assignment only:

- In Entra Enterprise Applications, set Assignment required = Yes.
- In Users and groups, assign only approved users or groups.

Notes:

- The app does not map Entra app roles or groups in code.
- Any successfully assigned Entra user can sign in through SSO.
- SSO users are treated as non-admin users in this app.

Minimum redirect URI to register in Entra app registration:

- https://<your-domain>/auth/entra/callback

If ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, and tenant/authority are present, the login page displays a Sign in with Microsoft button.

## Production readiness checklist

- Use a strong `FLASK_SECRET_KEY` and never use the development fallback in production.
- Set `APP_ENV=production`.
- Set `SESSION_COOKIE_SECURE=true` behind HTTPS.
- Configure notification settings if using device notifications:
	- `SMTP_USER`
	- `SMTP_PASS`
	- `SMTP_SERVER` (optional, default: `smtp.office365.com`)
	- `SMTP_PORT` (optional, default: `587`)
	- `NOTIFICATION_EMAIL`
- Health endpoints:
	- `GET /healthz` for liveness
	- `GET /readyz` for readiness (checks database connectivity)

Recommended runtime in production:

- Run with Gunicorn (already in `requirements.txt`) behind a reverse proxy/ingress.
- Keep Flask debug disabled (`FLASK_DEBUG=false`).
- Use WSGI entrypoint `wsgi:app`.

Example Gunicorn command:

- `gunicorn --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-8000} wsgi:app`