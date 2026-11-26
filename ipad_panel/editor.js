(function () {
  'use strict';
  var root = document.getElementById('editor');
  if (!root || !window.XMLHttpRequest) { return; }
  var model = JSON.parse(root.getAttribute('data-layout')), tiles = model.entities;
  var picked = '', preview = null, drag = null, searchSerial = 0, themePending = false, saving = false;
  var csrf = root.querySelector('[name=csrf]').value;
  var board = get('board'), save = get('save-layout'), note = get('edit-note');
  var label = get('widget-label'), remove = get('remove-widget'), weather = get('weather-source');
  var add = get('add-widget'), results = get('results'), search = get('device-search');
  var offset = 0, chosenType = 'all', query = '';

  function get(id) { return document.getElementById(id); }
  function request(path, fields, done) {
    var xhr = new XMLHttpRequest(), bits = [], key;
    xhr.open(fields ? 'POST' : 'GET', path, true);
    xhr.setRequestHeader('Accept', 'application/json');
    if (fields) {
      fields.csrf = csrf;
      for (key in fields) { if (Object.prototype.hasOwnProperty.call(fields, key)) { bits.push(key + '=' + encodeURIComponent(fields[key])); } }
      xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    }
    xhr.timeout = 8000;
    xhr.onload = function () {
      var data;
      try { data = JSON.parse(xhr.responseText); } catch (err) { data = {}; }
      done(xhr.status, data);
    };
    xhr.onerror = xhr.ontimeout = function () { done(0, {}); };
    xhr.send(fields ? bits.join('&') : null);
  }
  function button(text, handler) {
    var node = document.createElement('button');
    node.type = 'button'; node.textContent = text;
    if (handler) { node.onclick = handler; }
    return node;
  }
  function find(id) {
    for (var i = 0; i < tiles.length; i += 1) { if (tiles[i].id === id) { return tiles[i]; } }
    return null;
  }
  function fits(cell, width, ignore) {
    if (cell < 0 || cell >= model.cells || cell % 4 + width > 4) { return false; }
    for (var i = 0; i < tiles.length; i += 1) {
      var other = tiles[i];
      if (other.id !== ignore && cell < other.cell + other.width && other.cell < cell + width) { return false; }
    }
    return true;
  }
  function changed(text) {
    save.disabled = saving;
    note.textContent = text || 'Unsaved layout changes.';
  }
  function move(cell, width) {
    var tile = find(picked);
    if (!tile || saving) { return; }
    if (!fits(cell, width, picked)) { note.textContent = 'This position is occupied or the widget does not fit.'; return; }
    tile.cell = cell; tile.width = width;
    changed(); draw();
  }
  function draw() {
    var selected = find(picked), slots = {}, i, cells, row, tile, slot, cell, grip, moves;
    var focusId = document.activeElement && document.activeElement.getAttribute('data-focus');
    var focusTarget = null;
    for (i = 0, cells = 8; i < tiles.length; i += 1) {
      cells = Math.max(cells, Math.ceil((tiles[i].cell + 1) / 4) * 4 + 4);
      slots[tiles[i].cell] = tiles[i];
    }
    board.textContent = '';
    for (i = 0; i < Math.min(model.cells, cells); i += 1) {
      if (i % 4 === 0) { row = document.createElement('div'); row.className = 'board-row'; board.appendChild(row); }
      tile = slots[i];
      slot = document.createElement('div'); slot.className = 'slot w' + (tile ? tile.width : '1');
      if (tile) {
        cell = button(tile.label + ' · ' + tile.width + ' × 1', function () {
          picked = this.getAttribute('data-widget'); draw();
        });
        cell.className = 'cell' + (tile.id === picked ? ' selected' : '');
        cell.setAttribute('data-widget', tile.id);
        cell.setAttribute('data-focus', tile.id);
        cell.setAttribute('aria-pressed', tile.id === picked ? 'true' : 'false');
        slot.appendChild(cell);
        grip = button('↔ Move', function () { picked = this.getAttribute('data-grip'); draw(); });
        grip.className = 'handle'; grip.setAttribute('data-grip', tile.id);
        grip.setAttribute('aria-label', 'Move ' + tile.label);
        slot.appendChild(grip);
      } else {
        cell = button('+', function () { var t = find(picked); if (t) { move(Number(this.getAttribute('data-cell')), t.width); } });
        cell.className = 'cell empty-cell'; cell.setAttribute('data-cell', i);
        cell.setAttribute('aria-label', 'Move to row ' + (Math.floor(i / 4) + 1) + ', column ' + (i % 4 + 1));
        cell.disabled = !selected;
        slot.appendChild(cell);
      }
      if (focusId && cell.getAttribute('data-focus') === focusId) { focusTarget = cell; }
      row.appendChild(slot);
      if (tile) { i += tile.width - 1; }
    }
    if (focusTarget) { focusTarget.focus(); }
    get('selected-id').textContent = selected ? selected.id : 'Select a widget or add one below.';
    label.disabled = remove.disabled = !selected;
    label.value = selected ? selected.label : '';
    moves = root.querySelectorAll('[data-width], [data-move]');
    for (i = 0; i < moves.length; i += 1) {
      moves[i].disabled = !selected;
      if (moves[i].hasAttribute('data-width')) { moves[i].setAttribute('aria-pressed', selected && selected.width === Number(moves[i].getAttribute('data-width')) ? 'true' : 'false'); }
    }
    if (preview) { updatePreview(preview, true); }
  }
  function touchCell(touch) {
    var hit = document.elementFromPoint(touch.clientX, touch.clientY);
    while (hit && hit !== board) { if (hit.hasAttribute('data-cell')) { return hit; } hit = hit.parentElement; }
    return null;
  }
  function highlight(cell) {
    if (drag.mark) { drag.mark.className = 'cell empty-cell'; }
    drag.mark = cell;
    if (cell) { cell.className = 'cell empty-cell drag-target'; }
  }
  board.addEventListener('touchstart', function (event) {
    var id = event.target.getAttribute('data-grip');
    if (id && !saving && event.touches.length === 1) {
      event.preventDefault();
      drag = { id: id, mark: null };
      note.textContent = 'Drag to a free cell.';
    }
  }, false);
  board.addEventListener('touchmove', function (event) {
    if (!drag || event.touches.length !== 1) { return; }
    event.preventDefault();
    var cell = touchCell(event.touches[0]), tile = find(drag.id);
    highlight(cell && tile && fits(Number(cell.getAttribute('data-cell')), tile.width, tile.id) ? cell : null);
  }, false);
  board.addEventListener('touchend', function (event) {
    if (!drag) { return; }
    event.preventDefault();
    var cell = touchCell(event.changedTouches[0]), widget = find(drag.id);
    highlight(null); picked = drag.id; drag = null;
    if (cell && widget) { move(Number(cell.getAttribute('data-cell')), widget.width); }
    else { draw(); note.textContent = 'Select a free cell to place the widget.'; }
  }, false);
  board.addEventListener('touchcancel', function () { if (drag) { highlight(null); drag = null; } }, false);

  function setupActions() {
    var widths = root.querySelectorAll('[data-width]'), arrows = root.querySelectorAll('[data-move]'), i;
    for (i = 0; i < widths.length; i += 1) { widths[i].onclick = function () {
      var tile = find(picked); if (tile) { move(tile.cell, Number(this.getAttribute('data-width'))); }
    }; }
    for (i = 0; i < arrows.length; i += 1) { arrows[i].onclick = function () {
      var tile = find(picked), step = Number(this.getAttribute('data-move'));
      if (!tile) { return; }
      if (Math.abs(step) === 1 && Math.floor((tile.cell + step) / 4) !== Math.floor(tile.cell / 4)) {
        note.textContent = 'This is the edge of the row.'; return;
      }
      move(tile.cell + step, tile.width);
    }; }
  }
  function updatePreview(item, keepLabel) {
    preview = item;
    var existing = find(item.id), widget = get('preview'), heading = document.createElement('strong');
    var domain = item.id.split('.')[0], detail = document.createElement('p');
    heading.className = 'tile-label'; heading.textContent = item.label;
    detail.className = 'tile-value'; detail.textContent = (domain === 'light' || domain === 'switch') ? 'On / Off' : (domain === 'weather' ? 'Weather' : 'Sensor reading');
    widget.textContent = ''; widget.appendChild(heading); widget.appendChild(detail);
    if (!keepLabel) { get('add-label').value = existing ? existing.label : item.label; }
    add.disabled = !!existing || tiles.length >= model.limit;
    add.textContent = existing ? 'Already on panel' : 'Add to layout';
  }
  function showResults(data) {
    results.textContent = ''; get('pages').textContent = '';
    get('search-note').textContent = data.total ? data.total + ' matching devices' : 'No matching devices.';
    for (var i = 0; i < data.items.length; i += 1) {
      var item = data.items[i], li = document.createElement('li'), detail = document.createElement('small');
      var entry = button(item.label + (find(item.id) ? ' · On panel' : ''), (function (choice) {
        return function () { updatePreview(choice, false); };
      }(item)));
      detail.textContent = item.id; entry.appendChild(detail); li.appendChild(entry); results.appendChild(li);
    }
    if (offset) { get('pages').appendChild(button('Previous', function () { offset = Math.max(0, offset - 30); load(); })); }
    if (offset + 30 < data.total) { get('pages').appendChild(button('Next', function () { offset += 30; load(); })); }
  }
  function load() {
    var version = ++searchSerial;
    get('search-note').textContent = 'Loading devices…';
    results.textContent = ''; get('pages').textContent = '';
    request('/catalogue?type=' + encodeURIComponent(chosenType) + '&q=' + encodeURIComponent(query) + '&offset=' + offset, null, function (status, data) {
      if (version !== searchSerial) { return; }
      if (status === 200) { showResults(data); }
      else { get('search-note').textContent = data.error || 'Could not search. Try again.'; }
    });
  }
  function addWeatherOption(id, title) {
    var option = document.createElement('option'); option.value = id; option.textContent = title;
    weather.appendChild(option);
  }
  function loadWeather() {
    request('/catalogue?type=weather', null, function (status, data) {
      if (status === 200) {
        var existing = !model.weather || model.weather === 'auto';
        for (var i = 0; i < data.items.length; i += 1) {
          addWeatherOption(data.items[i].id, data.items[i].label);
          existing = existing || data.items[i].id === model.weather;
        }
        if (model.weather && !existing) { addWeatherOption(model.weather, model.weather + ' (current)'); }
        weather.value = model.weather;
      } else {
        if (model.weather && model.weather !== 'auto') { addWeatherOption(model.weather, model.weather + ' (current)'); }
        weather.value = model.weather;
        get('weather-note').textContent = 'Weather devices are unavailable. You can keep or hide the current one.';
      }
    });
  }
  function setupTimezones() {
    var input = get('zone-query'), choice = get('zone-choice'), submit = get('save-zone');
    var auto = get('auto-zone'), message = get('zone-note'), zones = [], busy = false;
    function filterZones() {
      var query = input.value.toLowerCase().trim().replace(/ /g, '_');
      var matches = zones.filter(function (name) { return name.toLowerCase().indexOf(query) !== -1; });
      var i, option;
      choice.textContent = '';
      for (i = 0; i < Math.min(matches.length, 50); i += 1) {
        option = document.createElement('option'); option.value = matches[i];
        option.textContent = matches[i].replace(/_/g, ' '); choice.appendChild(option);
      }
      submit.disabled = busy || !matches.length;
      message.textContent = matches.length > 50 ? 'Type a city or region to narrow the list.' : (matches.length ? 'Applies immediately.' : 'No matching time zones.');
    }
    function saveZone(value) {
      if (busy || !value) { return; }
      busy = true; auto.disabled = submit.disabled = true;
      message.textContent = 'Saving time zone…';
      request('/timezone', { timezone: value }, function (status, data) {
        busy = false; auto.disabled = false; submit.disabled = !choice.value;
        if (status === 200) {
          get('current-zone').textContent = 'Current: ' + data.label;
          message.textContent = 'Time zone saved.';
        } else { message.textContent = data.error || 'Could not save the time zone.'; }
      });
    }
    input.oninput = filterZones;
    submit.onclick = function () { saveZone(choice.value); };
    auto.onclick = function () { saveZone('auto'); };
    request('/timezones', null, function (status, data) {
      if (status === 200 && Array.isArray(data)) { zones = data; filterZones(); }
      else { message.textContent = 'Could not load time zones.'; }
    });
  }
  function displayTheme(theme) {
    var options = root.querySelectorAll('[data-theme-choice]');
    document.documentElement.setAttribute('data-theme', theme);
    for (var i = 0; i < options.length; i += 1) { options[i].setAttribute('aria-pressed', options[i].getAttribute('data-theme-choice') === theme ? 'true' : 'false'); }
  }
  function changeTheme() {
    if (themePending) { return; }
    var choice = this.getAttribute('data-theme-choice');
    displayTheme(choice); themePending = true;
    request('/theme', { theme: choice }, function (status, data) {
      themePending = false;
      if (status === 200) { model.theme = data.theme; }
      else { displayTheme(model.theme); note.textContent = data.error || 'Could not save theme.'; }
    });
  }

  label.oninput = function () {
    var tile = find(picked);
    if (tile && !saving) {
      tile.label = this.value.trim() || tile.id;
      var caption = board.querySelector('.cell.selected');
      if (caption) { caption.textContent = tile.label + ' · ' + tile.width + ' × 1'; }
      changed();
    }
  };
  remove.onclick = function () {
    if (saving) { return; }
    tiles = tiles.filter(function (t) { return t.id !== picked; }); picked = '';
    changed('Widget removed from the draft.'); draw(); load();
  };
  search.onsubmit = function (event) {
    event.preventDefault(); query = search.elements.q.value; chosenType = search.elements.type.value; offset = 0; load();
  };
  search.elements.type.onchange = function () { chosenType = this.value; offset = 0; load(); };
  add.onclick = function () {
    if (saving || !preview || find(preview.id) || tiles.length >= model.limit) { return; }
    var cell = 0;
    while (cell < model.cells && !fits(cell, 1, '')) { cell += 1; }
    if (cell >= model.cells) { note.textContent = 'No free grid cell.'; return; }
    tiles.push({ id: preview.id, label: get('add-label').value.trim() || preview.label, cell: cell, width: 1 });
    picked = preview.id; changed('Widget added to the draft.'); draw(); load();
    if (board.scrollIntoView) { board.scrollIntoView(); }
  };
  weather.onchange = function () { if (!saving) { model.weather = weather.value; changed(); } };
  save.onclick = function () {
    saving = true; save.disabled = true; label.disabled = true; weather.disabled = true; note.textContent = 'Saving layout…';
    request('/layout', { widgets: JSON.stringify(tiles), weather: model.weather }, function (status, data) {
      if (status === 200 && data.saved) { window.location.assign('/'); }
      else { saving = false; weather.disabled = false; draw(); changed(data.error || 'Could not save. Try again.'); }
    });
  };
  var themes = root.querySelectorAll('[data-theme-choice]');
  for (var i = 0; i < themes.length; i += 1) { themes[i].onclick = changeTheme; }
  setupActions(); draw(); load(); loadWeather(); setupTimezones();
}());
