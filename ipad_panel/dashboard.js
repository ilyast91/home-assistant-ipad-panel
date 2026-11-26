(function () {
  'use strict';
  var root = document.getElementById('dashboard');
  if (!root || !window.XMLHttpRequest) { return; }
  var slots = root.querySelectorAll('[data-id]'), pending = {}, serial = 0, applied = 0;
  var interval = Number(root.getAttribute('data-interval')) * 1000;

  function text(id, value) { document.getElementById(id).textContent = value; }
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
  function apply(data, version, only) {
    var i, slot, id, value, button, flag, unit;
    if ((!only && version < applied) || !data.values) { return; }
    if (!only) {
      applied = version;
      text('clock', data.clock);
      text('date', data.date);
      text('timezone-label', data.zoneLabel);
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
      if (button) {
        flag = value[0] === 'on';
        button.className = 'tile control' + (flag ? ' is-on' : '');
        button.value = flag ? 'turn_off' : 'turn_on';
        button.setAttribute('aria-pressed', flag ? 'true' : 'false');
        button.disabled = data.stale || (value[0] !== 'on' && value[0] !== 'off');
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
      if (code === 200) { apply(data, version); }
      else if (version >= applied) {
        text('connection', 'Connection lost');
        document.getElementById('update').className = 'update warning';
        var buttons = root.querySelectorAll('.control');
        for (var i = 0; i < buttons.length; i += 1) { buttons[i].disabled = true; }
      }
      window.setTimeout(poll, interval);
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
      button.disabled = false;
      // Ignore polls started before the command finished; their state may predate confirmation.
      applied = ++serial;
      if (code === 200) { apply(result, applied, id); }
      feedback.className = 'feedback' + (code === 200 ? '' : ' error');
      feedback.textContent = code === 200 ? 'State confirmed' : (result.error || 'Could not confirm. Check the device and try again.');
      if (focused && document.activeElement === document.body && !button.disabled) { button.focus(); }
    });
  }
  var forms = root.querySelectorAll('.control-form');
  for (var j = 0; j < forms.length; j += 1) { forms[j].addEventListener('submit', control, false); }
  window.setTimeout(poll, interval);
}());
