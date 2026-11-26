import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from auth import MIN_PASSWORD, choose_password
from climate import command as climate_command, confirmed as climate_confirmed, describe as describe_climate
from selection import ENTITY_ID, Entity, Selection, checked_zone, parse_entities
from web import UPSTREAM_ERRORS, handler, render  # Re-exported for tests.

DEMO = [
    (Entity("sensor.demo_temperature", "Living room", 0), ("22.4", "°C")),
    (Entity("sensor.demo_humidity", "Humidity", 1), ("46", "%")),
    (Entity("light.demo_living", "Living room light", 2, 2), ("on", "")),
    (Entity("binary_sensor.demo_door", "Front door", 4), ("Closed", "")),
    (Entity("switch.demo_socket", "Reading lamp socket", 6, 2), ("off", "")),
]
DEMO_WEATHER = {"id": "weather.demo", "condition": "Sunny", "value": "4", "unit": "°C"}
CONTROL_WAIT = (0, .25, .5, 1)
WEATHER_LABELS = {"partlycloudy": "Partly cloudy", "clear-night": "Clear night", "snowy-rainy": "Sleet",
                  "lightning-rainy": "Thunderstorms", "windy-variant": "Windy"}


@dataclass(frozen=True)
class Settings:
    demo: bool
    title: str
    zone: ZoneInfo | None
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
        zone = options.get("timezone", "auto")
        zone = None if zone == "auto" else checked_zone(zone)

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
    weather: dict | None = None
    climates: dict = field(default_factory=dict)


