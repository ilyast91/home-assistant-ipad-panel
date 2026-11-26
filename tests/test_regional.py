import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_panel import demo
from panel import Panel, Settings
from selection import Selection


class RegionalTests(unittest.TestCase):
    def test_ha_time_zone_used_and_cached_across_restarts_then_manual_overrides(self):
        now = datetime(2026, 1, 2, 21, 15, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'selection.json'
            settings = Settings.from_options({'demo': False}, 'http://ha/api', 'token')
            panel = Panel(settings, Selection((), path))
            self.assertEqual(panel.dashboard(now)['zoneLabel'], 'UTC (until Home Assistant responds)')
            with patch.object(panel, 'request', side_effect=lambda endpoint, **kw:
                              {'time_zone': 'Europe/Moscow'} if endpoint == '/config' else []):
                panel.poll()
            self.assertEqual(panel.dashboard(now)['clock'], '00:15')
            self.assertEqual(panel.dashboard(now)['date'], 'Saturday, 03 January')
            restarted = Panel(settings, Selection((), path))
            self.assertEqual(restarted.dashboard(now)['clock'], '00:15')
            restarted.selection.set_timezone('America/New_York')
            self.assertEqual(restarted.dashboard(now)['clock'], '16:15')
            with self.assertRaises(ValueError):
                restarted.selection.set_timezone('/etc/passwd')
            self.assertEqual(restarted.selection.layout.timezone, 'America/New_York')

    def test_weather_auto_detects_usable_entity_and_is_optional(self):
        panel = Panel(Settings.from_options({'demo': False, 'timezone': 'UTC'}, 'http://ha/api', 'token'))
        states = [
            {'entity_id': 'weather.a', 'state': 'unavailable'},
            {'entity_id': 'weather.b', 'state': 'partlycloudy', 'attributes': {'temperature': 9, 'temperature_unit': '°C'}},
        ]
        with patch.object(panel, 'request', return_value=states) as request:
            panel.poll()
            request.assert_called_once()
        now = datetime.now(timezone.utc)
        self.assertEqual(panel.dashboard(now)['weather']['id'], 'weather.b')
        self.assertEqual(panel.dashboard(now)['weather']['value'], '9')
        panel.selection.save([], '')
        self.assertIsNone(panel.dashboard(now)['weather'])
        panel.selection.save([{'id': 'sensor.test'}], 'auto')
        def no_weather(endpoint, **kwargs):
            if endpoint == '/states/sensor.test':
                return {'state': '1'}
            raise OSError()
        with patch.object(panel, 'request', side_effect=no_weather):
            panel.poll()
        self.assertFalse(panel.dashboard(now)['stale'])

    def test_previous_unset_weather_becomes_auto_but_new_hidden_preference_persists(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'selection.json'
            path.write_text(json.dumps({'entities': [], 'weather': '', 'theme': 'dark'}))
            selection = Selection((), path)
            self.assertEqual(selection.weather, 'auto')
            selection.save([], '')
            self.assertEqual(Selection((), path).weather, '')

    def test_console_clock_can_still_use_explicit_deployment_timezone(self):
        panel = Panel(demo(timezone='Europe/Berlin'))
        now = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
        self.assertEqual(panel.dashboard(now)['clock'], '14:00')
