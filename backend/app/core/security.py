"""密码哈希(bcrypt 直用，弃用 passlib 以规避 py3.13 兼容问题) 与 JWT 签发/校验。"""
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import bcrypt
from jose import JWTError, jwt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


class TokenClaims(NamedTuple):
    sub: int
    username: str
    department_id: int | None
    role_ids: list[int]
    permission_codes: list[str]


def create_token(
    *,
    sub: int,
    username: str,
    department_id: int | None,
    role_ids: list[int],
    permission_codes: list[str],
    secret: str,
    expire_hours: int = 12,
    algorithm: str = "HS256",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(sub),
        "username": username,
        "department_id": department_id,
        "role_ids": role_ids,
        "permission_codes": permission_codes,
        "iat": now,
        "exp": now + timedelta(hours=expire_hours),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, secret: str, algorithm: str = "HS256") -> TokenClaims:
    """无效/过期抛 JWTError（含 ExpiredSignatureError）。"""
    payload = jwt.decode(token, secret, algorithms=[algorithm])
    return TokenClaims(
        sub=int(payload["sub"]),
        username=payload.get("username", ""),
        department_id=payload.get("department_id"),
        role_ids=list(payload.get("role_ids", [])),
        permission_codes=list(payload.get("permission_codes", [])),
    )


__all__ = [
    "hash_password",
    "verify_password",
    "create_token",
    "decode_token",
    "TokenClaims",
    "JWTError",
]