class Panel:
    def __init__(self, settings, selection=None):
        self.settings = settings
        self.selection = selection if selection is not None else Selection(settings.entities)
        self.snapshot = Snapshot(())
        self.changed = Event()
        self.lock = Lock()
        self.pending = set()
        self.revision = 0
        self.demo_states = {entity.id: value for entity, value in DEMO}
        self.demo_states.update({"sensor.demo_outside": ("4", "°C"),
                                 "weather.demo": (DEMO_WEATHER["value"], DEMO_WEATHER["unit"])})
        self.demo_climate = {"state": "heat", "attributes": {"current_temperature": 20.5, "temperature": 22,
                             "temperature_unit": "°C", "min_temp": 16, "max_temp": 30, "target_temp_step": .5,
                             "supported_features": 1, "hvac_modes": ["off", "heat", "cool", "auto"]}}
        self.temperature_unit = ""
        self.next_timezone_check = 0
        self.next_weather_scan = 0
        self.auto_weather_id = ""

    @property
    def entities(self):
        if self.settings.demo:
            widgets = self.selection.layout.demo_entities
            return tuple(entity for entity, _ in DEMO) if widgets is None else widgets
        return self.selection.entities

    @property
    def weather_source(self):
        return self.selection.layout.demo_weather if self.settings.demo else self.selection.weather

    @property
    def timezone_mode(self):
        return self.selection.layout.timezone or (self.settings.zone.key if self.settings.zone else "auto")

    def timezone_display(self):
        mode = self.timezone_mode
        if mode != "auto":
            return ZoneInfo(mode), mode
        cached = self.selection.layout.ha_timezone if not self.settings.demo else ""
        if cached:
            return ZoneInfo(cached), f"{cached} (Home Assistant)"
        return ZoneInfo("UTC"), "UTC (demo)" if self.settings.demo else "UTC (until Home Assistant responds)"

    def sync_ha_config(self):
        live_climate = any(entity.id.startswith("climate.") for entity in self.entities)
        if self.settings.demo or (self.timezone_mode != "auto" and not live_climate) or monotonic() < self.next_timezone_check:
            return
        self.next_timezone_check = monotonic() + 60
        try:
            config = self.request("/config")
            if isinstance(config, dict):
                units = config.get("unit_system")
                if isinstance(units, dict) and units.get("temperature") in ("°C", "°F", "K"):
                    self.temperature_unit = units["temperature"]
                if self.timezone_mode == "auto" and config.get("time_zone"):
                    self.selection.cache_timezone(config["time_zone"])
        except UPSTREAM_ERRORS as error:
            if isinstance(error, HTTPError):
                error.close()
        else:
            self.next_timezone_check = monotonic() + 600

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

    def read_state(self, entity_id):
        try:
            data = self.request(f"/states/{entity_id}")
        except HTTPError as error:
            error.close()
            if error.code == 404:
                return {"state": "unavailable"}
            raise
        if not isinstance(data, dict) or not isinstance(data.get("state"), str):
            raise ValueError("invalid HA state")
        return data

    def get_state(self, entity):
        data = self.read_state(entity.id)
        attributes = data.get("attributes")
        unit = attributes.get("unit_of_measurement") if isinstance(attributes, dict) else None
        state = data["state"]
        return state, unit if isinstance(unit, str) and state not in {"unknown", "unavailable"} else ""

    def catalogue(self):
        if self.settings.demo:
            return {**{entity.id: entity.label for entity, _ in DEMO}, "weather.demo": "Demo weather",
                    "sensor.demo_outside": "Outdoor temperature", "climate.demo_hall": "Hall thermostat"}
        states = self.all_states()
        entities = {}
        for item in states:
            entity_id = item.get("entity_id") if isinstance(item, dict) else None
            if not isinstance(entity_id, str) or not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", entity_id):
                continue
            attrs = item.get("attributes")
            name = attrs.get("friendly_name") if isinstance(attrs, dict) else None
            entities[entity_id] = (name[:120] if isinstance(name, str) and name.strip() else entity_id)
        return entities

    def all_states(self):
        states = self.request("/states", max_size=16 * 1024 * 1024)
        if not isinstance(states, list):
            raise ValueError("Invalid Home Assistant state list.")
        return states

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

    def confirm_control(self, entity_id, action):
        if action not in {"turn_on", "turn_off"} or entity_id.partition(".")[0] not in {"light", "switch"}:
            return False
        with self.lock:
            states = {entity.id: value[0] for entity, value in zip(self.snapshot.entities, self.snapshot.values)}
            if (entity_id not in {entity.id for entity in self.entities} or states.get(entity_id) not in {"on", "off"} or
                    self.snapshot.stale or not self.snapshot.updated_at or
                    (datetime.now(timezone.utc) - self.snapshot.updated_at).total_seconds() > self.settings.refresh_seconds * 2 + 5):
                return False
            if entity_id in self.pending:
                raise TimeoutError("This widget already has a command in progress.")
            self.pending.add(entity_id)
            self.revision += 1
        try:
            target = action.removeprefix("turn_")
            if self.settings.demo:
                self.demo_states[entity_id] = (target, "")
                value = self.demo_states[entity_id]
            else:
                if not self.control(entity_id, action):
                    return False
                for delay in CONTROL_WAIT:
                    if delay:
                        sleep(delay)
                    value = self.get_state(Entity(entity_id, entity_id))
                    if value[0] == target:
                        break
                else:
                    raise TimeoutError("Home Assistant did not confirm the new state.")
            with self.lock:
                self.snapshot = replace(self.snapshot, values=tuple(
                    value if entity.id == entity_id else previous
                    for entity, previous in zip(self.snapshot.entities, self.snapshot.values)))
            return True
        finally:
            with self.lock:
                self.pending.remove(entity_id)
                self.revision += 1
            self.changed.set()

    def confirm_climate(self, entity_id, action, value):
        if not entity_id.startswith("climate."):
            return False
        with self.lock:
            snapshot = self.snapshot
            state = snapshot.climates.get(entity_id)
            if (entity_id not in {entity.id for entity in self.entities} or snapshot.stale or not snapshot.updated_at or
                    (datetime.now(timezone.utc) - snapshot.updated_at).total_seconds() > self.settings.refresh_seconds * 2 + 5):
                return False
            requested = climate_command(state, action, value)
            if requested is None:
                return False
            if entity_id in self.pending:
                raise TimeoutError("This widget already has a command in progress.")
            self.pending.add(entity_id)
            self.revision += 1
        service, payload = requested
        try:
            if self.settings.demo:
                if entity_id != "climate.demo_hall":
                    return False
                if service == "set_hvac_mode":
                    self.demo_climate["state"] = payload["hvac_mode"]
                else:
                    self.demo_climate["attributes"].update(payload)
                confirmed = describe_climate(self.demo_climate, self.temperature_unit)
            else:
                with self.selection.lock:
                    if not any(entity.id == entity_id for entity in self.selection.entities):
                        return False
                    self.request(f"/services/climate/{service}", {"entity_id": entity_id, **payload})
                for delay in CONTROL_WAIT:
                    if delay:
                        sleep(delay)
                    confirmed = describe_climate(self.read_state(entity_id), self.temperature_unit)
                    if climate_confirmed(confirmed, payload):
                        break
                else:
                    raise TimeoutError("Home Assistant did not confirm the climate command.")
            with self.lock:
                self.snapshot = replace(self.snapshot, climates={**self.snapshot.climates, entity_id: confirmed})
            return True
        finally:
            with self.lock:
                self.pending.remove(entity_id)
                self.revision += 1
            self.changed.set()

    def read_weather(self, entity_id):
        if self.settings.demo:
            return DEMO_WEATHER if entity_id else None
        if not entity_id:
            return None
        if entity_id == "auto":
            return self.read_auto_weather()
        return self.weather_values(entity_id, self.read_state(entity_id))

    def read_auto_weather(self):
        if self.auto_weather_id and monotonic() < self.next_weather_scan:
            value = self.weather_values(self.auto_weather_id, self.read_state(self.auto_weather_id))
            if value["available"]:
                return value
        if monotonic() < self.next_weather_scan and not self.auto_weather_id:
            return None
        self.next_weather_scan = monotonic() + 60
        options = {}
        for item in self.all_states():
            id_ = item.get("entity_id") if isinstance(item, dict) else None
            if (isinstance(id_, str) and id_.startswith("weather.") and ENTITY_ID.fullmatch(id_)
                    and isinstance(item.get("state"), str)):
                options[id_] = self.weather_values(id_, item)
        if not options:
            self.auto_weather_id = ""
            return None
        values = sorted(options.values(), key=lambda value: (not value["available"], value["value"] == "—", value["id"]))
        selected = values[0]
        self.auto_weather_id = selected["id"]
        if selected["available"]:
            self.next_weather_scan = monotonic() + 600
        return selected

    @staticmethod
    def weather_values(entity_id, data):
        attributes = data.get("attributes")
        attrs = attributes if isinstance(attributes, dict) else {}
        state = data["state"]
        value = attrs.get("temperature")
        unit = attrs.get("temperature_unit")
        available = state not in {"unknown", "unavailable"}
        return {"id": entity_id, "available": available, "condition": WEATHER_LABELS.get(state, state.replace("-", " ").capitalize()),
                "value": str(value) if available and type(value) in (float, int) else "—",
                "unit": unit if available and type(value) in (float, int) and isinstance(unit, str) else ""}

    def dashboard(self, now, snapshot=None):
        from views import dashboard_data
        snapshot = self.snapshot if snapshot is None else snapshot
        zone, label = self.timezone_display()
        return dashboard_data(self.settings, snapshot, now, self.weather_source, zone, label)

    def poll(self):
        entities = self.entities
        with self.lock:
            if self.pending:
                return
            revision = self.revision
        try:
            climate_states = {}
            values = []
            for entity in entities:
                if entity.id.startswith("climate."):
                    climate_states[entity.id] = self.demo_climate if self.settings.demo else self.read_state(entity.id)
                    values.append((climate_states[entity.id]["state"], ""))
                else:
                    values.append(self.demo_states.get(entity.id, ("—", "")) if self.settings.demo else self.get_state(entity))
            try:
                weather = self.read_weather(self.weather_source)
            except UPSTREAM_ERRORS as error:
                if isinstance(error, HTTPError):
                    error.close()
                previous = self.snapshot.weather
                weather = ({**previous, "available": False, "condition": "Unavailable", "value": "—", "unit": ""}
                           if previous else None)
                if not entities:
                    raise
            self.sync_ha_config()
            climates = {entity_id: describe_climate(data, self.temperature_unit) for entity_id, data in climate_states.items()}
        except UPSTREAM_ERRORS as error:
            if isinstance(error, HTTPError):
                error.close()
            with self.lock:
                if revision == self.revision:
                    self.snapshot = replace(self.snapshot, stale=True)
        else:
            with self.lock:
                if revision == self.revision:
                    self.snapshot = Snapshot(tuple(values), datetime.now(timezone.utc), entities=entities, weather=weather, climates=climates)

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
