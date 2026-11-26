import json
from dataclasses import asdict
from html import escape
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

from climate import TARGETS
from selection import CELLS, MAX_ENTITIES

TEMPLATE = Template(Path(__file__).with_name('panel.html').read_text(encoding='utf-8'))
CONTROL_DOMAINS = {'light', 'switch'}
WEATHER_ICONS = {'Sunny': '☀', 'Clear night': '☾', 'Partly cloudy': '⛅', 'Cloudy': '☁',
                 'Rainy': '☂', 'Pouring': '☂', 'Snowy': '❄', 'Sleet': '❄', 'Thunderstorms': 'ϟ'}
ICONS = {
    'light': 'M8 15c0-2-3-3-3-7a7 7 0 0 1 14 0c0 4-3 5-3 7 M9 18h6 M10 21h4',
    'switch': 'M9 3v5 M15 3v5 M7 8h10v3a5 5 0 0 1-5 5v5 M17 11a5 5 0 0 1-5 5',
    'temperature': 'M10 14V6a2 2 0 0 1 4 0v8a4 4 0 1 1-4 0z M12 11v6',
    'binary_sensor': 'M5 21h14 M7 21V3h10v18 M14 12h.1',
    'sensor': 'M3 12h4l3-7 4 14 3-7h4',
}


