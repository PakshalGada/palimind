"""Optional ACP provider presets.

A preset is just an ACP command from the environment.  PaliMind does not
download or bundle a provider CLI by default; the user installs it and points
the matching variable at the executable.
"""

from __future__ import annotations

import os
from typing import Any

from palimind.agents.providers.acp import ACPProvider

PRESETS = {
    "grok": "PALIMIND_GROK_COMMAND",
    "gemini": "PALIMIND_GEMINI_COMMAND",
    "opencode": "PALIMIND_OPENCODE_COMMAND",
    "cursor": "PALIMIND_CURSOR_COMMAND",
    "cline": "PALIMIND_CLINE_COMMAND",
    "pi": "PALIMIND_PI_COMMAND",
    "muse": "PALIMIND_MUSE_COMMAND",
    "inception": "PALIMIND_INCEPTION_COMMAND",
    "custom-acp": "PALIMIND_CUSTOM_ACP_COMMAND",
}


def register_presets(registry: Any) -> list[str]:
    registered = []
    for provider_id, env_name in PRESETS.items():
        if provider_id in registry.ids():
            continue
        command = os.environ.get(env_name, "").strip()
        if not command:
            continue
        registry.register(
            provider_id,
            lambda provider_id=provider_id, command=command: ACPProvider(
                provider_id, command=command
            ),
        )
        registered.append(provider_id)
    return registered
