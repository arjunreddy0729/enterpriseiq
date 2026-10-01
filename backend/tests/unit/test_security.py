"""Password hashing, token signing, and the production auth guard."""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.security import (
    JWT_ALGORITHM,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "unit-test-secret-that-is-long-enough-for-hs256-0123456789"


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"jwt_secret": SecretStr(SECRET)}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def test_correct_password_verifies() -> None:
    assert verify_password("hunter2", hash_password("hunter2"))


def test_wrong_password_does_not_verify() -> None:
    assert not verify_password("hunter3", hash_password("hunter2"))


def test_same_password_hashes_differently_each_time() -> None:
    """A fresh salt per hash: two users with the same password must not have
    the same hash, or cracking one cracks both."""
    assert hash_password("same") != hash_password("same")


def test_hash_does_not_contain_the_password() -> None:
    assert "correct-horse" not in hash_password("correct-horse")


@pytest.mark.parametrize("stored", [None, "", "garbage", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$aa$bb"])
def test_missing_or_malformed_hash_never_verifies(stored: str | None) -> None:
    assert not verify_password("anything", stored)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def test_token_round_trip_returns_the_user_id() -> None:
    user_id = uuid.uuid4()
    issued = create_access_token(user_id, settings())
    assert decode_access_token(issued.token, settings()) == user_id


def test_token_carries_no_groups_or_role() -> None:
    """Groups are resolved per request. A token that embedded them would keep
    granting revoked access until it expired."""
    issued = create_access_token(uuid.uuid4(), settings())
    claims = jwt.decode(issued.token, options={"verify_signature": False})
    assert set(claims) == {"sub", "iss", "aud", "iat", "exp", "jti"}


def test_expired_token_is_rejected() -> None:
    past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)
    issued = create_access_token(uuid.uuid4(), settings(), now=past)
    with pytest.raises(TokenError, match="expired"):
        decode_access_token(issued.token, settings())


def test_token_signed_with_another_secret_is_rejected() -> None:
    forged = create_access_token(uuid.uuid4(), settings(jwt_secret=SecretStr("x" * 64))).token
    with pytest.raises(TokenError):
        decode_access_token(forged, settings())


def test_tampered_payload_is_rejected() -> None:
    header, _payload, signature = create_access_token(uuid.uuid4(), settings()).token.split(".")
    other_payload = create_access_token(uuid.uuid4(), settings()).token.split(".")[1]
    with pytest.raises(TokenError):
        decode_access_token(f"{header}.{other_payload}.{signature}", settings())


def test_alg_none_token_is_rejected() -> None:
    """The classic JWT attack: strip the signature and declare alg=none."""
    now = dt.datetime.now(dt.UTC)
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iss": "enterpriseiq",
            "aud": "enterpriseiq-api",
            "iat": now,
            "exp": now + dt.timedelta(hours=1),
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(TokenError):
        decode_access_token(unsigned, settings())


def test_wrong_audience_is_rejected() -> None:
    """A token minted for another service must not work here, even when that
    service happens to share the signing key."""
    now = dt.datetime.now(dt.UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iss": "enterpriseiq",
            "aud": "some-other-service",
            "iat": now,
            "exp": now + dt.timedelta(hours=1),
        },
        SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(TokenError):
        decode_access_token(token, settings())


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
def test_garbage_is_rejected(token: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(token, settings())


def test_missing_secret_cannot_issue_or_verify() -> None:
    no_secret = settings(jwt_secret=None)
    with pytest.raises(TokenError):
        create_access_token(uuid.uuid4(), no_secret)
    with pytest.raises(TokenError):
        decode_access_token("a.b.c", no_secret)


# ---------------------------------------------------------------------------
# Production guard
# ---------------------------------------------------------------------------
def test_production_refuses_the_dev_header() -> None:
    with pytest.raises(ValidationError, match="AUTH_DEV_HEADER_ENABLED"):
        settings(environment="production", auth_dev_header_enabled=True)


def test_production_refuses_a_short_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        settings(
            environment="production",
            auth_dev_header_enabled=False,
            jwt_secret=SecretStr("short"),
        )


def test_production_accepts_real_auth() -> None:
    configured = settings(environment="production", auth_dev_header_enabled=False)
    assert not configured.auth_dev_header_enabled
