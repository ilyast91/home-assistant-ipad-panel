import json
import sys
import threading
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ipad_panel"))
from panel import Entity, Panel, Settings, handler, load_settings, render


def demo(**options):
    return Settings.from_options({"demo": True, **options})


@contextmanager
def serve(request_handler):
    with ThreadingHTTPServer(("127.0.0.1", 0), request_handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


class PanelTests(unittest.TestCase):
    def test_configuration_uses_supervisor_or_compose_credentials(self):
        with TemporaryDirectory() as path:
            options = Path(path) / "options.json"
            config = Path(path) / "panel.json"
            options.write_text(json.dumps({"demo": False, "entities": [{"id": "sensor.room"}]}))
            config.write_text(json.dumps({"demo": False, "entities": [{"id": "sensor.room", "label": "Living room"}]}))
            haos = load_settings(options, config, {"SUPERVISOR_TOKEN": "internal"})
            self.assertEqual(haos.api_url, "http://supervisor/core/api")
            self.assertEqual(haos.token, "internal")
            compose = load_settings(Path(path) / "missing.json", config, {
                "HA_URL": "http://ha.local:8123/", "HA_TOKEN": "manual",
            })
            self.assertEqual(compose.api_url, "http://ha.local:8123/api")
            self.assertEqual(compose.token, "manual")
            self.assertEqual(compose.entities[0].label, "Living room")

    def test_live_requires_credentials_but_accepts_empty_selection(self):
        with self.assertRaises(ValueError):
            Settings.from_options({"demo": False, "entities": [{"id": "sensor.room"}]})
        self.assertEqual(Settings.from_options({"demo": False}, "http://ha/api", "secret").entities, ())
        with self.assertRaises(ValueError):
            demo(entities=[{"id": "sensor.room/../../config"}])

    def test_poll_only_reads_configured_states_and_keeps_snapshot_when_ha_fails(self):
        requests = []
        statuses = iter([200, 404, 503, 200, 404])

        class FakeHA(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.command, self.path, self.headers.get("Authorization")))
                code = next(statuses)
                self.send_response(code)
                self.end_headers()
                if code == 200:
                    self.wfile.write(b'{"state":"22.4","attributes":{"unit_of_measurement":"C"}}')

        with serve(FakeHA) as url:
            panel = Panel(Settings.from_options({"demo": False, "entities": [
                {"id": "sensor.room"}, {"id": "sensor.missing"},
            ]}, url + "/api", "secret"))
            panel.poll()
            snapshot = panel.snapshot
            self.assertEqual(snapshot.values[0], ("22.4", "C"))
            self.assertEqual(snapshot.values[1], ("unavailable", ""))
            self.assertIsNotNone(snapshot.updated_at)
            self.assertFalse(snapshot.stale)
            panel.poll()
            self.assertEqual(panel.snapshot.updated_at, snapshot.updated_at)
            self.assertEqual(panel.snapshot.values, snapshot.values)
            self.assertTrue(panel.snapshot.stale)
            panel.poll()
            self.assertFalse(panel.snapshot.stale)
            self.assertGreater(panel.snapshot.updated_at, snapshot.updated_at)
        self.assertEqual(requests, [
            ("GET", "/api/states/sensor.room", "Bearer secret"),
            ("GET", "/api/states/sensor.missing", "Bearer secret"),
            ("GET", "/api/states/sensor.room", "Bearer secret"),
            ("GET", "/api/states/sensor.room", "Bearer secret"),
            ("GET", "/api/states/sensor.missing", "Bearer secret"),
        ])

    def test_truncated_response_does_not_stop_polling(self):
        class FakeHA(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"100\r\n{\"state\":")

        with serve(FakeHA) as url:
            panel = Panel(Settings.from_options({"demo": False, "entities": [
                {"id": "sensor.room"},
            ]}, url + "/api", "secret"))
            panel.poll()
            self.assertTrue(panel.snapshot.stale)

    def test_ha_redirect_is_not_followed(self):
        requests = []

        class FakeHA(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/other")
                self.end_headers()

        with serve(FakeHA) as url:
            panel = Panel(Settings.from_options({"demo": False, "entities": [
                {"id": "sensor.room"},
            ]}, url + "/api", "secret"))
            panel.poll()
            self.assertTrue(panel.snapshot.stale)
            self.assertIsNone(panel.snapshot.updated_at)
            self.assertEqual(requests, ["/api/states/sensor.room"])

    def test_demo_html_escapes_strings_and_refreshes_without_javascript(self):
        panel = Panel(demo(title="<script>alert(1)</script>", timezone="Europe/Berlin"))
        panel.poll()
        now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
        snapshot = replace(panel.snapshot, updated_at=now)
        html = render(panel.settings, snapshot, now, panel.entities)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script", html)
        self.assertIn('http-equiv="refresh"', html)
        self.assertIn("Demo", html)
        self.assertIn("13:00", html)
        self.assertIn("Last update", html)
        self.assertIn("Stale data", render(panel.settings, snapshot, now + timedelta(minutes=5), panel.entities))
        entity = Entity("sensor.test", "<label>")
        unsafe = render(panel.settings, replace(snapshot, values=(("<sensor>", "<unit>"),), entities=(entity,)), now, (entity,))
        for item in ("sensor", "unit", "label"):
            self.assertIn(f"&lt;{item}&gt;", unsafe)

    def test_http_exposes_only_panel_and_health(self):
        panel = Panel(demo(allowed_hosts=["homeassistant.local"]))
        with serve(handler(panel)) as url:
            with urlopen(url + "/") as response:
                self.assertIn(b"Set up iPad Panel", response.read())
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with urlopen(url + "/healthz") as response:
                self.assertEqual(response.read(), b"ok\n")
            with self.assertRaises(HTTPError) as invalid:
                urlopen(url + "/api/states")
            self.assertEqual(invalid.exception.code, 404)
            with self.assertRaises(HTTPError) as write:
                urlopen(Request(url + "/", data=b""))
            self.assertEqual(write.exception.code, 404)
            with self.assertRaises(HTTPError) as rebinding:
                urlopen(Request(url + "/", headers={"Host": "unconfigured.example"}))
            self.assertEqual(rebinding.exception.code, 400)
            with urlopen(Request(url + "/", headers={"Host": "homeassistant.local:8090"})) as response:
                self.assertEqual(response.status, 200)