def glyph(kind):
    path = ICONS.get(kind, ICONS['sensor'])
    return (f'<svg class="glyph" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            f'<path d="{path}"></path></svg>')


def page(title, content, refresh=None, navigation='', theme='dark', script=''):
    refresh_tag = f'<noscript><meta http-equiv="refresh" content="{refresh}"></noscript>' if refresh else ''
    return TEMPLATE.substitute(title=escape(title), content=content, refresh=refresh_tag, navigation=navigation,
                               theme=theme, script=f'<script src="/{script}.js" defer></script>' if script else '')


def fields(csrf, entity_id=None):
    result = f'<input type="hidden" name="csrf" value="{escape(csrf)}">'
    if entity_id is not None:
        result += f'<input type="hidden" name="id" value="{escape(entity_id)}">'
    return result


def navigation(csrf, settings=False):
    path, label = ('/', 'Dashboard') if settings else ('/edit', 'Settings')
    return (f'<nav><a href="{path}">{label}</a><form method="post" action="/logout">'
            f'{fields(csrf)}<button type="submit">Sign out</button></form></nav>')


def dashboard_data(settings, snapshot, now, weather_id, zone=None, zone_label=None):
    updated = snapshot.updated_at
    stale = snapshot.stale or bool(updated and (now - updated).total_seconds() > settings.refresh_seconds * 2 + 5)
    zone = zone or settings.zone or ZoneInfo('UTC')
    local = now.astimezone(zone)
    weather = snapshot.weather if snapshot.weather and weather_id in ('auto', snapshot.weather['id']) else None
    if weather_id not in ('', 'auto') and not weather:
        weather = {'id': weather_id, 'condition': 'Unavailable', 'value': '—', 'unit': ''}
    return {
        'values': {e.id: value for e, value in zip(snapshot.entities, snapshot.values)},
        'climates': snapshot.climates,
        'clock': local.strftime('%H:%M'), 'date': local.strftime('%A, %d %B'),
        'clockEpoch': int(local.replace(tzinfo=ZoneInfo('UTC')).timestamp() * 1000),
        'updated': updated.astimezone(zone).strftime('%Y-%m-%d %H:%M:%S') if updated else '—',
        'zoneLabel': zone_label or zone.key,
        'stale': stale, 'weather': {key: weather[key] for key in ('id', 'condition', 'value', 'unit')} if weather else None,
        'weatherIcon': WEATHER_ICONS.get(weather['condition'], '☁') if weather else '',
        'status': ('Stale data' if updated else 'Home Assistant unavailable') if stale else
                  ('Waiting for data' if not updated else ('Demo' if settings.demo else 'Live')),
    }


def climate_tile(entity, state, stale, csrf, heading):
    state = state or {}
    active = state.get('available') and not stale
    label = escape(entity.label)
    unit = state.get('unit', '')
    current = state.get('current')
    current_text = '—' if current is None else f'{current:g} {escape(unit)}'.strip()
    targets = {target['key']: target for target in state.get('targets', [])}
    contents = (f'{heading}<p class="climate-reading"><span class="climate-caption">Current</span> '
                f'<strong class="climate-current">{current_text}</strong></p>'
                f'<p class="climate-mode">{escape(state.get("modeLabel", "Waiting for data"))}</p>')
    for key, name in TARGETS.items():
        target = targets.get(key)
        value = f'{target["value"]:g} {escape(unit)}'.strip() if target else '—'
        contents += (f'<div class="climate-target" data-target="{key}"' + ('' if target else ' hidden') + '>'
                     f'<span class="climate-caption">{name}</span> <strong>{value}</strong>')
        if csrf:
            contents += '<div class="climate-stepper">'
            for direction, symbol, verb in [('down', '−', 'Decrease'), ('up', '+', 'Increase')]:
                allowed = bool(active and target and target[direction])
                available = 'yes' if allowed else 'no'
                contents += (f'<form class="climate-form" method="post" action="/climate">{fields(csrf, entity.id)}'
                             f'<input type="hidden" name="action" value="{key}_{direction}">'
                             f'<button type="submit" data-direction="{direction}" data-available="{available}" '
                             f'aria-label="{verb} {label} {name.lower()}" {"" if allowed else "disabled"}>{symbol}</button></form>')
            contents += '</div>'
        contents += '</div>'
    if csrf:
        modes = state.get('modes', [])
        mode_enabled = bool(active and modes)
        disabled = '' if mode_enabled else ' disabled'
        signature = escape(','.join(mode['id'] for mode in modes))
        options = '<option value="">Choose a mode</option>'
        for mode in modes:
            options += f'<option value="{mode["id"]}">{escape(mode["label"])}</option>'
        hidden = '' if modes else ' hidden'
        contents += (f'<form class="climate-form climate-modes" method="post" action="/climate"{hidden}>'
                     f'{fields(csrf, entity.id)}<input type="hidden" name="action" value="mode">'
                     f'<label>Mode<select name="value" required data-modes="{signature}"{disabled}>{options}</select></label>'
                     f'<button type="submit" data-available="{"yes" if mode_enabled else "no"}"{disabled}>Apply</button></form>'
                     '<span class="feedback" role="status"></span>')
    return f'<div class="tile climate">{contents}</div>'


def render(settings, snapshot, now, entities, csrf='', notice='', theme='dark', weather_id=None, status=None):
    status = status or dashboard_data(settings, snapshot, now, ('weather.demo' if settings.demo else '') if weather_id is None else weather_id)
    rows = {}
    for entity in entities:
        value, unit = status['values'].get(entity.id, ('—', ''))
        domain = entity.id.partition('.')[0]
        controlled = domain in CONTROL_DOMAINS
        label = escape(entity.label)
        kind = 'temperature' if domain == 'climate' or (domain == 'sensor' and unit in {'°C', '°F'}) else domain
        label_html = f'<span class="tile-label">{glyph(kind)} {label}</span>'
        if domain == 'climate':
            inner = climate_tile(entity, status['climates'].get(entity.id), status['stale'], csrf, label_html)
        elif controlled and csrf:
            available = value in {'on', 'off'} and not status['stale']
            state = {'on': 'On', 'off': 'Off'}.get(value, 'Unavailable')
            inner = (f'<form method="post" action="/control" class="control-form">{fields(csrf, entity.id)}'
                     f'<button class="tile control{" is-on" if value == "on" else ""}" type="submit" name="action" '
                     f'value="{"turn_off" if value == "on" else "turn_on"}" aria-label="{label} power" '
                     f'aria-pressed="{str(value == "on").lower()}" {"" if available else "disabled"} data-available="{"yes" if available else "no"}">'
                     f'{label_html}<span class="power" aria-hidden="true">⏻</span><strong class="tile-value">{state}</strong></button>'
                     '<span class="feedback" role="status"></span></form>')
        else:
            text = 'Unavailable' if value in {'unavailable', 'unknown'} else value
            inner = (f'<div class="tile">{label_html}<strong class="tile-value">{escape(text)}</strong>'
                     f'<span class="tile-unit">{escape(unit)}</span></div>')
        rows.setdefault(entity.cell // 4, {})[entity.cell % 4] = (entity.width, entity.id, inner)
    grid = ''
    for row in range(max(rows, default=-1) + 1):
        column, parts = 0, []
        while column < 4:
            item = rows.get(row, {}).get(column)
            if item:
                width, entity_id, inner = item
                parts.append(f'<li class="slot w{width}" data-id="{escape(entity_id)}">{inner}</li>')
                column += width
            else:
                parts.append('<li class="slot w1 gap" aria-hidden="true"></li>')
                column += 1
        grid += '<ul class="tile-row">' + ''.join(parts) + '</ul>'
    weather = status['weather'] or {'value': '', 'unit': '', 'condition': ''}
    weather_html = (
        f'<div class="weather" id="weather-card" {"" if status["weather"] else "hidden"}><span id="weather-icon" aria-hidden="true">{status["weatherIcon"]}</span><div><strong id="weather-value">'
        f'{escape(weather["value"])} {escape(weather["unit"])}</strong>'
        f'<span id="weather-condition">{escape(weather["condition"])}</span></div></div>')
    body = (f'<div id="dashboard" data-interval="{settings.refresh_seconds}" data-clock="{status["clockEpoch"]}"><header class="overview">'
            f'<div><p class="eyebrow">{escape(settings.title)}</p><h1 class="clock" id="clock">{status["clock"]}</h1>'
            f'<p id="date">{status["date"]}</p><p class="hint" id="timezone-label">{escape(status["zoneLabel"])}</p><p class="warning" id="clock-sync" role="status"></p></div><div class="conditions">{weather_html}'
            f'<p class="update{" warning" if status["stale"] else ""}" id="update"><span id="connection">{status["status"]}</span> '
            f'· Last update <time id="last-update">{status["updated"]}</time></p></div></header>')
    if notice:
        body += f'<p class="notice" role="status">{escape(notice)}</p>'
    body += (grid or '<p class="empty">No widgets yet. <a href="/edit">Add your first widget</a>.</p>') + '</div>'
    return page(settings.title, body, f'{settings.refresh_seconds};url=/' if notice else settings.refresh_seconds,
                navigation(csrf) if csrf else '', theme, 'dashboard' if csrf else '')


def editor_page(panel, csrf):
    layout = panel.selection.layout
    widgets = panel.entities if panel.settings.demo else layout.entities
    model = {'entities': [asdict(e) for e in widgets], 'weather': panel.weather_source,
             'theme': layout.theme, 'demo': panel.settings.demo, 'cells': CELLS, 'limit': MAX_ENTITIES,
             'timezone': panel.timezone_mode}
    body = (f'<div id="editor" data-layout="{escape(json.dumps(model))}">{fields(csrf)}'
            '<div class="editor-header"><div><p class="eyebrow">Panel settings</p><h1>Arrange widgets</h1>'
            '<p class="hint">Select a widget. Drag its handle, tap a cell, or use the arrows to move it.</p></div>'
            '<div class="toolbar"><a class="button" id="discard-layout" href="/">Discard draft</a> <button type="button" id="save-layout" class="primary" disabled>Save layout</button></div></div>'
            '<div class="appearance"><strong>Panel theme</strong><div class="toolbar" role="group" aria-label="Panel theme">'
            f'<button type="button" data-theme-choice="light" aria-pressed="{str(layout.theme == "light").lower()}">Light</button> '
            f'<button type="button" data-theme-choice="dark" aria-pressed="{str(layout.theme == "dark").lower()}">Dark</button></div></div>'
            '<div class="editor-columns"><section aria-label="Layout"><div id="board" class="board"></div>'
            '<p id="edit-note" class="notice" role="status"></p></section>'
            '<section class="inspector"><h2>Selected widget</h2><p id="selected-id" class="hint">Select a tile</p>'
            '<label>Label<input type="text" id="widget-label" maxlength="120"></label>'
            '<p class="hint">Size</p><div class="toolbar"><button type="button" data-width="1">1 × 1</button> '
            '<button type="button" data-width="2">2 × 1</button></div><p class="hint">Position</p><div class="toolbar">'
            '<button type="button" data-move="-1" aria-label="Move left">←</button> '
            '<button type="button" data-move="-4" aria-label="Move up">↑</button> '
            '<button type="button" data-move="4" aria-label="Move down">↓</button> '
            '<button type="button" data-move="1" aria-label="Move right">→</button></div>'
            '<button type="button" id="remove-widget" class="danger">Remove from layout</button></section></div>'
            '<details open id="library"><summary>Add a widget</summary><div class="catalogue">'
            '<form id="device-search" class="search"><label>Find by name or entity ID<input name="q" maxlength="100" placeholder="Living room, sensor…"></label>'
            '<label>Type<select name="type"><option value="all">All</option><option value="light">Lights</option>'
            '<option value="switch">Switches</option><option value="climate">Climate</option><option value="sensor">Sensors</option><option value="weather">Weather</option></select></label>'
            '<button type="submit">Search</button></form><div class="editor-columns"><section><p id="search-note" role="status" class="hint" tabindex="-1"></p>'
            '<ul id="results" class="results"></ul><div id="pages" class="toolbar"></div></section>'
            '<section class="inspector"><h2>Preview</h2><div id="preview" class="tile"><span class="hint">Choose a result to preview it.</span></div>'
            '<label>Label on panel<input id="add-label" maxlength="120"></label><button id="add-widget" class="primary" type="button" disabled>Add to layout</button></section></div></div></details>'
            '<details id="weather-settings"><summary>Weather next to the clock</summary><div class="catalogue"><label>Weather source<select id="weather-source">'
            '<option value="auto">Automatic — Home Assistant</option><option value="">Hide weather</option></select></label>'
            '<p id="weather-note" role="status" class="hint">Change this with Save layout.</p></div></details>'
            '<details id="timezone-settings"><summary>Time zone</summary><div class="catalogue">'
            f'<p id="current-zone" class="hint">Current: {escape(panel.timezone_display()[1])}</p>'
            '<button type="button" id="auto-zone">Use Home Assistant time zone</button>'
            '<label>Find a city or time zone<input type="search" id="zone-query" placeholder="Moscow, Europe/Berlin, UTC"></label>'
            '<label>Matching time zones<select id="zone-choice"></select></label>'
            '<button type="button" id="save-zone" disabled>Use selected time zone</button><p id="zone-note" role="status" class="hint">Applies immediately.</p></div></details>'
            '<noscript><p>The visual editor requires JavaScript. <a href="/settings">Open basic device settings</a>.</p></noscript></div>')
    return page('Panel settings', body, navigation=navigation(csrf, True), theme=layout.theme, script='editor')
