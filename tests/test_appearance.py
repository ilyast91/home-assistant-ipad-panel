import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, build_opener

from test_controls import post
from test_first_run import form_token
from test_panel import demo, serve
from panel import Panel, Settings
from selection import Selection
from views import render
from web import handler


class AppearanceTests(unittest.TestCase):
    def test_palette_is_independent_and_persistent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'selection.json'
            path.write_text('{"entities":[{"id":"sensor.room","cell":5}],"theme":"light"}')
            layout = Selection((), path)
            self.assertEqual(layout.layout.palette, 'sage')
            layout.set_palette('ocean')
            layout.set_theme('dark')
            with self.assertRaises(ValueError):
                layout.set_palette('invalid')
            restarted = Selection((), path).layout
            self.assertEqual((restarted.palette, restarted.theme, restarted.entities[0].cell), ('ocean', 'dark', 5))

    def test_palette_write_requires_csrf_and_is_rendered_after_reload(self):
        panel = Panel(Settings.from_options({'demo': True}, password='test-password'))
        with serve(handler(panel)) as url:
            browser = build_opener(HTTPCookieProcessor(CookieJar()))
            post(browser, url + '/login', {'csrf': form_token(browser, url), 'password': 'test-password'}).close()
            with self.assertRaises(HTTPError) as denied:
                post(browser, url + '/palette', {'palette': 'lavender'})
            self.assertEqual(denied.exception.code, 403)
            with post(browser, url + '/palette', {'csrf': form_token(browser, url), 'palette': 'lavender'}) as reply:
                self.assertEqual(reply.status, 200)
            with browser.open(url) as reply:
                self.assertIn(b'data-palette="lavender"', reply.read())

    def test_only_2_by_2_climate_uses_the_large_console(self):
        panel = Panel(demo())
        for width, height in ((1, 1), (2, 1), (1, 2), (2, 2)):
            panel.selection.save([{'id': 'climate.demo_hall', 'width': width, 'height': height}], '', demo=True)
            panel.poll()
            html = render(panel.settings, panel.snapshot, datetime.now(timezone.utc), panel.entities, 'secret')
            self.assertEqual('tile climate climate-console' in html, width == height == 2)
            self.assertIn('data-target="target_temp_low"', html)
            self.assertIn('class="climate-mode-list"', html)
