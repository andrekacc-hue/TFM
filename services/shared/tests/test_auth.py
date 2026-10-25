from __future__ import annotations

import time
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from shared.auth import SupabaseJWTVerifier, bearer_token, verify_internal_api_key
from shared.exceptions import AuthenticationError

URL = "https://demo.supabase.co"
SECRET = "test-secret-with-at-least-32-characters!!"


def _claims(**overrides):
    now = int(time.time())
    claims = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "iss": f"{URL}/auth/v1",
        "exp": now + 3600,
        "iat": now,
        "email": "ana@banco.test",
        "app_metadata": {"role": "editor", "area": "operaciones"},
    }
    claims.update(overrides)
    return claims


class FakeJWKS:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=self.public_key)


def test_hs256_token_builds_user_context():
    claims = _claims()
    token = jwt.encode(claims, SECRET, algorithm="HS256")
    user = SupabaseJWTVerifier(URL, SECRET, jwks_client=FakeJWKS(None)).verify(token)
    assert str(user.user_id) == claims["sub"]
    assert user.role == "editor"
    assert user.area == "operaciones"
    assert user.access_token == token


def test_es256_token_is_verified_with_jwks():
    private_key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(_claims(), private_key, algorithm="ES256", headers={"kid": "k1"})
    verifier = SupabaseJWTVerifier(URL, None, jwks_client=FakeJWKS(private_key.public_key()))
    assert verifier.verify(token).email == "ana@banco.test"


def test_es256_with_wrong_key_is_rejected():
    signer = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(_claims(), signer, algorithm="ES256")
    verifier = SupabaseJWTVerifier(URL, None, jwks_client=FakeJWKS(other.public_key()))
    with pytest.raises(AuthenticationError) as exc:
        verifier.verify(token)
    assert exc.value.code == "invalid_token"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"exp": int(time.time()) - 10}, "token_expired"),
        ({"aud": "otra"}, "invalid_token"),
        ({"iss": "https://otro.supabase.co/auth/v1"}, "invalid_token"),
    ],
)
def test_invalid_claims_are_rejected(overrides, code):
    token = jwt.encode(_claims(**overrides), SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError) as exc:
        SupabaseJWTVerifier(URL, SECRET, jwks_client=FakeJWKS(None)).verify(token)
    assert exc.value.code == code


def test_hs256_without_configured_secret_is_rejected():
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        SupabaseJWTVerifier(URL, None, jwks_client=FakeJWKS(None)).verify(token)


def test_garbage_token_is_rejected():
    with pytest.raises(AuthenticationError):
        SupabaseJWTVerifier(URL, SECRET, jwks_client=FakeJWKS(None)).verify("no-es-un-jwt")


def test_internal_api_key():
    verify_internal_api_key("clave-interna-correcta", "clave-interna-correcta")
    for provided in (None, "", "otra"):
        with pytest.raises(AuthenticationError):
            verify_internal_api_key(provided, "clave-interna-correcta")


@pytest.mark.parametrize(
    ("header", "expected"),
    [("Bearer abc.def.ghi", "abc.def.ghi"), ("bearer  tok ", "tok"), ("Basic xyz", None), ("Bearer ", None), (None, None)],
)
def test_bearer_token(header, expected):
    assert bearer_token(header) == expected
