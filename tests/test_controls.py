import re
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from unittest.mock import patch

from test_panel import demo, serve
from panel import Panel, Settings, handler
from auth import Sessions
from selection import Selection

PASSWORD = "test-password-only"


def post(client, url, fields):
    return client.open(Request(url, data=urlencode(fields).encode()))


class ControlsTests(unittest.TestCase):
    def test_password_unset_exposes_setup_but_not_demo_or_settings(self):
        panel = Panel(demo())
        panel.poll()
        with serve(handler(panel)) as url:
            self.assertIn(b"PANEL_PASSWORD", urlopen(url).read())
            self.assertNotIn(b"Living room", urlopen(url).read())
            self.assertIn(b"PANEL_PASSWORD", urlopen(url + "/settings").read())
            with self.assertRaises(HTTPError) as locked:
                post(build_opener(), url + "/control", {"id": "light.kitchen", "action": "turn_on"})
            self.assertEqual(locked.exception.code, 401)

    def test_session_expires_and_tampered_cookie_is_rejected(self):
        auth = Sessions(PASSWORD, secure=True)
        token = auth.issue(now=100)
        self.assertIsNotNone(auth.verify(token, now=101))
        self.assertIsNone(auth.verify(token[:-1] + ("0" if token[-1] != "0" else "1"), now=101))
        self.assertIsNone(auth.verify(token, now=100 + auth.max_age + 1))
        self.assertIn("Secure", auth.cookie(token))
        self.assertIn("HttpOnly", auth.cookie(token))

    def test_login_throttled_and_logout_revokes_session(self):
        auth = Sessions(PASSWORD)
        for _ in range(5):
            self.assertEqual(auth.login("wrong", "test-client"), (None, 401))
        self.assertEqual(auth.login(PASSWORD, "test-client"), (None, 429))
        token, status = auth.login(PASSWORD, "another-client")
        self.assertEqual(status, 303)
        self.assertIsNotNone(auth.verify(token))
        auth.revoke(token)
        self.assertIsNone(auth.verify(token))

    def test_switch_off_works_and_demo_never_calls_upstream(self):
        selected = {"entities": [{"id": "switch.kettle"}]}
        panel = Panel(Settings.from_options({"demo": False, **selected}, "http://ha/api", "token"))
        with patch.object(panel, "request") as request:
            self.assertTrue(panel.control("switch.kettle", "turn_off"))
            request.assert_called_once_with("/services/switch/turn_off", {"entity_id": "switch.kettle"})
        panel = Panel(demo(**selected))
        with patch.object(panel, "request") as request:
            self.assertFalse(panel.control("switch.kettle", "turn_off"))
            request.assert_not_called()

    def test_legacy_selection_imported_once_even_after_all_removed(self):
        settings = Settings.from_options({"demo": True, "entities": [{"id": "light.kitchen"}]})
        with TemporaryDirectory() as path:
            dest = Path(path) / "selection.json"
            selection = Selection(settings.entities, dest)
            self.assertEqual(selection.entities, settings.entities)
            selection.remove("light.kitchen")
            self.assertEqual(Selection(settings.entities, dest).entities, ())

    def test_login_search_rename_select_and_control_are_protected(self):
        options = {"demo": False, "entities": [{"id": "sensor.room"}]}
        settings = Settings.from_options(options, "http://ha/api", "never-in-the-browser", password=PASSWORD)
        with TemporaryDirectory() as path:
            dest = Path(path) / "selection.json"
            panel = Panel(settings, Selection(settings.entities, dest))
            catalogue = [{"entity_id": "light.kitchen", "attributes": {"friendly_name": "Kitchen lights"}},
                         {"entity_id": "switch.kettle", "attributes": {"friendly_name": "Kettle"}},
                         {"entity_id": "lock.door", "attributes": {"friendly_name": "Door"}}]
            calls = []
            def fake_api(endpoint, payload=None, **kwargs):
                calls.append((endpoint, payload))
                return catalogue if endpoint == "/states" else {"state": "off"}

            with patch.object(panel, "request", side_effect=fake_api), serve(handler(panel)) as url:
                public = urlopen(url + "/settings?q=kitchen").read().decode()
                self.assertIn("Sign in", public)
                self.assertNotIn("Kitchen lights", public)
                self.assertEqual(calls, [])
                with self.assertRaises(HTTPError) as anonymous:
                    post(build_opener(), url + "/control", {"csrf": "fake", "id": "light.kitchen", "action": "turn_on"})
                self.assertEqual(anonymous.exception.code, 401)
                self.assertEqual(calls, [])
                client = build_opener(HTTPCookieProcessor(CookieJar()))
                with self.assertRaises(HTTPError) as wrong:
                    post(client, url + "/login", {"password": "wrong"})
                self.assertEqual(wrong.exception.code, 401)
                self.assertIn("Settings", post(client, url + "/login", {"password": PASSWORD}).read().decode())
                page = client.open(url + "/settings?q=KITCHEN").read().decode()
                self.assertIn("Kitchen lights", page)
                self.assertNotIn("Kettle", page)
                self.assertNotIn("never-in-the-browser", page)
                token = re.search(r'name="csrf" value="([0-9a-f]+)"', page)[1]
                with self.assertRaises(HTTPError) as csrf:
                    post(client, url + "/settings/add", {"id": "light.kitchen"})
                self.assertEqual(csrf.exception.code, 403)
                with self.assertRaises(HTTPError) as origin:
                    client.open(Request(url + "/settings/add", data=urlencode({"csrf": token, "id": "light.kitchen"}).encode(),
                                        headers={"Origin": "https://example.invalid"}))
                self.assertEqual(origin.exception.code, 403)
                for entity, operation in (("switch.kettle", "turn_on"), ("sensor.room", "turn_off"),
                                          ("light.kitchen", "toggle")):
                    with self.assertRaises(HTTPError):
                        post(client, url + "/control", {"csrf": token, "id": entity, "action": operation})
                self.assertFalse(any(endpoint.startswith("/services/") for endpoint, _ in calls))
                post(client, url + "/settings/add", {"csrf": token, "id": "light.kitchen", "label": "Ceiling"})
                post(client, url + "/settings/rename", {"csrf": token, "id": "light.kitchen", "label": "Kitchen ceiling"})
                panel.poll()
                page = client.open(url).read().decode()
                self.assertIn("Kitchen ceiling", page)
                self.assertIn('value="turn_on"', page)
                post(client, url + "/control", {"csrf": token, "id": "light.kitchen", "action": "turn_on"})
                self.assertIn(("/services/light/turn_on", {"entity_id": "light.kitchen"}), calls)
                self.assertEqual(Selection((), dest).entities[-1].label, "Kitchen ceiling")
                post(client, url + "/settings/remove", {"csrf": token, "id": "light.kitchen"})
                self.assertEqual([entity.id for entity in Selection((), dest).entities], ["sensor.room"])
                post(client, url + "/logout", {"csrf": token})
                self.assertIn(b"Sign in", client.open(url).read())
