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
  var offset = 0, chosenType = 'all', query = '', dirty = false, scrollTimer = null;

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
  function fits(cell, width, height, ignore) {
    if (cell < 0 || cell + (height - 1) * 4 >= model.cells || cell % 4 + width > 4) { return false; }
    var x = cell % 4, y = Math.floor(cell / 4);
    for (var i = 0; i < tiles.length; i += 1) {
      var other = tiles[i], ox = other.cell % 4, oy = Math.floor(other.cell / 4);
      if (other.id !== ignore && x < ox + other.width && ox < x + width && y < oy + other.height && oy < y + height) { return false; }
    }
    return true;
  }
  function changed(text) {
    dirty = true;
    save.disabled = saving;
    note.textContent = text || 'Unsaved layout changes.';
  }
  function move(cell, width, height, id, focus) {
    var tile = find(id || picked);
    if (!tile || saving) { return; }
    if (!fits(cell, width, height, tile.id)) {
      note.textContent = 'This position is occupied or the widget does not fit. Other widgets were not moved.';
      var selected = board.querySelector('.cell.selected');
      if (selected) { selected.classList.add('grid-conflict'); }
      return;
    }
    picked = tile.id;
    tile.cell = cell; tile.width = width; tile.height = height;
    changed(); draw(focus ? picked : null);
  }
  function draw(keepFocus) {
    var selected = find(picked), slots = {}, occupied = {}, i, r, c, cells, row, tile, slot, cell, grip, moves;
    var focusId = keepFocus || (document.activeElement && document.activeElement.getAttribute('data-focus'));
    var focusTarget = null;
    for (i = 0, cells = 8; i < tiles.length; i += 1) {
      tile = tiles[i];
      cells = Math.max(cells, (Math.floor(tile.cell / 4) + tile.height + 1) * 4);
      slots[tile.cell] = tile;
      for (r = 0; r < tile.height; r += 1) {
        for (c = 0; c < tile.width; c += 1) { occupied[tile.cell + r * 4 + c] = true; }
      }
    }
    board.textContent = '';
    for (i = 0; i < Math.min(model.cells, cells); i += 1) {
      if (i % 4 === 0) { row = document.createElement('div'); row.className = 'board-row'; board.appendChild(row); }
      tile = slots[i];
      if (!tile && occupied[i]) { continue; }
      slot = document.createElement('div'); slot.className = tile ? 'slot w' + tile.width + ' h' + tile.height : 'slot w1 h1';
      slot.style.left = (i % 4 * 25) + '%';
      if (tile) {
        cell = button(tile.label + ' · ' + tile.width + ' × ' + tile.height, function () {
          picked = this.getAttribute('data-widget'); draw();
        });
        cell.className = 'cell' + (tile.id === picked ? ' selected' : '');
        cell.setAttribute('data-widget', tile.id);
        cell.setAttribute('data-focus', tile.id);
        cell.setAttribute('aria-pressed', tile.id === picked ? 'true' : 'false');
        slot.appendChild(cell);
        grip = button('↔ Move', function () {
          picked = this.getAttribute('data-grip'); draw(picked);
          note.textContent = 'Choose a free cell. You can scroll to another row first.';
        });
        grip.className = 'handle'; grip.setAttribute('data-grip', tile.id);
        grip.setAttribute('aria-label', 'Move ' + tile.label);
        slot.appendChild(grip);
      } else {
        cell = button('+', function () { var t = find(picked); if (t) { move(Number(this.getAttribute('data-cell')), t.width, t.height, t.id, true); } });
        cell.className = 'cell empty-cell'; cell.setAttribute('data-cell', i);
        cell.setAttribute('aria-label', 'Move to row ' + (Math.floor(i / 4) + 1) + ', column ' + (i % 4 + 1));
        cell.disabled = !selected;
        slot.appendChild(cell);
      }
      if (focusId && cell.getAttribute('data-focus') === focusId) { focusTarget = cell; }
      row.appendChild(slot);
    }
    if (focusTarget) { focusTarget.focus(); }
    get('selected-id').textContent = selected ? selected.id : 'Select a widget or add one below.';
    label.disabled = remove.disabled = !selected;
    label.value = selected ? selected.label : '';
    moves = root.querySelectorAll('[data-width], [data-move]');
    for (i = 0; i < moves.length; i += 1) {
      moves[i].disabled = !selected;
      if (moves[i].hasAttribute('data-width')) { moves[i].setAttribute('aria-pressed', selected && selected.width === Number(moves[i].getAttribute('data-width')) && selected.height === Number(moves[i].getAttribute('data-height')) ? 'true' : 'false'); }
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
      drag = { id: id, mark: null, touch: event.touches[0], startX: event.touches[0].clientX, startY: event.touches[0].clientY };
      note.textContent = 'Drag to a free cell, or tap Move and choose one.';
      scrollTimer = window.setInterval(function () {
        if (!drag || !drag.moved) { return; }
        var y = drag.touch.clientY, delta = y < 44 ? -15 : (y > window.innerHeight - 44 ? 15 : 0);
        if (delta) { window.scrollBy(0, delta); markDestination(); }
      }, 35);
    }
  }, false);
  board.addEventListener('touchmove', function (event) {
    if (!drag || event.touches.length !== 1) { return; }
    event.preventDefault();
    drag.touch = event.touches[0];
    drag.moved = drag.moved || Math.abs(drag.touch.clientX - drag.startX) + Math.abs(drag.touch.clientY - drag.startY) > 6;
    markDestination();
  }, false);
  function markDestination() {
    var cell = touchCell(drag.touch), tile = find(drag.id);
    highlight(cell && tile && fits(Number(cell.getAttribute('data-cell')), tile.width, tile.height, tile.id) ? cell : null);
  }
  function endDrag() { highlight(null); window.clearInterval(scrollTimer); drag = null; }
  board.addEventListener('touchend', function (event) {
    if (!drag) { return; }
    event.preventDefault();
    var touch = event.changedTouches[0], cell = touchCell(touch), widget = find(drag.id);
    var moved = drag.moved || Math.abs(touch.clientX - drag.startX) + Math.abs(touch.clientY - drag.startY) > 6;
    endDrag();
    if (cell && widget) { move(Number(cell.getAttribute('data-cell')), widget.width, widget.height, widget.id, true); }
    else if (!moved && widget) {
      picked = widget.id; draw(picked); note.textContent = 'Scroll if needed, then tap a free cell.';
    } else { note.textContent = 'Drop on a free cell to move the widget.'; }
  }, false);
  board.addEventListener('touchcancel', function () { if (drag) { endDrag(); } }, false);

  function setupActions() {
    var widths = root.querySelectorAll('[data-width]'), arrows = root.querySelectorAll('[data-move]'), i;
    for (i = 0; i < widths.length; i += 1) { widths[i].onclick = function () {
      var tile = find(picked); if (tile) { move(tile.cell, Number(this.getAttribute('data-width')), Number(this.getAttribute('data-height'))); }
    }; }
    for (i = 0; i < arrows.length; i += 1) { arrows[i].onclick = function () {
      var tile = find(picked), step = Number(this.getAttribute('data-move'));
      if (!tile) { return; }
      if (Math.abs(step) === 1 && Math.floor((tile.cell + step) / 4) !== Math.floor(tile.cell / 4)) {
        note.textContent = 'This is the edge of the row.'; return;
      }
      move(tile.cell + step, tile.width, tile.height);
    }; }
  }
  function updatePreview(item, keepLabel) {
    preview = item;
    var existing = find(item.id), widget = get('preview'), heading = document.createElement('strong');
    var domain = item.id.split('.')[0], detail = document.createElement('p');
    heading.className = 'tile-label'; heading.textContent = item.label;
    detail.className = 'tile-value'; detail.textContent = (domain === 'light' || domain === 'switch') ? 'On / Off' : (domain === 'climate' ? 'Temperature / mode' : (domain === 'weather' ? 'Weather' : 'Sensor reading'));
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
    if (offset) { get('pages').appendChild(button('Previous', function () { offset = Math.max(0, offset - 30); load(true); })); }
    if (offset + 30 < data.total) { get('pages').appendChild(button('Next', function () { offset += 30; load(true); })); }
  }
  function load(focusResults) {
    var version = ++searchSerial;
    preview = null;
    get('preview').textContent = 'Choose a result to preview it.';
    get('add-label').value = '';
    add.disabled = true;
    add.textContent = 'Add to layout';
    if (focusResults) { get('search-note').focus(); }
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
      if (!query && model.timezone !== 'auto') {
        matches = [model.timezone].concat(matches.filter(function (name) { return name !== model.timezone; }));
      }
      var i, option = document.createElement('option');
      choice.textContent = '';
      option.value = ''; option.textContent = 'Choose a time zone'; choice.appendChild(option);
      for (i = 0; i < Math.min(matches.length, 50); i += 1) {
        option = document.createElement('option'); option.value = matches[i];
        option.textContent = matches[i].replace(/_/g, ' '); choice.appendChild(option);
      }
      choice.value = !query && model.timezone !== 'auto' ? model.timezone : '';
      submit.disabled = busy || !choice.value;
      message.textContent = matches.length > 50 ? 'Type a city or region to narrow the list.' : (matches.length ? 'Applies immediately.' : 'No matching time zones.');
    }
    function saveZone(value) {
      if (busy || !value) { return; }
      busy = true; auto.disabled = submit.disabled = true;
      message.textContent = 'Saving time zone…';
      request('/timezone', { timezone: value }, function (status, data) {
        busy = false; auto.disabled = false; submit.disabled = !choice.value;
        if (status === 200) {
          model.timezone = data.timezone;
          if (model.timezone === 'auto') { input.value = ''; filterZones(); }
          get('current-zone').textContent = 'Current: ' + data.label;
          message.textContent = 'Time zone saved.';
        } else { message.textContent = data.error || 'Could not save the time zone.'; }
      });
    }
    input.oninput = filterZones;
    choice.onchange = function () { submit.disabled = busy || !choice.value; };
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
      if (caption) { caption.textContent = tile.label + ' · ' + tile.width + ' × ' + tile.height; }
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
    while (cell < model.cells && !fits(cell, 1, 1, '')) { cell += 1; }
    if (cell >= model.cells) { note.textContent = 'No free grid cell.'; return; }
    tiles.push({ id: preview.id, label: get('add-label').value.trim() || preview.label, cell: cell, width: 1, height: 1 });
    picked = preview.id; changed('Widget added to the draft.'); draw(); load();
    if (board.scrollIntoView) { board.scrollIntoView(); }
  };
  weather.onchange = function () { if (!saving) { model.weather = weather.value; changed(); } };
  save.onclick = function () {
    saving = true; save.disabled = true; label.disabled = true; weather.disabled = true; note.textContent = 'Saving layout…';
    request('/layout', { widgets: JSON.stringify(tiles), weather: model.weather }, function (status, data) {
      if (status === 200 && data.saved) { dirty = false; window.location.assign('/'); }
      else { saving = false; weather.disabled = false; draw(); changed(data.error || 'Could not save. Try again.'); }
    });
  };
  get('discard-layout').onclick = function () { dirty = false; };
  window.addEventListener('beforeunload', function (event) {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  }, false);
  var exit = document.querySelector('nav a[href="/"]');
  if (exit) { exit.onclick = function (event) {
    if (dirty && !window.confirm('Discard your unsaved layout changes?')) { event.preventDefault(); }
    else { dirty = false; }
  }; }
  var themes = root.querySelectorAll('[data-theme-choice]');
  for (var i = 0; i < themes.length; i += 1) { themes[i].onclick = changeTheme; }
  setupActions(); draw(); load(); loadWeather(); setupTimezones();
}());
