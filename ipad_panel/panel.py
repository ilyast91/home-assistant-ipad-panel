import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from auth import MIN_PASSWORD, choose_password
from selection import Entity, Selection, parse_entities
from web import UPSTREAM_ERRORS, handler, render  # Re-exported for tests.

DEMO = [
    (Entity("sensor.demo_temperature", "Living room"), ("22.4", "°C")),
    (Entity("sensor.demo_humidity", "Humidity"), ("46", "%")),
    (Entity("binary_sensor.demo_door", "Front door"), ("Closed", "")),
]


@dataclass(frozen=True)
class Settings:
    demo: bool
    title: str
    zone: ZoneInfo
    refresh_seconds: int
    entities: tuple[Entity, ...]
    allowed_hosts: tuple[str, ...]
    api_url: str = ""
    token: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    secure_cookie: bool = False

    @classmethod
    def from_options(cls, options, api_url="", token="", password=""):
        if not isinstance(options, dict):
            raise ValueError("configuration must be a JSON object")
        demo = options.get("demo", True)
        if type(demo) is not bool:
            raise ValueError("demo must be true or false")
        interval = options.get("refresh_seconds", 15)
        if type(interval) is not int or not 5 <= interval <= 300:
            raise ValueError("refresh_seconds must be an integer between 5 and 300")
        title = options.get("title", "Home Panel")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        zone = options.get("timezone", "UTC")
        if not isinstance(zone, str) or not zone or zone.startswith("/"):
            raise ValueError("timezone must be an IANA name, for example Europe/Berlin")
        try:
            zone = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("unknown timezone; use an IANA name such as Europe/Berlin") from error

        entities = parse_entities(options.get("entities", []))
        secure_cookie = options.get("secure_cookie", False)
        if type(secure_cookie) is not bool:
            raise ValueError("secure_cookie must be true or false")
        if not isinstance(password, str) or (password and not MIN_PASSWORD <= len(password) <= 256):
            raise ValueError(f"panel password must be {MIN_PASSWORD}–256 characters")

        names = options.get("allowed_hosts", [])
        if not isinstance(names, list) or not all(isinstance(name, str) and re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9.-]*", name
        ) for name in names):
            raise ValueError("allowed_hosts must contain hostnames without schemes, ports or wildcards")
        allowed_hosts = ("localhost", *(name.lower().rstrip(".") for name in names)) if names else ()
        if not demo:
            if not api_url or not token:
                raise ValueError("live mode requires an HA API URL and token")
            parsed = urlsplit(api_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment:
                raise ValueError("HA_URL must be an HTTP(S) base URL without credentials, query or fragment")
        return cls(demo, title, zone, interval, entities, allowed_hosts, api_url, token, password, secure_cookie)


def load_settings(options_path, config_path, env):
    if options_path.is_file():
        options = json.loads(options_path.read_text(encoding="utf-8"))
        if not isinstance(options, dict):
            raise ValueError("configuration must be a JSON object")
        return Settings.from_options(options, "http://supervisor/core/api", env.get("SUPERVISOR_TOKEN", ""),
                                     options.get("panel_password", ""))
    options = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    url = env.get("HA_URL", "").rstrip("/")
    return Settings.from_options(options, f"{url}/api" if url else "", env.get("HA_TOKEN", ""),
                                 env.get("PANEL_PASSWORD", ""))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Snapshot:
    values: tuple[tuple[str, str], ...]
    updated_at: datetime | None = None
    stale: bool = False
    entities: tuple[Entity, ...] = ()


class Panel:
    def __init__(self, settings, selection=None):
        self.settings = settings
        self.selection = selection if selection is not None else Selection(settings.entities)
        self.snapshot = Snapshot(())
        self.changed = Event()

    @property
    def entities(self):
        return tuple(entity for entity, _ in DEMO) if self.settings.demo else self.selection.entities

    def request(self, endpoint, payload=None, max_size=262144):
        headers = {"Authorization": f"Bearer {self.settings.token}", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.settings.api_url}{endpoint}",
                          data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=4) as response:
            data = response.read(max_size + 1)
        if len(data) > max_size:
            raise ValueError("HA response exceeds size limit")
        return json.loads(data)

    def get_state(self, entity):
        try:
            data = self.request(f"/states/{entity.id}")
        except HTTPError as error:
            error.close()
            if error.code == 404:
                return "unavailable", ""
            raise
        if not isinstance(data, dict) or not isinstance(data.get("state"), str):
            raise ValueError("invalid HA state")
        attributes = data.get("attributes")
        unit = attributes.get("unit_of_measurement") if isinstance(attributes, dict) else None
        state = data["state"]
        return state, unit if isinstance(unit, str) and state not in {"unknown", "unavailable"} else ""

    def catalogue(self):
        states = self.request("/states", max_size=16 * 1024 * 1024)
        if not isinstance(states, list):
            raise ValueError("invalid HA catalogue")
        entities = {}
        for item in states:
            entity_id = item.get("entity_id") if isinstance(item, dict) else None
            if not isinstance(entity_id, str) or not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", entity_id):
                continue
            attrs = item.get("attributes")
            name = attrs.get("friendly_name") if isinstance(attrs, dict) else None
            entities[entity_id] = (name[:120] if isinstance(name, str) and name.strip() else entity_id)
        return entities

    def control(self, entity_id, action):
        domain = entity_id.partition(".")[0]
        with self.selection.lock:
            if (self.settings.demo or domain not in {"light", "switch"} or
                    action not in {"turn_on", "turn_off"} or
                    not any(entity.id == entity_id for entity in self.selection.entities)):
                return False
            self.request(f"/services/{domain}/{action}", {"entity_id": entity_id})
        self.changed.set()
        return True

    def poll(self):
        entities = self.entities
        try:
            values = (tuple(value for _, value in DEMO) if self.settings.demo
                      else tuple(self.get_state(entity) for entity in entities))
        except UPSTREAM_ERRORS as error:
            if isinstance(error, HTTPError):
                error.close()
            self.snapshot = replace(self.snapshot, stale=True)
        else:
            self.snapshot = Snapshot(values, datetime.now(timezone.utc), entities=entities)

    def run(self, stop):
        while not stop.is_set():
            self.changed.clear()
            if self.settings.password:
                self.poll()
            self.changed.wait(self.settings.refresh_seconds)


