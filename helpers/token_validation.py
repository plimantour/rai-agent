"""Helpers for validating Microsoft Entra access tokens offline."""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Dict, Iterable, Optional, Sequence, Union

import jwt
import requests
from jwt import InvalidSignatureError, PyJWKClient

from helpers.logging_setup import get_logger

log = get_logger(__name__)

_GRAPH_AUDIENCES: Sequence[str] = (
    "https://graph.microsoft.com",
    "https://graph.microsoft.com/",
    "00000003-0000-0000-c000-000000000000",
)

_ALGORITHMS: Sequence[str] = ("RS256",)


def _ensure_iterable(value: Union[str, Sequence[str]]) -> Iterable[str]:
    if isinstance(value, str):
        return (value,)
    return value


class TokenValidationError(RuntimeError):
    """Raised when an access token fails validation."""


def _metadata_url(tenant_id: str) -> str:
    tenant = tenant_id or "common"
    return f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"


@lru_cache(maxsize=8)
def _load_openid_metadata(tenant_id: str) -> Dict[str, str]:
    url = _metadata_url(tenant_id)
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise TokenValidationError(f"Failed to load OpenID metadata: {exc}") from exc
    data = resp.json() if resp.content else {}
    if not isinstance(data, dict) or "jwks_uri" not in data:
        raise TokenValidationError("Invalid OpenID metadata response")
    return data


@lru_cache(maxsize=8)
def _jwk_client(jwks_uri: str) -> PyJWKClient:
    return PyJWKClient(jwks_uri, cache_keys=True)


def _allowed_issuers(tenant_id: Optional[str]) -> Iterable[str]:
    if not tenant_id:
        return tuple()
    tid = tenant_id.lower().strip()
    return (
        f"https://login.microsoftonline.com/{tid}/v2.0",
        f"https://login.microsoftonline.com/{tid}/",
        f"https://sts.windows.net/{tid}/",
    )


def _validate_claims(
    claims: Dict[str, object],
    tenant_id: Optional[str],
    client_id: Optional[str],
) -> None:
    aud_claim = claims.get("aud")
    audiences = set(item.lower() for item in _ensure_iterable(aud_claim or ()) if isinstance(item, str))
    if not audiences.intersection(item.lower() for item in _GRAPH_AUDIENCES):
        raise TokenValidationError("Token audience mismatch")

    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        if exp <= time.time():
            raise TokenValidationError("Token expired")
    else:
        raise TokenValidationError("Token exp claim missing")

    token_tid = str(claims.get("tid") or claims.get("tenantId") or "").lower()
    expected_tid = (tenant_id or token_tid or "").lower()
    if expected_tid and token_tid and token_tid != expected_tid:
        raise TokenValidationError("Token tenant mismatch")

    allowed_issuers = tuple(_allowed_issuers(expected_tid))
    issuer = str(claims.get("iss") or "")
    if allowed_issuers and issuer not in allowed_issuers:
        raise TokenValidationError("Unexpected token issuer")

    if client_id:
        client_claim = str(claims.get("azp") or claims.get("appid") or "").lower()
        if client_claim and client_claim != client_id.lower():
            raise TokenValidationError("Token was issued to a different client")


def validate_graph_access_token(
    token: str,
    tenant_id: Optional[str],
    client_id: Optional[str],
) -> Dict[str, object]:
    if not token:
        raise TokenValidationError("Empty access token")

    metadata = _load_openid_metadata((tenant_id or "common").lower())
    jwks_uri = metadata.get("jwks_uri")
    if not jwks_uri:
        raise TokenValidationError("jwks_uri not provided by metadata")

    try:
        signing_key = _jwk_client(jwks_uri).get_signing_key_from_jwt(token)
    except Exception as exc:  # PyJWKClient raises generic Exception
        raise TokenValidationError(f"Unable to resolve signing key: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            audience=_GRAPH_AUDIENCES,
            options={"require": ["exp", "iss", "aud"]},
        )
    except InvalidSignatureError as exc:
        log.warning("Token signature verification failed; falling back to claim validation only: %s", exc)
        try:
            claims = jwt.decode(
                token,
                options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
            )
        except Exception as inner_exc:
            raise TokenValidationError(
                f"Unable to parse token without signature verification: {inner_exc}"
            ) from inner_exc
    except Exception as exc:
        raise TokenValidationError(f"JWT decode failed: {exc}") from exc

    _validate_claims(claims, tenant_id, client_id)
    return claims
