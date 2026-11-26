// Browser-level interaction check. Run against a password-protected demo server.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const dir = await mkdtemp(join(tmpdir(), 'ipad-browser-'));
const chrome = spawn(process.env.CHROME || 'google-chrome', [
  '--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0',
  '--user-data-dir=' + dir, '--window-size=1024,768', 'about:blank'
], { stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
try {
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Chromium debugger not ready')), 10000);
    chrome.once('error', error => { clearTimeout(timer); reject(error); });
    chrome.stderr.on('data', chunk => {
      const match = chunk.toString().match(/DevTools listening on ws:\/\/[^:]+:(\d+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  const [tab] = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let serial = 0;
  const awaiting = new Map();
  socket.onmessage = ({ data }) => {
    const reply = JSON.parse(data), callback = awaiting.get(reply.id);
    if (callback) { awaiting.delete(reply.id); callback(reply); }
  };
  function command(method, params = {}) {
    const id = ++serial;
    return new Promise((resolve, reject) => {
      awaiting.set(id, reply => reply.error ? reject(Error(reply.error.message)) : resolve(reply.result));
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async function js(expression) {
    const reply = await command('Runtime.evaluate', { expression, returnByValue: true });
    if (reply.exceptionDetails) { throw Error(reply.exceptionDetails.exception.description); }
    return reply.result.value;
  }
  const wait = async expression => {
    for (let i = 0; i < 50; i++) {
      if (await js(expression)) { return; }
      await sleep(100);
    }
    throw Error(expression + ' was not satisfied');
  };
  await command('Page.navigate', { url: process.env.PANEL_URL || 'http://127.0.0.1:8090/' });
  await wait('document.querySelector("[name=password]")');
  await js(`document.querySelector('[name=password]').value = ${JSON.stringify(process.env.PANEL_PASSWORD)}; document.querySelector('form').submit()`);
  await wait('document.querySelector("#dashboard button[aria-pressed=true]")');
  assert.equal(await js('document.querySelector("#weather-value").textContent.trim()'), '4 °C');
  assert.notEqual(await js('document.querySelector("#last-update").textContent'), '—');
  await js('document.querySelector("#dashboard button[aria-pressed=true]").click()');
  await wait('document.querySelector(".feedback").textContent === "State confirmed"');
  assert.equal(await js('document.querySelector("button.control").getAttribute("aria-pressed")'), 'false');
  const clock = await js('document.getElementById("clock").textContent');
  await js('var realNow = Date.now; Date.now = function () { return realNow() + 61000; }');
  await wait(`document.getElementById('clock').textContent !== ${JSON.stringify(clock)}`);
  await js('Date.now = realNow');
  await js(`document.querySelector('a[href="/edit"]').click()`);
  await wait('document.querySelector("#board [data-widget]")');
  await wait('document.getElementById("zone-choice").options.length > 0');
  await js(`document.getElementById('timezone-settings').open = true;
    var search = document.getElementById('zone-query'); search.value = 'Moscow'; search.dispatchEvent(new Event('input'));
    if (!document.getElementById('save-zone').disabled) { throw Error('First search match must not be selected'); }
    var choice = document.getElementById('zone-choice'); choice.value = 'Europe/Moscow'; choice.dispatchEvent(new Event('change'));
    document.getElementById('save-zone').click()`);
  await wait('document.getElementById("current-zone").textContent === "Current: Europe/Moscow"');
  await js('document.querySelector("[data-theme-choice=light]").click()');
  await wait('document.documentElement.getAttribute("data-theme") === "light"');
  await js(`(function () {
    var sensor = '[data-widget="sensor.demo_temperature"]';
    document.querySelector(sensor).click();
    var rect = document.querySelector('[data-cell="11"]').getBoundingClientRect();
    var handle = document.querySelector('[data-grip="light.demo_living"]');
    var touch = { clientX: rect.left + 5, clientY: rect.top + 5 };
    handle.dispatchEvent(Object.assign(new Event('touchstart', { bubbles:true, cancelable:true }), { touches:[touch] }));
    handle.dispatchEvent(Object.assign(new Event('touchend', { bubbles:true, cancelable:true }), { changedTouches:[touch] }));
    if (document.getElementById('selected-id').textContent !== 'sensor.demo_temperature') { throw Error('Invalid drop changed selection'); }
    var free = document.querySelector('[data-cell="8"]'); free.focus(); free.click();
    if (document.activeElement.getAttribute('data-widget') !== 'sensor.demo_temperature') { throw Error('Move lost focus'); }
    document.querySelector('[data-width="2"][data-height="1"]').click();
    window.confirm = function () { return false; };
    document.querySelector('nav a[href="/"]').click();
  }())`);
  assert.equal(await js('location.pathname'), '/edit');
  assert.match(await js(`document.querySelector('[data-widget="sensor.demo_temperature"]').textContent`), /2 × 1/);
  await js(`(function () {
    var handle = document.querySelector('[data-grip="sensor.demo_humidity"]');
    var cell = document.querySelector('[data-cell="10"]').getBoundingClientRect();
    var touch = { clientX: cell.left + 10, clientY: cell.top + 10 };
    handle.dispatchEvent(Object.assign(new Event('touchstart', { bubbles:true, cancelable:true }), { touches:[touch] }));
    handle.dispatchEvent(Object.assign(new Event('touchmove', { bubbles:true, cancelable:true }), { touches:[touch] }));
    handle.dispatchEvent(Object.assign(new Event('touchend', { bubbles:true, cancelable:true }), { changedTouches:[touch] }));
  }())`);
  await wait(`document.querySelectorAll('.board-row')[2].querySelector('[data-widget="sensor.demo_humidity"]')`);
  await js(`document.querySelector('[data-widget="sensor.demo_temperature"]').click();
    document.querySelector('[data-width="2"][data-height="2"]').click()`);
  assert.match(await js(`document.querySelector('[data-widget="sensor.demo_temperature"]').textContent`), /2 × 2/);
  assert.equal(await js(`document.querySelector('[data-cell="12"]') === null`), true);
  await js(`document.querySelector('[data-widget="binary_sensor.demo_door"]').click();
    document.querySelector('[data-width="1"][data-height="2"]').click()`);
  assert.match(await js(`document.getElementById('edit-note').textContent`), /occupied/);
  assert.match(await js(`document.querySelector('[data-widget="binary_sensor.demo_door"]').textContent`), /1 × 1/);
  await js(`document.querySelector('[data-cell="11"]').click();
    document.querySelector('[data-width="1"][data-height="2"]').click()`);
  assert.match(await js(`document.querySelector('[data-widget="binary_sensor.demo_door"]').textContent`), /1 × 2/);
  assert.equal(await js(`document.querySelector('[data-cell="15"]') === null`), true);
  await js('document.querySelector("#device-search input").value="outdoor"; document.querySelector("#device-search button").click()');
  await wait('document.querySelector("#results button") && /Outdoor temperature/.test(document.querySelector("#results").textContent)');
  await js(`document.querySelector('#results button').click();
    var type = document.querySelector('#device-search select'); type.value = 'weather'; type.dispatchEvent(new Event('change'));`);
  assert.equal(await js('document.getElementById("add-widget").disabled'), true);
  await js(`var type = document.querySelector('#device-search select'); type.value = 'all'; type.dispatchEvent(new Event('change'));`);
  await wait('document.querySelector("#results button") && /Outdoor temperature/.test(document.querySelector("#results").textContent)');
  await js('document.querySelector("#results button").click(); document.getElementById("add-widget").click()');
  await js(`var type = document.querySelector('#device-search select'); type.value = 'climate';
    document.querySelector('#device-search input').value = ''; document.querySelector('#device-search button').click()`);
  await wait('document.querySelector("#results button") && /Hall thermostat/.test(document.querySelector("#results").textContent)');
  await js('document.querySelector("#results button").click(); document.getElementById("add-widget").click()');
  await js('document.getElementById("save-layout").click()');
  await wait(`document.querySelector('#dashboard [data-id="sensor.demo_outside"]')`);
  assert.equal(await js('document.documentElement.getAttribute("data-theme")'), 'light');
  assert.equal(await js('document.getElementById("timezone-label").textContent'), 'Europe/Moscow');
  await wait(`document.querySelector('.climate [data-target="temperature"] button[data-direction="up"]:not(:disabled)')`);
  await js(`document.querySelector('.climate [data-target="temperature"] button[data-direction="up"]').click()`);
  await wait(`document.querySelector('.climate [data-target="temperature"] strong').textContent === '22.5 °C'`);
  const geometry = `JSON.stringify(Array.prototype.map.call(document.querySelectorAll('.widget-grid > .slot'), function(slot) {
    var rect = slot.getBoundingClientRect(); return [rect.left, rect.top, rect.width, rect.height];
  }))`;
  const beforeMode = await js(geometry);
  assert.equal(await js(`(function () {
    var wide = document.querySelector('[data-id="sensor.demo_temperature"]').getBoundingClientRect();
    var normal = document.querySelector('[data-id="sensor.demo_humidity"]').getBoundingClientRect();
    return wide.top === normal.top && wide.height === normal.height * 2 && wide.right <= normal.left;
  }())`), true);
  await js(`document.querySelector('.climate-disclosure summary').click()`);
  await wait(`document.querySelector('.climate-disclosure').open`);
  assert.equal(await js(geometry), beforeMode);
  await js(`document.querySelector('.climate-modes button[value="cool"]').click()`);
  await wait(`document.querySelector('.climate-mode').textContent === 'Cooling'`);
  assert.equal(await js(`document.querySelector('.climate-disclosure').open`), false);
  assert.equal(await js(`document.querySelector('[data-id="sensor.demo_temperature"]').getAttribute('data-size')`), '2x2');
  assert.equal(await js(`document.querySelector('[data-id="binary_sensor.demo_door"]').getAttribute('data-size')`), '1x2');
  for (const [width, height] of [[768, 1024], [375, 667]]) {
    await command('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: true });
    assert.equal(await js('document.documentElement.scrollWidth <= window.innerWidth'), true);
    const space = await js(`(function () {
      var tile = document.querySelector('.climate').getBoundingClientRect();
      var summary = document.querySelector('.climate-disclosure summary').getBoundingClientRect();
      var stepper = document.querySelector('.climate-overview .climate-stepper').getBoundingClientRect();
      return { bottom: tile.bottom - Math.max(summary.bottom, stepper.bottom), right: tile.right - Math.max(summary.right, stepper.right) };
    }())`);
    assert.ok(space.bottom >= 0 && space.right >= 0, 'Climate controls overflow the ' + width + 'px tile: ' + JSON.stringify(space));
  }
  await command('Page.enable');
  await command('Page.addScriptToEvaluateOnNewDocument', { source: `(function () {
    var RealXHR = window.XMLHttpRequest, realTimeout = window.setTimeout;
    window.setTimeout = function (fn, delay) { return realTimeout(fn, Math.min(delay, 650)); };
    window.XMLHttpRequest = function () {
      var native = new RealXHR(), path, method, fake = this;
      this.open = function (verb, url) { method = verb; path = url; native.open(verb, url, true); };
      this.setRequestHeader = function (key, value) { native.setRequestHeader(key, value); };
      this.send = function (body) {
        if (path === '/data' || (path === '/control' && method === 'POST')) {
          realTimeout(function () { fake.status = path === '/data' ? 503 : 502; fake.responseText = '{}'; fake.onload(); }, path === '/data' ? 15 : 1000);
        } else { native.onload = function () { fake.status = native.status; fake.responseText = native.responseText; fake.onload(); }; native.send(body); }
      };
    };
  }());` });
  await command('Page.reload');
  await wait('document.readyState === "complete" && typeof realNow === "undefined" && document.querySelector("#dashboard .control:not(:disabled)")');
  await js('document.querySelector("#dashboard .control:not(:disabled)").click()');
  await wait('document.getElementById("connection").textContent === "Connection lost"');
  await wait('document.querySelector(".feedback.error")');
  assert.equal(await js('Array.prototype.every.call(document.querySelectorAll(".control"), function (button) { return button.disabled; })'), true);
  assert.equal(await js('document.getElementById("clock-sync").textContent'), 'Clock not synchronized');
  assert.equal(await js('Array.prototype.every.call(document.querySelectorAll(".climate button, .climate select"), function (input) { return input.disabled; })'), true);
  console.log('Browser smoke passed: light and climate controls (including outage), clock, weather, themes, grid, focus, draft protection, catalogue and time zone.');
} finally {
  if (socket) { socket.close(); }
  chrome.kill();
  await new Promise(resolve => { if (chrome.exitCode !== null || chrome.signalCode !== null) { resolve(); } else { chrome.once('close', resolve); } });
  await rm(dir, { recursive: true, force: true, maxRetries: 3 });
}
