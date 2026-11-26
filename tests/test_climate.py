import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from test_panel import serve
from test_controls import post
from test_first_run import form_token
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, build_opener

from panel import Panel, Settings
from climate import describe, command
from web import handler


def thermostat(mode='heat', **extra):
    return {'state': mode, 'attributes': {'current_temperature': 19.5, 'temperature': 21, 'temperature_unit': '°C', 'target_temp_step': .5,
            'min_temp': 16, 'max_temp': 30, 'supported_features': 1, 'hvac_modes': ['off', 'heat', 'cool'], **extra}}


def make_panel():
    panel = Panel(Settings.from_options({'demo': False, 'timezone': 'UTC', 'entities': [{'id': 'climate.room'}]},
                                       'http://ha/api', 'secret', password='test-password'))
    panel.next_weather_scan = panel.next_timezone_check = float('inf')
    return panel


class ClimateTests(unittest.TestCase):
    def test_single_setpoint_and_modes_only_from_ha(self):
        state = describe(thermostat(), '°C')
        self.assertEqual(state['current'], 19.5)
        self.assertEqual(state['unit'], '°C')
        self.assertEqual(state['targets'], [{'key': 'temperature', 'label': 'Target', 'value': 21,
                                              'down': True, 'up': True}])
        self.assertEqual(command(state, 'temperature_up', ''), ('set_temperature', {'temperature': 21.5}))
        self.assertEqual(command(state, 'mode', 'cool'), ('set_hvac_mode', {'hvac_mode': 'cool'}))
        self.assertIsNone(command(state, 'mode', 'fan_only'))
        self.assertIsNone(command(describe(thermostat(temperature=30), '°C'), 'temperature_up', ''))
        self.assertIsNone(command(describe(thermostat(supported_features=0), '°C'), 'temperature_up', ''))
        self.assertIsNone(command(describe(thermostat('unavailable'), '°C'), 'mode', 'heat'))
        self.assertIsNone(command(describe(thermostat(temperature=float('nan')), '°C'), 'temperature_up', ''))

    def test_fallback_step_and_ha_temperature_unit(self):
        panel = make_panel()
        panel.next_timezone_check = 0
        fixture = thermostat(target_temp_step=None)
        del fixture['attributes']['temperature_unit']
        with patch.object(panel, 'request', side_effect=[fixture, {'unit_system': {'temperature': '°F'}}]):
            panel.poll()
        state = panel.snapshot.climates['climate.room']
        self.assertEqual(state['unit'], '°F')
        self.assertEqual(command(state, 'temperature_down', ''), ('set_temperature', {'temperature': 20}))

    def test_range_preserves_the_other_endpoint(self):
        state = describe(thermostat('heat_cool', supported_features=3, target_temp_low=20, target_temp_high=21), '°C')
        self.assertEqual(command(state, 'target_temp_low_up', ''), ('set_temperature', {'target_temp_low': 20.5, 'target_temp_high': 21}))
        self.assertIsNone(command(describe(thermostat('heat_cool', supported_features=2, target_temp_low=20.5,
                                                    target_temp_high=21), '°C'), 'target_temp_low_up', ''))

    def test_confirmation_preserves_state_on_failure_and_only_targets_selected_devices(self):
        panel = make_panel()
        with patch.object(panel, 'request', side_effect=[thermostat(), [], thermostat(temperature=21.5)]) as request:
            panel.poll()
            self.assertTrue(panel.confirm_climate('climate.room', 'temperature_up', ''))
            self.assertFalse(panel.confirm_climate('climate.unselected', 'mode', 'cool'))
            self.assertFalse(panel.confirm_climate('climate.room', 'mode', 'dry'))
        self.assertEqual(request.call_args_list[1].args, ('/services/climate/set_temperature', {'entity_id': 'climate.room', 'temperature': 21.5}))
        with patch.object(panel, 'request', side_effect=[[], thermostat(temperature=21.5)]), patch('panel.CONTROL_WAIT', (0,)):
            with self.assertRaises(TimeoutError):
                panel.confirm_climate('climate.room', 'mode', 'cool')
        state = panel.snapshot.climates['climate.room']
        self.assertEqual(state['mode'], 'heat')
        self.assertEqual(state['targets'][0]['value'], 21.5)

    def test_climate_forms_require_csrf_and_confirm_a_supported_mode_without_javascript(self):
        panel = make_panel()
        with patch.object(panel, 'request', side_effect=[thermostat(), [], thermostat('cool')]), serve(handler(panel)) as url:
            panel.poll()
            browser = build_opener(HTTPCookieProcessor(CookieJar()))
            with post(browser, url + '/login', {'csrf': form_token(browser, url), 'password': 'test-password'}) as response:
                page = response.read().decode()
            self.assertIn('19.5 °C', page)
            self.assertIn('value="temperature_up"', page)
            self.assertNotIn('value="dry"', page)
            with self.assertRaises(HTTPError) as denied:
                post(browser, url + '/climate', {'id': 'climate.room', 'action': 'mode', 'value': 'cool'})
            self.assertEqual(denied.exception.code, 403)
            with post(browser, url + '/climate', {'csrf': form_token(browser, url), 'id': 'climate.room', 'action': 'mode', 'value': 'cool'}) as response:
                page = response.read().decode()
            self.assertIn('State confirmed', page)
            self.assertIn('Cooling', page)
