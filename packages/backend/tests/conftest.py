"""Shared test configuration.

Tests exercise the ASGI app in-process and are not a deployed service, so the
bearer-token gate is disabled here. Production defaults remain authenticated.
"""

from __future__ import annotations

import os

os.environ.setdefault("PALIMIND_AUTH_DISABLED", "1")
