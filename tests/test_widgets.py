import json
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, build_opener, urlopen
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_panel import demo, serve
from test_controls import post
from test_first_run import form_token
from panel import Panel, Settings, handler
from selection import Entity, Selection, parse_entities
from web import render


class WidgetTests(unittest.TestCase):
    def test_import_old_layout_and_persist_grid_weather_and_theme(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            path.write_text('[{"id":"sensor.temp","label":"Temperature"}]')
            layout = Selection((), path)
            self.assertEqual(layout.entities[0], Entity("sensor.temp", "Temperature", 0, 1))
            layout.save([{"id": "sensor.temp", "label": "Room", "cell": 9, "width": 2}], "weather.home")
            layout.set_theme("light")
            saved = Selection((), path)
            self.assertEqual(saved.theme, "light")
            self.assertEqual(saved.weather, "weather.home")
            self.assertEqual(asdict(saved.entities[0]), {"id": "sensor.temp", "label": "Room", "cell": 9, "width": 2, "height": 1})

    def test_bad_positions_overlaps_and_weather_do_not_change_layout(self):
        layout = Selection(())
        first = {"id": "sensor.temp", "cell": 1, "width": 2}
        layout.save([first], "weather.home")
        for entities, weather in (([first, {"id": "sensor.humidity", "cell": 2}], ""),
                                  ([{**first, "cell": 3}], ""),
                                  ([{**first, "width": 3}], ""),
                                  ([{**first, "cell": -1}], ""),
                                  ([first], "sensor.other")):
            with self.assertRaises(ValueError):
                layout.save(entities, weather)
        self.assertEqual(layout.entities, parse_entities([first]))
        self.assertEqual(layout.weather, "weather.home")

    def test_editor_api_requires_session_and_csrf_and_saves_only_a_valid_draft(self):
        panel = Panel(Settings.from_options({}, password="test-password"))
        with serve(handler(panel)) as url:
            with self.assertRaises(HTTPError) as anonymous:
                urlopen(url + "/catalogue")
            self.assertEqual(anonymous.exception.code, 401)
            client = build_opener(HTTPCookieProcessor(CookieJar()))
            proof = form_token(client, url)
            with post(client, url + "/login", {"csrf": proof, "password": "test-password"}):
                pass
            csrf = form_token(client, url + "/edit")
            with self.assertRaises(HTTPError) as rejected:
                post(client, url + "/theme", {"theme": "light"})
            self.assertEqual(rejected.exception.code, 403)
            with post(client, url + "/theme", {"csrf": csrf, "theme": "light"}):
                pass
            self.assertEqual(panel.selection.theme, "light")
            first = {"id": "sensor.demo_temperature", "cell": 1, "width": 2}
            with self.assertRaises(HTTPError) as collision:
                post(client, url + "/layout", {"csrf": csrf, "widgets": json.dumps([
                    first, {"id": "sensor.demo_humidity", "cell": 2},
                ])})
            self.assertEqual(collision.exception.code, 400)
            self.assertIsNone(panel.selection.layout.demo_entities)
            with post(client, url + "/layout", {"csrf": csrf, "widgets": json.dumps([first])}) as reply:
                self.assertTrue(json.load(reply)["saved"])
            self.assertEqual(panel.entities[0].width, 2)
            self.assertEqual(panel.selection.entities, ())

    def test_turn_on_requires_readback_and_keeps_previous_value_on_failure(self):
        panel = Panel(Settings.from_options({"demo": False, "timezone": "UTC", "entities": [{"id": "light.study"}]}, "http://ha/api", "token"))
        panel.selection.save([{"id": "light.study"}], "")
        with patch.object(panel, "request", side_effect=[{"state": "off"}, [], {"state": "on"}]) as request:
            panel.poll()
            self.assertTrue(panel.confirm_control("light.study", "turn_on"))
        self.assertEqual(request.call_args_list[1].args, ("/services/light/turn_on", {"entity_id": "light.study"}))
        self.assertEqual(panel.dashboard(datetime.now(timezone.utc))["values"]["light.study"][0], "on")
        with patch.object(panel, "request", side_effect=[[], {"state": "on"}]), patch("panel.CONTROL_WAIT", (0,)):
            with self.assertRaises(TimeoutError):
                panel.confirm_control("light.study", "turn_off")
        self.assertEqual(panel.dashboard(datetime.now(timezone.utc))["values"]["light.study"][0], "on")

    def test_weather_and_stale_dashboard_share_last_success(self):
        panel = Panel(Settings.from_options({"demo": False}, "http://ha/api", "token"))
        panel.selection.save([{"id": "sensor.room"}], "weather.home")
        with patch.object(panel, "request", return_value={"state": "partlycloudy", "attributes": {
            "temperature": 12, "temperature_unit": "°C",
        }}):
            panel.poll()
        now = datetime.now(timezone.utc)
        current = panel.dashboard(now)
        self.assertEqual(current["weather"], {"id": "weather.home", "condition": "Partly cloudy", "value": "12", "unit": "°C"})
        with patch.object(panel, "request", side_effect=OSError()):
            panel.poll()
        stale = panel.dashboard(now)
        self.assertEqual(stale["updated"], current["updated"])
        self.assertTrue(stale["stale"])
        self.assertIn("Last update", render(panel.settings, panel.snapshot, now, panel.entities))

    def test_demo_modes_do_not_call_ha_and_toggle_is_a_single_form_button(self):
        panel = Panel(demo())
        with patch.object(panel, "request") as request:
            panel.poll()
            self.assertFalse(panel.confirm_control("light.demo", "turn_on"))
            request.assert_not_called()
        real = Panel(Settings.from_options({"demo": False, "entities": [{"id": "switch.fan"}]}, "http://ha/api", "token"))
        with patch.object(real, "request", return_value={"state": "on"}):
            real.poll()
        page = render(real.settings, real.snapshot, datetime.now(timezone.utc), real.entities, "csrf")
        self.assertEqual(page.count('action="/control"'), 1)
        self.assertEqual(page.count('name="action"'), 1)
        self.assertIn('value="turn_off"', page)
        self.assertIn('aria-pressed="true"', page)
