"""Backward-compatible authentication facade.

The implementation lives in :mod:`palimind.security`; this package keeps the
historical ``palimind.auth`` import path working.
"""

from palimind.security.auth import (
    COOKIE_NAME,
    AuthMiddleware,
    extract_token,
    install_auth,
    require_auth,
)
from palimind.security.tokens import (
    allow_remote,
    auth_disabled,
    get_api_token,
    get_proxy_token,
    token_file,
)

__all__ = [
    "COOKIE_NAME",
    "AuthMiddleware",
    "allow_remote",
    "auth_disabled",
    "extract_token",
    "get_api_token",
    "get_proxy_token",
    "install_auth",
    "require_auth",
    "token_file",
]
