import os
import jwt
import requests
from itsdangerous import URLSafeTimedSerializer


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


def get_entra_redirect_uri(fallback_callback_uri):
    configured = os.getenv("ENTRA_REDIRECT_URI", "").strip()
    if configured:
        return configured
    return fallback_callback_uri


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


def get_entra_state_serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt="entra-oidc-state")

def build_entra_state(secret_key, nonce):
    serializer = get_entra_state_serializer(secret_key)
    payload = {
        "nonce": nonce,
    }
    return serializer.dumps(payload)

def parse_entra_state(secret_key, state_token, max_age_seconds=600):
    serializer = get_entra_state_serializer(secret_key)
    return serializer.loads(state_token, max_age=max_age_seconds)
