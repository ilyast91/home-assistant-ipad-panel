import json
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from html import escape
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from string import Template
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TEMPLATE = Template(Path(__file__).with_name("panel.html").read_text(encoding="utf-8"))
DEMO_ENTITIES = [("Living room", "22.4", "°C"), ("Humidity", "46", "%"), ("Front door", "Closed", "")]


@dataclass(frozen=True)
class Entity:
    id: str
    label: str


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

    @classmethod
    def from_options(cls, options, api_url="", token=""):
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

        raw_entities = options.get("entities", [])
        if not isinstance(raw_entities, list) or len(raw_entities) > 24:
            raise ValueError("entities must be a list with at most 24 entries")
        entities = []
        for item in raw_entities:
            if not isinstance(item, dict):
                raise ValueError("each entity must have an id and optional label")
            entity_id = item.get("id")
            if not isinstance(entity_id, str) or not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", entity_id):
                raise ValueError("invalid entity id; use domain.object_id")
            label = item.get("label") or entity_id
            if not isinstance(label, str):
                raise ValueError("entity label must be a string")
            entities.append(Entity(entity_id, label))

        names = options.get("allowed_hosts", ["homeassistant.local"])
        if not isinstance(names, list) or not all(isinstance(name, str) and re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9.-]*", name
        ) for name in names):
            raise ValueError("allowed_hosts must contain hostnames without schemes, ports or wildcards")
        allowed_hosts = ("localhost", *(name.lower().rstrip(".") for name in names))
        if not demo:
            if not entities or not api_url or not token:
                raise ValueError("live mode requires at least one entity, an HA API URL and a token")
            parsed = urlsplit(api_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment:
                raise ValueError("HA_URL must be an HTTP(S) base URL without credentials, query or fragment")
        return cls(demo, title, zone, interval, tuple(entities), allowed_hosts, api_url, token)


def load_settings(options_path, config_path, env):
    if options_path.is_file():
        options = json.loads(options_path.read_text(encoding="utf-8"))
        return Settings.from_options(options, "http://supervisor/core/api", env.get("SUPERVISOR_TOKEN", ""))
    options = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    url = env.get("HA_URL", "").rstrip("/")
    return Settings.from_options(options, f"{url}/api" if url else "", env.get("HA_TOKEN", ""))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Snapshot:
    values: tuple[tuple[str, str], ...]
    updated_at: datetime | None = None
    stale: bool = False


class Panel:
    def __init__(self, settings):
        self.settings = settings
        self.labels = [name for name, _, _ in DEMO_ENTITIES] if settings.demo else [e.label for e in settings.entities]
        self.snapshot = Snapshot(tuple(("—", "") for _ in self.labels))
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get_state(self, entity):
        request = Request(f"{self.settings.api_url}/states/{entity.id}", headers={
            "Authorization": f"Bearer {self.settings.token}", "Accept": "application/json",
        })
        try:
            with self.opener.open(request, timeout=4) as response:
                data = json.loads(response.read(262144))
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

    def poll(self):
        try:
            values = (tuple((value, unit) for _, value, unit in DEMO_ENTITIES) if self.settings.demo
                      else tuple(self.get_state(entity) for entity in self.settings.entities))
        except (URLError, OSError, ValueError, HTTPException):
            self.snapshot = replace(self.snapshot, stale=True)
        else:
            self.snapshot = Snapshot(values, datetime.now(timezone.utc))

    def run(self, stop):
        while not stop.is_set():
            self.poll()
            stop.wait(self.settings.refresh_seconds)


def render(settings, snapshot, now, labels=None):
    if labels is None:
        labels = [name for name, _, _ in DEMO_ENTITIES] if settings.demo else [e.label for e in settings.entities]
    cards = "".join(
        f'<li><h2>{escape(label)}</h2><p>{escape(value)} <span>{escape(unit)}</span></p></li>'
        for label, (value, unit) in zip(labels, snapshot.values)
    )
    updated = snapshot.updated_at
    age = (now - updated).total_seconds() if updated else 0
    stale = snapshot.stale or age > settings.refresh_seconds * 2 + 5
    if stale:
        status = "Stale data" if updated else "Home Assistant unavailable"
    elif not updated:
        status = "Waiting for data"
    else:
        status = "Demo" if settings.demo else "Live"
    return TEMPLATE.substitute(
        title=escape(settings.title), clock=now.astimezone(settings.zone).strftime("%H:%M"),
        refresh=settings.refresh_seconds, status=status, status_class="warn" if stale else "",
        updated=updated.astimezone(settings.zone).strftime("%Y-%m-%d %H:%M:%S") if updated else "—",
        cards=cards,
    )


def valid_host(header, names):
    match = re.fullmatch(r"(\[[0-9a-fA-F:.]+\]|[a-zA-Z0-9][a-zA-Z0-9.-]*)(?::[0-9]{1,5})?", header)
    if not match:
        return False
    host = match[1].lower().rstrip(".")
    try:
        ip_address(host.strip("[]"))
    except ValueError:
        return host in names
    return True


def handler(panel):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1 or not valid_host(hosts[0], panel.settings.allowed_hosts):
                self.send_error(400, "Unrecognized Host; check allowed_hosts")
                return
            if self.path == "/healthz":
                body, kind = b"ok\n", "text/plain"
            elif self.path in {"/", "/index.html"}:
                body = render(panel.settings, panel.snapshot, datetime.now(timezone.utc), panel.labels).encode()
                kind = "text/html"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # Do not log every kiosk refresh.

    return Handler


def main():
    try:
        settings = load_settings(Path("/data/options.json"), Path("/config/panel.json"), os.environ)
    except json.JSONDecodeError:
        raise SystemExit("Invalid JSON in panel configuration") from None
    except (OSError, ValueError) as error:
        raise SystemExit(f"Panel configuration error: {error}") from None
    # Supervisor can create its options file as root-only. Read it before dropping privileges.
    if os.environ.get("PANEL_DROP_PRIVILEGES") == "1" and os.getuid() == 0:
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    panel = Panel(settings)
    stop = Event()
    with ThreadingHTTPServer(("0.0.0.0", 8090), handler(panel)) as server:
        Thread(target=panel.run, args=(stop,), daemon=True).start()
        print("iPad Panel listening on port 8090", flush=True)
        try:
            server.serve_forever()
        finally:
            stop.set()


if __name__ == "__main__":
    main()
