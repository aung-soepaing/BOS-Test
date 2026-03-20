# SustainaBOS

## Microsoft Entra ID SSO setup

The app now supports both local username/password login and Microsoft SSO.

Set these environment variables to enable SSO:

- ENTRA_TENANT_ID: Your Entra tenant ID (GUID).
- ENTRA_CLIENT_ID: Application (client) ID from app registration.
- ENTRA_CLIENT_SECRET: Client secret for the web app registration.
- ENTRA_REDIRECT_URI: Optional explicit callback URL. If omitted, the app uses /auth/entra/callback on the current host.
- ENTRA_AUTHORITY: Optional full authority URL. Defaults to https://login.microsoftonline.com/<ENTRA_TENANT_ID>.

Authorization for SSO users is controlled via Entra Enterprise Applications (Users and groups), not .env mapping:

- In Entra Enterprise Applications, set Assignment required = Yes.
- Define and assign app roles (recommended): app_users and app_admin.
- Assign users or groups to those roles in Users and groups.

Notes:

- Users assigned to app_admin are treated as administrators.
- Users assigned to app_users are standard users.
- If no roles are emitted in token, the app treats an assigned Enterprise App user as a standard user.

Minimum redirect URI to register in Entra app registration:

- https://<your-domain>/auth/entra/callback

If ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, and tenant/authority are present, the login page displays a Sign in with Microsoft button.