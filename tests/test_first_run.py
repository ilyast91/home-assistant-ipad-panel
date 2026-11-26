import re
import stat
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from test_panel import demo, serve
from panel import Panel, Settings, handler
from auth import choose_password


def form_token(client, url):
    with client.open(url) as reply:
        return re.search(r'name="csrf" value="([0-9a-f]+)"', reply.read().decode())[1]


def login(client, url, token, origin=None, password="abcdef"):
    headers = {} if origin is None else {"Origin": origin}
    return client.open(Request(url + "/login", headers=headers,
                               data=urlencode({"csrf": token, "password": password}).encode()))


class FirstRunTests(unittest.TestCase):
    def test_generated_password_is_saved_once_and_manual_overrides_it(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / "password"
            first, generated = choose_password("", file)
            self.assertTrue(generated)
            self.assertGreaterEqual(len(first), 16)
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            self.assertEqual(choose_password("", file), (first, False))
            self.assertEqual(choose_password("123456", file), ("123456", False))
            self.assertEqual(choose_password("", file), (first, False))

    def test_password_minimum_is_six(self):
        self.assertEqual(Settings.from_options({}, password="123456").password, "123456")
        with self.assertRaises(ValueError):
            Settings.from_options({}, password="abcde")

    def test_host_default_accepts_names_but_explicit_list_limits_them(self):
        for settings, allowed in ((demo(), True), (demo(allowed_hosts=["panel.lan"]), False)):
            with serve(handler(Panel(settings))) as url:
                request = Request(url, headers={"Host": "my-kiosk.lan:8090"})
                if allowed:
                    self.assertEqual(urlopen(request).status, 200)
                else:
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(request)
                    self.assertEqual(rejected.exception.code, 400)

    def test_login_null_origin_works_but_csrf_and_cross_site_origin_do_not(self):
        panel = Panel(Settings.from_options({}, password="abcdef"))
        with serve(handler(panel)) as url:
            client = build_opener(HTTPCookieProcessor(CookieJar()))
            token = form_token(client, url)
            outsider = build_opener(HTTPCookieProcessor(CookieJar()))
            for browser, proof, origin in ((outsider, token, "null"), (client, "", "null"),
                                           (client, token, "http://cross-site.invalid")):
                with self.assertRaises(HTTPError) as rejected:
                    login(browser, url, proof, origin)
                self.assertEqual(rejected.exception.code, 403)
            with login(client, url, token, "null") as response:
                self.assertIn(b"Sign out", response.read())
            with self.assertRaises(HTTPError) as replay:
                login(client, url, token, "null")
            self.assertEqual(replay.exception.code, 403)
