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
    with client.open(Request(root + path, data=urlencode(fields).encode()), timeout=5) as reply:
        return reply.read().decode()


def token(html):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html)[1]


page = post("/login", password=password)
assert password not in page and "smoke-token" not in page
if mode == "demo":
    assert "Demo" in get("/")
else:
    entity = "light.fake_kitchen"
    if mode != "persisted":
        results = get("/settings?q=kitchen")
        assert "Fake kitchen light" in results and entity in results
        assert "Panel updated." in post("/settings/add", csrf=token(results), id=entity, label="Kitchen panel")
        page = get("/")
        assert "Command sent" in post("/control", csrf=token(page), id=entity, action="turn_on")
    else:
        assert "Kitchen panel" in get("/settings")
    dashboard = get("/")
    assert "Kitchen panel" in dashboard and 'value="turn_off"' in dashboard
if mode == "haos":
    with open("/proc/1/status") as status:
        assert re.search(r"^Uid:\s+10001\s", status.read(), re.MULTILINE)
assert password not in get("/")
print("Verified", mode)
