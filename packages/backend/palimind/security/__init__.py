"""Process and request security primitives.

This package holds the pieces that keep Palimind's local API and agent
execution from becoming an unauthenticated remote-code-execution surface:

* :mod:`palimind.security.tokens` — per-user bearer tokens for the API and the
  OpenCode proxy.
* :mod:`palimind.security.auth` — FastAPI middleware enforcing those tokens
  and loopback-only access.
* :mod:`palimind.security.sandbox` — OS-level isolation for shell/Python
  execution (bubblewrap on Linux, fail-closed elsewhere).
"""

from palimind.security.tokens import (
    get_api_token,
    get_proxy_token,
    token_file,
)

__all__ = ["get_api_token", "get_proxy_token", "token_file"]
