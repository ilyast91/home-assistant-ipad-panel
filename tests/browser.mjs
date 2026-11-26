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
  await js(`document.querySelector('a[href="/edit"]').click()`);
  await wait('document.querySelector("#board [data-widget]")');
  await wait('document.getElementById("zone-choice").options.length > 0');
  await js(`document.getElementById('timezone-settings').open = true;
    var search = document.getElementById('zone-query'); search.value = 'Moscow'; search.dispatchEvent(new Event('input'));
    document.getElementById('save-zone').click()`);
  await wait('document.getElementById("current-zone").textContent === "Current: Europe/Moscow"');
  await js('document.querySelector("[data-theme-choice=light]").click()');
  await wait('document.documentElement.getAttribute("data-theme") === "light"');
  await js(`document.querySelector('[data-widget="sensor.demo_temperature"]').click(); document.querySelector('[data-cell="8"]').click(); document.querySelector('[data-width="2"]').click()`);
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
  await js('document.querySelector("#device-search input").value="outdoor"; document.querySelector("#device-search button").click()');
  await wait('document.querySelector("#results button") && /Outdoor temperature/.test(document.querySelector("#results").textContent)');
  await js('document.querySelector("#results button").click(); document.getElementById("add-widget").click()');
  await js('document.getElementById("save-layout").click()');
  await wait(`document.querySelector('#dashboard [data-id="sensor.demo_outside"]')`);
  assert.equal(await js('document.documentElement.getAttribute("data-theme")'), 'light');
  assert.equal(await js('document.getElementById("timezone-label").textContent'), 'Europe/Moscow');
  assert.equal(await js(`document.querySelector('[data-id="sensor.demo_temperature"]').classList.contains('w2')`), true);
  await command('Emulation.setDeviceMetricsOverride', { width: 375, height: 667, deviceScaleFactor: 1, mobile: true });
  assert.equal(await js('document.documentElement.scrollWidth <= window.innerWidth'), true);
  console.log('Browser smoke passed: full-tile control, weather, timestamps, light theme, touch move, resize, catalogue, save, mobile width.');
} finally {
  if (socket) { socket.close(); }
  chrome.kill();
  await new Promise(resolve => { if (chrome.exitCode !== null || chrome.signalCode !== null) { resolve(); } else { chrome.once('close', resolve); } });
  await rm(dir, { recursive: true, force: true, maxRetries: 3 });
}
