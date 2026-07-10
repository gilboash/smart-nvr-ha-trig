"""Home Assistant MQTT Discovery publisher.

Each camera becomes one HA device. Each zone becomes one entity:
  Detection zone → binary_sensor  (ON = object present, OFF = cleared after hysteresis)
  State zone     → sensor          (current label string, e.g. "closed")

Set SNVR_MQTT_HOST in .env to enable. Leave blank to disable entirely.
"""
from __future__ import annotations

import json
import logging
import threading

import paho.mqtt.client as mqtt

from app.db import get_conn
from app.events.publisher import EpisodeEvent, EventPublisher
from app.settings import settings

logger = logging.getLogger("snvr.mqtt")


class MQTTPublisher(EventPublisher):
    def __init__(self) -> None:
        self._client = mqtt.Client(client_id="naco-real-smart-nvr")
        self._discovered: set[int] = set()
        self._lock = threading.Lock()
        self._connected = False

    # ── lifecycle ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        try:
            self._client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            logger.error("MQTT connect to %s:%d failed: %s", settings.mqtt_host, settings.mqtt_port, e)

    def disconnect(self) -> None:
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info("MQTT connected to %s:%d", settings.mqtt_host, settings.mqtt_port)
            # Re-announce all zones after reconnect so HA rediscovers them
            with self._lock:
                self._discovered.clear()
        else:
            logger.error("MQTT connection refused (rc=%d)", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        if rc != 0:
            logger.warning("MQTT disconnected unexpectedly (rc=%d), will reconnect", rc)

    # ── publish ──────────────────────────────────────────────────────────────

    async def publish(self, event: EpisodeEvent) -> None:
        if not self._connected or event.zone_id is None:
            return
        self._ensure_discovered(event)
        self._publish_state(event)

    def _ensure_discovered(self, event: EpisodeEvent) -> None:
        """Lazy-publish HA discovery config on the first event for a zone."""
        zone_id = event.zone_id
        with self._lock:
            if zone_id in self._discovered:
                return
            self._discovered.add(zone_id)

        row = get_conn().execute(
            "SELECT z.name AS zone_name, z.zone_type, c.name AS cam_name, c.id AS cam_id "
            "FROM zones z JOIN cameras c ON c.id = z.camera_id WHERE z.id = ?",
            (zone_id,),
        ).fetchone()
        if row is None:
            return
        self._publish_discovery(event, dict(row))

    def _publish_discovery(self, event: EpisodeEvent, row: dict) -> None:
        cam_id = row["cam_id"]
        zone_id = event.zone_id
        is_state = row["zone_type"] == "state"
        entity_type = "sensor" if is_state else "binary_sensor"
        unique_id = f"naco_nvr_{cam_id}_{zone_id}"

        pfx = settings.mqtt_topic_prefix
        state_topic = f"{pfx}/camera_{cam_id}/zone_{zone_id}/state"
        attr_topic = f"{pfx}/camera_{cam_id}/zone_{zone_id}/attributes"

        config: dict = {
            "name": row["zone_name"],
            "unique_id": unique_id,
            "device": {
                "identifiers": [f"naco_nvr_camera_{cam_id}"],
                "name": row["cam_name"],
                "manufacturer": "naco-real-smart-nvr",
                "model": "NVR Zone",
            },
            "state_topic": state_topic,
            "json_attributes_topic": attr_topic,
        }
        if not is_state:
            config["payload_on"] = "ON"
            config["payload_off"] = "OFF"
            config["device_class"] = "motion"

        disc_topic = f"{settings.mqtt_discovery_prefix}/{entity_type}/{unique_id}/config"
        self._client.publish(disc_topic, json.dumps(config), qos=1, retain=True)
        logger.info(
            "MQTT discovery: zone %d '%s' → HA %s (device: %s)",
            zone_id, row["zone_name"], entity_type, row["cam_name"],
        )

    def withdraw_zone(self, zone_id: int, cam_id: int, zone_type: str) -> None:
        """Publish empty payload to discovery topic — tells HA to remove the entity."""
        entity_type = "sensor" if zone_type == "state" else "binary_sensor"
        unique_id = f"naco_nvr_{cam_id}_{zone_id}"
        disc_topic = f"{settings.mqtt_discovery_prefix}/{entity_type}/{unique_id}/config"
        self._client.publish(disc_topic, "", qos=1, retain=True)
        with self._lock:
            self._discovered.discard(zone_id)
        logger.info("MQTT withdraw: zone %d (cam %d) removed from HA discovery", zone_id, cam_id)

    def announce_all(self) -> None:
        """Re-publish discovery config for every zone currently in the DB."""
        rows = get_conn().execute(
            "SELECT z.id AS zone_id, z.name AS zone_name, z.zone_type, "
            "c.id AS cam_id, c.name AS cam_name "
            "FROM zones z JOIN cameras c ON c.id = z.camera_id"
        ).fetchall()
        with self._lock:
            self._discovered.clear()
        for r in rows:
            self._publish_discovery(
                type("E", (), {"zone_id": r["zone_id"], "camera_id": r["cam_id"]})(),
                dict(r),
            )
        logger.info("MQTT announce_all: re-announced %d zones", len(rows))

    def _publish_state(self, event: EpisodeEvent) -> None:
        cam_id = event.camera_id
        zone_id = event.zone_id
        pfx = settings.mqtt_topic_prefix
        state_topic = f"{pfx}/camera_{cam_id}/zone_{zone_id}/state"
        attr_topic = f"{pfx}/camera_{cam_id}/zone_{zone_id}/attributes"

        is_state_event = event.class_name.startswith("state:")

        if is_state_event:
            # State zone: publish the new label on ENTER; EXIT is implicit (next ENTER replaces it)
            if event.kind == "EXIT":
                return
            state_value = event.class_name[len("state:"):]  # "state:closed" → "closed"
        else:
            state_value = "ON" if event.kind == "ENTER" else "OFF"

        attrs = {
            "class_name": event.class_name,
            "confidence": round(event.confidence, 3),
            "zone_id": zone_id,
            "camera_id": cam_id,
            "episode_id": event.episode_id,
            "ts": event.ts,
        }

        self._client.publish(state_topic, state_value, qos=1, retain=True)
        self._client.publish(attr_topic, json.dumps(attrs), qos=1, retain=True)
        logger.debug("MQTT zone %d: %s", zone_id, state_value)
