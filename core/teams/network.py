from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)


def get_lan_ip() -> str | None:
    """Return the machine's actual LAN IP (not 127.0.0.1).

    Opens a UDP socket to a public IP and reads the local socket name, then
    closes it without sending real data. Returns None if no network route
    exists (never crashes).
    """
    logger.debug("[TEAMS] get_lan_ip entry")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # connect() on a UDP socket picks the outbound interface for the
        # route to the target without transmitting any packets.
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        logger.debug("[TEAMS] get_lan_ip -> %s", ip)
        return ip
    except OSError as e:
        logger.warning("[TEAMS] get_lan_ip failed, no network route: %s", e)
        return None
    finally:
        sock.close()