def main():
    options = Path("/data/options.json")
    config = Path("/config/panel.json")
    try:
        settings = load_settings(options, config, os.environ)
        state = Path(os.environ["PANEL_STATE_DIR"]) if "PANEL_STATE_DIR" in os.environ else None
        if state is not None:
            state.mkdir(parents=True, exist_ok=True)
            if os.getuid() == 0:
                os.chown(state, 10001, 10001)
        # Supervisor options can be root-only; read them before dropping privileges.
        if os.environ.get("PANEL_DROP_PRIVILEGES") == "1" and os.getuid() == 0:
            os.setgroups([])
            os.setgid(10001)
            os.setuid(10001)
        selection = Selection(settings.entities, state / "selection.json" if state is not None else None)
        password, generated = choose_password(settings.password, state / "password" if state is not None else None)
        settings = replace(settings, password=password)
    except json.JSONDecodeError:
        raise SystemExit("Invalid JSON in panel configuration or saved selection") from None
    except (OSError, ValueError) as error:
        raise SystemExit(f"Panel configuration error: {error}") from None
    if generated:
        print(f"Generated panel password: {password}", flush=True)
    panel = Panel(settings, selection)
    stop = Event()
    with ThreadingHTTPServer(("0.0.0.0", 8090), handler(panel)) as server:
        Thread(target=panel.run, args=(stop,), daemon=True).start()
        print("iPad Panel ready: HTTP port 8090", flush=True)
        try:
            server.serve_forever()
        finally:
            stop.set()


if __name__ == "__main__":
    main()
