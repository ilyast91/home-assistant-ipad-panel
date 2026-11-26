(function () {
  'use strict';
  var root = document.getElementById('dashboard');
  if (!root || !window.XMLHttpRequest) { return; }
  var slots = root.querySelectorAll('[data-id]'), pending = {}, serial = 0, applied = 0;
  var interval = Number(root.getAttribute('data-interval')) * 1000;
  var clockEpoch = Number(root.getAttribute('data-clock')), syncedAt = Date.now(), connected = true;
  var weekdays = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  var months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  function text(id, value) { document.getElementById(id).textContent = value; }
  function pad(n) { return n < 10 ? '0' + n : String(n); }
  function tick() {
    // The server encodes its local wall time as UTC fields for clients without time-zone support.
    var local = new Date(clockEpoch + Date.now() - syncedAt);
    text('clock', pad(local.getUTCHours()) + ':' + pad(local.getUTCMinutes()));
    text('date', weekdays[local.getUTCDay()] + ', ' + pad(local.getUTCDate()) + ' ' + months[local.getUTCMonth()]);
  }
  function request(method, path, body, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, path, true);
    xhr.setRequestHeader('Accept', 'application/json');
    if (body) { xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded'); }
    xhr.timeout = 25000;
    xhr.onload = function () {
      var result;
      try { result = JSON.parse(xhr.responseText); } catch (err) { result = {}; }
      done(xhr.status, result);
    };
    xhr.onerror = xhr.ontimeout = function () { done(0, {}); };
    xhr.send(body || null);
  }
  function climateAvailability(slot) {
    var inputs = slot.querySelectorAll('button[data-available], select[data-available]');
    var busy = pending[slot.getAttribute('data-id')];
    for (var i = 0; i < inputs.length; i += 1) {
      inputs[i].disabled = !!busy || !connected || inputs[i].getAttribute('data-available') !== 'yes';
    }
  }
  function updateClimate(slot, state, stale) {
    state = state || { available: false, targets: [], modes: [] };
    var unit = state.unit ? ' ' + state.unit : '', rows = slot.querySelectorAll('[data-target]');
    var targets = {}, i, j, target, buttons, active = state.available && !stale;
    slot.querySelector('.climate-current').textContent = state.current == null ? '—' : state.current + unit;
    slot.querySelector('.climate-mode').textContent = state.modeLabel || 'Unavailable';
    for (i = 0; i < state.targets.length; i += 1) { targets[state.targets[i].key] = state.targets[i]; }
    for (i = 0; i < rows.length; i += 1) {
      target = targets[rows[i].getAttribute('data-target')];
      rows[i].hidden = !target;
      rows[i].querySelector('strong').textContent = target ? target.value + unit : '—';
      buttons = rows[i].querySelectorAll('button');
      for (j = 0; j < buttons.length; j += 1) {
        buttons[j].setAttribute('data-available', active && target && target[buttons[j].getAttribute('data-direction')] ? 'yes' : 'no');
      }
    }
    var form = slot.querySelector('.climate-modes'), select = form.elements.value;
    var signature = state.modes.map(function (mode) { return mode.id; }).join(',');
    form.hidden = !signature;
    if (select.getAttribute('data-modes') !== signature) {
      var old = select.value;
      select.length = 1;
      for (i = 0; i < state.modes.length; i += 1) { select.add(new Option(state.modes[i].label, state.modes[i].id)); }
      select.value = old;
      if (select.selectedIndex === -1) { select.selectedIndex = 0; }
      select.setAttribute('data-modes', signature);
    }
    var allowed = active && signature ? 'yes' : 'no';
    select.setAttribute('data-available', allowed);
    form.querySelector('button').setAttribute('data-available', allowed);
    climateAvailability(slot);
  }
  function apply(data, version, only) {
    var i, slot, id, value, button, flag, unit;
    if ((!only && version < applied) || !data.values) { return; }
    if (!only) {
      applied = version;
      connected = true;
      clockEpoch = data.clockEpoch;
      syncedAt = Date.now();
      tick();
      text('timezone-label', data.zoneLabel);
      text('clock-sync', '');
      text('last-update', data.updated);
      text('connection', data.status);
      document.getElementById('update').className = 'update' + (data.stale ? ' warning' : '');
      document.getElementById('weather-card').hidden = !data.weather;
      if (data.weather) {
        text('weather-value', data.weather.value + ' ' + data.weather.unit);
        text('weather-condition', data.weather.condition);
        text('weather-icon', data.weatherIcon);
      }
    }
    for (i = 0; i < slots.length; i += 1) {
      slot = slots[i];
      id = slot.getAttribute('data-id');
      if (pending[id] || (only && only !== id)) { continue; }
      value = data.values[id] || ['—', ''];
      button = slot.querySelector('button.control');
      if (slot.querySelector('.climate')) {
        updateClimate(slot, (data.climates || {})[id], data.stale);
      } else if (button) {
        flag = value[0] === 'on';
        button.className = 'tile control' + (flag ? ' is-on' : '');
        button.value = flag ? 'turn_off' : 'turn_on';
        button.setAttribute('aria-pressed', flag ? 'true' : 'false');
        button.setAttribute('data-available', !data.stale && (value[0] === 'on' || value[0] === 'off') ? 'yes' : 'no');
        button.disabled = !connected || button.getAttribute('data-available') !== 'yes';
        button.querySelector('.tile-value').textContent = flag ? 'On' : (value[0] === 'off' ? 'Off' : 'Unavailable');
      } else {
        slot.querySelector('.tile-value').textContent = value[0] === 'unavailable' || value[0] === 'unknown' ? 'Unavailable' : value[0];
        unit = slot.querySelector('.tile-unit');
        if (unit) { unit.textContent = value[1]; }
      }
    }
  }
  function poll() {
    var version = ++serial;
    request('GET', '/data', null, function (code, data) {
      if (code === 401) { window.location.replace('/'); return; }
      if (code === 200 && data.values) { apply(data, version); }
      else if (version >= applied) {
        connected = false;
        text('connection', 'Connection lost');
        text('clock-sync', 'Clock not synchronized');
        document.getElementById('update').className = 'update warning';
        var buttons = root.querySelectorAll('.control, .climate button, .climate select');
        for (var i = 0; i < buttons.length; i += 1) { buttons[i].disabled = true; }
      }
      window.setTimeout(poll, connected ? interval : Math.min(interval, 5000));
    });
  }
  function control(event) {
    event.preventDefault();
    var form = this, button = form.querySelector('button'), feedback = form.querySelector('.feedback');
    var id = form.elements.id.value, focused = document.activeElement === button;
    if (button.disabled || pending[id]) { return; }
    pending[id] = true;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    feedback.className = 'feedback';
    feedback.textContent = 'Working…';
    request('POST', '/control', 'csrf=' + encodeURIComponent(form.elements.csrf.value) +
      '&id=' + encodeURIComponent(id) + '&action=' + encodeURIComponent(button.value), function (code, result) {
      delete pending[id];
      button.removeAttribute('aria-busy');
      button.disabled = !connected || button.getAttribute('data-available') !== 'yes';
      // Ignore polls started before the command finished; their state may predate confirmation.
      applied = ++serial;
      if (code === 200) { apply(result, applied, id); }
      feedback.className = 'feedback' + (code === 200 ? '' : ' error');
      feedback.textContent = code === 200 ? 'State confirmed' : (result.error || 'Could not confirm. Check the device and try again.');
      if (focused && document.activeElement === document.body && !button.disabled) { button.focus(); }
    });
  }
  function climateControl(event) {
    event.preventDefault();
    var form = this, id = form.elements.id.value, button = form.querySelector('button');
    var slot = form.parentNode;
    while (slot && slot.getAttribute('data-id') !== id) { slot = slot.parentElement; }
    if (!slot || button.disabled || pending[id]) { return; }
    var feedback = slot.querySelector('.feedback'), select = form.elements.value;
    var value = select ? select.value : '', focused = document.activeElement === button;
    pending[id] = true;
    climateAvailability(slot);
    slot.setAttribute('aria-busy', 'true');
    feedback.className = 'feedback'; feedback.textContent = 'Working…';
    request('POST', '/climate', 'csrf=' + encodeURIComponent(form.elements.csrf.value) +
      '&id=' + encodeURIComponent(id) + '&action=' + encodeURIComponent(form.elements.action.value) +
      '&value=' + encodeURIComponent(value), function (code, result) {
      delete pending[id]; slot.removeAttribute('aria-busy');
      applied = ++serial;
      if (code === 200) { apply(result, applied, id); if (select) { select.selectedIndex = 0; } }
      climateAvailability(slot);
      feedback.className = 'feedback' + (code === 200 ? '' : ' error');
      feedback.textContent = code === 200 ? 'State confirmed' : (result.error || 'Could not confirm. Check the device and try again.');
      if (focused && document.activeElement === document.body && !button.disabled) { button.focus(); }
    });
  }
  var forms = root.querySelectorAll('.control-form');
  for (var j = 0; j < forms.length; j += 1) { forms[j].addEventListener('submit', control, false); }
  var climates = root.querySelectorAll('.climate-form');
  for (var k = 0; k < climates.length; k += 1) { climates[k].addEventListener('submit', climateControl, false); }
  window.setInterval(tick, 1000);
  window.setTimeout(poll, interval);
}());
