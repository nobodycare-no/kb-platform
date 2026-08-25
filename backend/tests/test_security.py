import pytest
from jose import JWTError

from app.core.config import get_settings
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

SECRET = "unit-test-secret"


def test_password_roundtrip():
    hashed = hash_password("Abc12345!")
    assert hashed != "Abc12345!"
    assert verify_password("Abc12345!", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_garbage_hash_returns_false():
    assert verify_password("x", "not-a-bcrypt-hash") is False


def _claims(**kw):
    base = dict(
        sub=7,
        username="it001",
        department_id=3,
        role_ids=[11],
        permission_codes=["kb:read"],
        secret=SECRET,
    )
    base.update(kw)
    return base


def test_token_roundtrip_claims():
    token = create_token(**_claims())
    claims = decode_token(token, SECRET)
    assert claims.sub == 7
    assert claims.username == "it001"
    assert claims.department_id == 3
    assert claims.role_ids == [11]
    assert claims.permission_codes == ["kb:read"]


def test_expired_token_rejected():
    token = create_token(**_claims(expire_hours=-1))
    with pytest.raises(JWTError):
        decode_token(token, SECRET)


def test_wrong_secret_rejected():
    token = create_token(**_claims())
    with pytest.raises(JWTError):
        decode_token(token, "other-secret")


def test_default_expire_matches_config():
    s = get_settings()
    assert s.jwt_expire_hours == 12
