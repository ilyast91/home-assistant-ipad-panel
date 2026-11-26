from decimal import Decimal
from math import isclose, isfinite

MODE_LABELS = {'off': 'Off', 'heat': 'Heating', 'cool': 'Cooling', 'heat_cool': 'Heat / cool',
               'auto': 'Auto', 'dry': 'Dry', 'fan_only': 'Fan only'}
TARGETS = {'temperature': 'Target', 'target_temp_low': 'Lower target', 'target_temp_high': 'Upper target'}


def number(value):
    return value if type(value) in (int, float) and -10000 <= value <= 10000 and isfinite(value) else None


def step_target(state, key, direction):
    target = next((target for target in state['targets'] if target['key'] == key), None)
    if not state['step'] or not target:
        return None
    result = float(Decimal(str(target['value'])) + direction * Decimal(str(state['step'])))
    low, high = state['min'], state['max']
    if not low <= result <= high:
        return None
    payload = {item['key']: item['value'] for item in state['targets']}
    payload[key] = result
    if 'target_temp_low' in payload and payload['target_temp_low'] >= payload['target_temp_high']:
        return None
    return payload


def describe(data, unit):
    attrs = data.get('attributes')
    attrs = attrs if isinstance(attrs, dict) else {}
    mode = data['state']
    available = mode not in {'unavailable', 'unknown'}
    modes = attrs.get('hvac_modes')
    modes = list(dict.fromkeys(item for item in modes if isinstance(item, str) and item in MODE_LABELS)) if isinstance(modes, list) else []
    features = attrs.get('supported_features')
    features = features if type(features) is int and features >= 0 else 0
    low, high, step = (number(attrs.get(name)) for name in ('min_temp', 'max_temp', 'target_temp_step'))
    if step is None and attrs.get('target_temp_step') is None:
        step = 1
    if low is None or high is None or low >= high or step is None or step <= 0:
        step = None
    values = {key: number(attrs.get(key)) for key in TARGETS}
    if available and mode == 'heat_cool' and features & 2 and all(values[key] is not None for key in ('target_temp_low', 'target_temp_high')):
        keys = ('target_temp_low', 'target_temp_high')
    elif available and mode != 'heat_cool' and values['temperature'] is not None:
        keys = ('temperature',)
        if not features & 1:
            step = None
    else:
        keys = ()
    reported_unit = attrs.get('temperature_unit')
    if reported_unit in ('°C', '°F', 'K'):
        unit = reported_unit
    state = {'mode': mode, 'modeLabel': MODE_LABELS.get(mode, 'Unavailable' if not available else mode),
             'current': number(attrs.get('current_temperature')) if available else None, 'unit': unit,
             'available': available, 'modes': [{'id': item, 'label': MODE_LABELS[item]} for item in modes],
             'min': low, 'max': high, 'step': step,
             'targets': [{'key': key, 'label': TARGETS[key], 'value': values[key]} for key in keys]}
    for target in state['targets']:
        target['down'] = step_target(state, target['key'], -1) is not None
        target['up'] = step_target(state, target['key'], 1) is not None
    return state


def command(state, action, value):
    if not state or not state['available']:
        return None
    if action == 'mode':
        if any(mode['id'] == value for mode in state['modes']):
            return 'set_hvac_mode', {'hvac_mode': value}
        return None
    key, _, direction = action.rpartition('_')
    if key in TARGETS and direction in {'down', 'up'}:
        payload = step_target(state, key, 1 if direction == 'up' else -1)
        if payload is not None:
            return 'set_temperature', payload
    return None


def confirmed(state, payload):
    if 'hvac_mode' in payload:
        return state['mode'] == payload['hvac_mode']
    targets = {target['key']: target['value'] for target in state['targets']}
    return all(key in targets and isclose(targets[key], value, rel_tol=0, abs_tol=.00001) for key, value in payload.items())
