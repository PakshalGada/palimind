from __future__ import annotations

import json
from typing import Any

# MQTT is optional. Tier 3 tool that requires explicit opt-in via the
# agent's tools allowlist.
try:
    import paho.mqtt.client as mqtt
    _MQTT_AVAILABLE = True
except ImportError:
    _MQTT_AVAILABLE = False


def mqtt(
    action: str = "publish",
    broker: str = "localhost",
    port: int = 1883,
    topic: str = "",
    message: str = "",
    qos: int = 0,
    timeout: int = 10,
) -> str:
    """Publish to or subscribe on a local MQTT broker."""
    if not _MQTT_AVAILABLE:
        return "Error: paho-mqtt is not installed (`pip install paho-mqtt`)."
    if not topic:
        return "Error: topic is required"

    if str(action).lower() == "subscribe":
        return _subscribe(str(broker), int(port), str(topic), int(timeout))
    return _publish(str(broker), int(port), str(topic), str(message), int(qos))


def _publish(broker: str, port: int, topic: str, message: str, qos: int) -> str:
    try:
        client = mqtt.Client()
        client.connect(broker, port, keepalive=10)
        client.loop_start()
        info = client.publish(topic, message, qos=qos)
        info.wait_for_publish(timeout=10)
        client.loop_stop()
        client.disconnect()
        return f"Published to MQTT topic '{topic}'"
    except Exception as e:
        return f"Error publishing to MQTT: {e}"


def _subscribe(broker: str, port: int, topic: str, timeout: int) -> str:
    import time

    received: list[dict[str, Any]] = []

    try:
        client = mqtt.Client()

        def on_message(_client, _ud, msg):
            received.append(
                {
                    "topic": msg.topic,
                    "payload": msg.payload.decode("utf-8", errors="replace"),
                }
            )

        client.on_message = on_message
        client.connect(broker, port, keepalive=10)
        client.subscribe(topic)
        client.loop_start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.1)
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        return f"Error subscribing to MQTT: {e}"

    if not received:
        return f"No messages received on '{topic}' within {timeout}s."
    return json.dumps(received[:50], ensure_ascii=False)


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Publish to or subscribe on a local MQTT broker. Tier 3 tool — "
        "requires explicit opt-in in the agent's tool list."
    ),
    "parameters": {
        "action": "Optional: 'publish' or 'subscribe' (default publish)",
        "broker": "Optional: broker host (default localhost)",
        "port": "Optional: broker port (default 1883)",
        "topic": "The MQTT topic",
        "message": "Message payload (publish only)",
        "qos": "Optional: quality of service 0/1/2 (publish only)",
        "timeout": "Optional: seconds to listen (subscribe only, default 10)",
    },
    "tier": 3,
    "requires_approval": True,
}
