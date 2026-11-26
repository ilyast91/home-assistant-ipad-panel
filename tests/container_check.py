import re
import sys
import time
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

root = "http://127.0.0.1:8090"
mode, password = sys.argv[1:]
for _ in range(30):
    try:
        with urlopen(root, timeout=2) as reply:
            public = reply.read().decode()
            # Direct HTTP must not receive Secure cookies when HTTPS has not been enabled.
            cookie = reply.headers["Set-Cookie"]
            assert cookie.startswith("ipad_panel_login=")
            assert not any(flag.strip().lower() == "secure" for flag in cookie.split(";")[1:])
    except OSError:
        time.sleep(1)
    else:
        break
else:
    raise RuntimeError("panel did not start")
assert "Living room" not in public and "Fake kitchen light" not in public
assert "Sign in" in public

client = build_opener(HTTPCookieProcessor(CookieJar()))


def get(path):
    with client.open(root + path, timeout=5) as reply:
        return reply.read().decode()


def post(path, **fields):
    with client.open(Request(root + path, headers={"Origin": "null"}, data=urlencode(fields).encode()), timeout=5) as reply:
        return reply.read().decode()


def token(html):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html)[1]


page = post("/login", password=password, csrf=token(get("/")))
assert "Sign out" in page
assert password not in page and "smoke-token" not in page
if mode in {"demo", "generated"}:
    assert "Demo" in get("/")
else:
    for _ in range(30):
        initial = get("/")
        if "Europe/Moscow (Home Assistant)" in initial and 'id="weather-value">17 °C</strong>' in initial:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("Automatic HA weather or time zone was not discovered")
    entity = "light.fake_kitchen"
    if mode != "persisted":
        results = get("/settings?q=kitchen")
        assert "Fake kitchen light" in results and entity in results
        assert "Panel updated." in post("/settings/add", csrf=token(results), id=entity, label="Kitchen panel")
        for _ in range(30):
            page = get("/")
            action = re.search(r'value="(turn_on|turn_off)" aria-label="Kitchen panel power" aria-pressed="(?:false|true)"\s+data-available="yes">', page)
            if action:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("initial state was not polled")
        assert "Command sent" in post("/control", csrf=token(page), id=entity, action=action[1])
    else:
        assert "Kitchen panel" in get("/settings")
    dashboard = get("/")
    assert "Kitchen panel" in dashboard and 'class="control-form"' in dashboard
if mode == "haos":
    with open("/proc/1/status") as status:
        assert re.search(r"^Uid:\s+10001\s", status.read(), re.MULTILINE)
assert password not in get("/")
print("Verified", mode)
