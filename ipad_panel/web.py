import hmac
import re
from datetime import datetime, timezone
from html import escape
from http.client import HTTPException
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from ipaddress import ip_address
from pathlib import Path
from string import Template
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from auth import Sessions
from selection import MAX_ENTITIES

TEMPLATE = Template(Path(__file__).with_name("panel.html").read_text(encoding="utf-8"))
UPSTREAM_ERRORS = (OSError, ValueError, HTTPException)
RESULTS = {
    "saved": "Panel updated.", "sent": "Command sent to Home Assistant.",
    "unavailable": "Home Assistant is unavailable or denied the request.",
}


def page(title, content, refresh=None, navigation=""):
    refresh_tag = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return TEMPLATE.substitute(title=escape(title), content=content, refresh=refresh_tag, navigation=navigation)


def fields(csrf, entity_id=None):
    result = f'<input type="hidden" name="csrf" value="{escape(csrf)}">'
    if entity_id is not None:
        result += f'<input type="hidden" name="id" value="{escape(entity_id)}">'
    return result


def navigation(csrf, settings=False):
    path, label = ("/", "Dashboard") if settings else ("/settings", "Settings")
    return (f'<nav><a href="{path}">{label}</a><form method="post" action="/logout">'
            f'{fields(csrf)}<button type="submit">Sign out</button></form></nav>')


def render(settings, snapshot, now, entities, csrf="", notice=""):
    values = {entity.id: value for entity, value in zip(snapshot.entities, snapshot.values)}
    cards = []
    for entity in entities:
        value, unit = values.get(entity.id, ("—", ""))
        buttons = ""
        if csrf and not settings.demo and entity.id.partition(".")[0] in {"light", "switch"}:
            buttons = (f'<form method="post" action="/control">{fields(csrf, entity.id)}'
                       f'<button type="submit" name="action" value="turn_on" aria-label="Turn on {escape(entity.label)}">On</button> '
                       f'<button type="submit" name="action" value="turn_off" aria-label="Turn off {escape(entity.label)}">Off</button></form>')
        cards.append(f'<li><h2>{escape(entity.label)}</h2><p>{escape(value)} <span>{escape(unit)}</span></p>{buttons}</li>')
    updated = snapshot.updated_at
    age = (now - updated).total_seconds() if updated else 0
    stale = snapshot.stale or age > settings.refresh_seconds * 2 + 5
    if stale:
        status = "Stale data" if updated else "Home Assistant unavailable"
    elif not updated:
        status = "Waiting for data"
    else:
        status = "Demo" if settings.demo else "Live"
    local_time = now.astimezone(settings.zone).strftime("%H:%M")
    last_update = updated.astimezone(settings.zone).strftime("%Y-%m-%d %H:%M:%S") if updated else "—"
    rendered = (f'<p class="clock">{local_time}</p><h1>{escape(settings.title)}</h1>'
                f'<p class="status{" warn" if stale else ""}">{status} &middot; Last update: {last_update}</p>')
    if notice:
        rendered += f'<p role="status" class="notice">{escape(notice)} <a href="/">Back to dashboard</a></p>'
    if cards:
        rendered += '<ul class="tiles">' + "".join(cards) + '</ul>'
    else:
        rendered += '<p>No devices yet. <a href="/settings">Open settings to add a device</a>.</p>'
    # Refresh the clean dashboard path, not the URL with a previous command notice.
    refresh = f"{settings.refresh_seconds};url=/" if notice else settings.refresh_seconds
    return page(settings.title, rendered, refresh, navigation(csrf) if csrf else "")


def settings_page(panel, csrf, query, notice):
    selected = panel.selection.entities
    body = '<h1>Panel settings</h1>'
    if notice:
        body += f'<p role="status" class="notice">{escape(notice)}</p>'
    if panel.settings.demo:
        body += '<p>Demo mode is active. Turn it off in the installation settings to browse and control your devices.</p>'
        return page("Panel settings", body, navigation=navigation(csrf, True))
    body += '<h2>On this panel</h2>'
    if not selected:
        body += '<p>No devices added yet.</p>'
    for entity in selected:
        title, id_ = escape(entity.label), escape(entity.id)
        body += (f'<div class="entry"><code>{id_}</code><form method="post" action="/settings/rename">'
                 f'{fields(csrf, entity.id)}<label>Label <input name="label" maxlength="120" required value="{title}"></label> '
                 f'<button type="submit">Save name</button></form><form method="post" action="/settings/remove">'
                 f'{fields(csrf, entity.id)}<button type="submit" aria-label="Remove {title}">Remove</button></form></div>')
    body += ('<h2>Add a device</h2><form method="get" action="/settings">'
             f'<label>Search by name or entity ID <input name="q" maxlength="100" value="{escape(query or "")}"></label> '
             '<button type="submit">Search</button></form>')
    if query is None:
        body += '<p>Enter a search, or select Search with an empty box to browse the first 50 devices.</p>'
    elif len(selected) >= MAX_ENTITIES:
        body += f'<p>The panel holds up to {MAX_ENTITIES} devices. Remove one before adding another.</p>'
    else:
        try:
            catalogue = panel.catalogue()
        except UPSTREAM_ERRORS as error:
            if isinstance(error, HTTPError):
                error.close()
            body += f'<p class="notice">{RESULTS["unavailable"]}</p>'
        else:
            needle = query.casefold()
            chosen = {entity.id for entity in selected}
            results = sorted(((id_, name) for id_, name in catalogue.items() if id_ not in chosen and
                              (needle in id_.casefold() or needle in name.casefold())), key=lambda item: item[1].casefold())
            if not results:
                body += '<p>No matching devices left to add.</p>'
            if len(results) > 50:
                body += '<p>Showing the first 50 matches. Narrow the search to find others.</p>'
            for id_, name in results[:50]:
                body += (f'<div class="entry"><strong>{escape(name)}</strong> <code>{escape(id_)}</code>'
                         f'<form method="post" action="/settings/add">{fields(csrf, id_)}'
                         f'<label>Label <input name="label" maxlength="120" value="{escape(name)}"></label> '
                         '<button type="submit">Add</button></form></div>')
    return page("Panel settings", body, navigation=navigation(csrf, True))


def sign_in(message=""):
    error = f'<p role="alert" class="notice">{escape(message)}</p>' if message else ""
    return page("Sign in", '<h1>Sign in</h1>' + error + '<form method="post" action="/login">'
                '<label>Panel password <input type="password" name="password" maxlength="256" required></label> '
                '<button type="submit">Sign in</button></form>')


def valid_host(header, names):
    match = re.fullmatch(r"(\[[0-9a-fA-F:.]+\]|[a-zA-Z0-9][a-zA-Z0-9.-]*)(?::[0-9]{1,5})?", header)
    if not match:
        return False
    host = match[1].lower().rstrip(".")
    try:
        ip_address(host.strip("[]"))
    except ValueError:
        return host in names
    return True


def handler(panel):
    auth = Sessions(panel.settings.password, panel.settings.secure_cookie)

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def respond(self, body, code=200, kind="text/html", **headers):
            body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in headers.items():
                self.send_header(key.replace("_", "-"), value)
            self.end_headers()
            self.wfile.write(body)

        def redirect(self, path, **headers):
            self.respond("", 303, Location=path, **headers)

        def check_host(self):
            hosts = self.headers.get_all("Host", [])
            if len(hosts) == 1 and valid_host(hosts[0], panel.settings.allowed_hosts):
                return True
            self.respond("Unrecognized Host; check allowed_hosts", 400, "text/plain")
            return False

        def session(self):
            try:
                cookie = SimpleCookie(self.headers.get("Cookie", "")).get(auth.name)
            except CookieError:
                cookie = None
            token = cookie.value if cookie else ""
            return token, auth.verify(token)

        def route(self):
            try:
                target = urlsplit(self.path)
                if target.netloc or target.scheme:
                    raise ValueError
                return target
            except ValueError:
                self.respond("Invalid URL", 400, "text/plain")
                return None

        def do_GET(self):
            if not self.check_host() or (target := self.route()) is None:
                return
            if target.path == "/healthz":
                self.respond("ok\n", kind="text/plain")
                return
            if target.path not in {"/", "/index.html", "/settings"}:
                self.respond("Not found", 404, "text/plain")
                return
            if not auth.password:
                self.respond(page("Set up iPad Panel", '<h1>Set up iPad Panel</h1>'
                                  '<p>Set <strong>panel_password</strong> in the HAOS App configuration, '
                                  'or <strong>PANEL_PASSWORD</strong> in the Compose .env file '
                                  '(12 characters or more). Then restart the App or recreate the container.</p>'))
                return
            _, csrf = self.session()
            if not csrf:
                self.respond(sign_in())
                return
            try:
                query = parse_qs(target.query, keep_blank_values=True, max_num_fields=8)
            except ValueError:
                self.respond("Invalid query", 400, "text/plain")
                return
            notice = RESULTS.get(query.get("notice", [""])[0], "")
            if target.path == "/settings":
                search = query["q"][0].strip()[:100] if "q" in query else None
                self.respond(settings_page(panel, csrf, search, notice))
            else:
                self.respond(render(panel.settings, panel.snapshot, datetime.now(timezone.utc), panel.entities, csrf, notice))

        def do_POST(self):
            if not self.check_host() or (target := self.route()) is None:
                return
            path = target.path
            if path not in {"/login", "/logout", "/settings/add", "/settings/rename", "/settings/remove", "/control"}:
                self.respond("Not found", 404, "text/plain")
                return
            if not auth.password:
                self.respond("Configure the panel password first", 401, "text/plain")
                return
            supplied_origin = self.headers.get("Origin")
            try:
                if supplied_origin:
                    origin = urlsplit(supplied_origin)
                    if origin.scheme not in {"http", "https"} or origin.netloc.lower() != self.headers["Host"].lower():
                        self.respond("Invalid origin", 403, "text/plain")
                        return
                if self.headers.get_content_type() != "application/x-www-form-urlencoded" or self.headers.get("Transfer-Encoding"):
                    raise ValueError
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError
                data = parse_qs(raw.decode(), max_num_fields=8, keep_blank_values=True)
                if any(len(values) != 1 for values in data.values()):
                    raise ValueError
                data = {key: values[0] for key, values in data.items()}
            except (OSError, ValueError):
                self.respond("Invalid form", 400, "text/plain")
                return
            if path == "/login":
                token, status = auth.login(data.get("password", ""), self.client_address[0])
                if token:
                    old, _ = self.session()
                    auth.revoke(old)
                    self.redirect("/", Set_Cookie=auth.cookie(token))
                elif status == 429:
                    self.respond(sign_in("Too many attempts. Try again in a minute."), status, Retry_After="60")
                else:
                    self.respond(sign_in("Wrong password."), status)
                return
            token, csrf = self.session()
            if not csrf:
                self.respond(sign_in("Sign in again to continue."), 401)
                return
            if not hmac.compare_digest(csrf.encode(), data.get("csrf", "").encode()):
                self.respond("Invalid form token", 403, "text/plain")
                return
            if path == "/logout":
                auth.revoke(token)
                self.redirect("/", Set_Cookie=auth.cookie(""))
                return
            if panel.settings.demo:
                self.respond("Demo mode cannot change real devices", 403, "text/plain")
                return
            entity_id, label = data.get("id", ""), data.get("label", "").strip()
            if path == "/control":
                try:
                    sent = panel.control(entity_id, data.get("action", ""))
                except UPSTREAM_ERRORS as error:
                    if isinstance(error, HTTPError):
                        error.close()
                    self.redirect("/?notice=unavailable")
                else:
                    if sent:
                        self.redirect("/?notice=sent")
                    else:
                        self.respond("This control is not allowed", 403, "text/plain")
                return
            if path == "/settings/add":
                try:
                    catalogue = panel.catalogue()
                except UPSTREAM_ERRORS as error:
                    if isinstance(error, HTTPError):
                        error.close()
                    self.redirect("/settings?notice=unavailable")
                    return
                if entity_id not in catalogue:
                    self.respond("Device not found in Home Assistant", 404, "text/plain")
                    return
            try:
                if path == "/settings/add":
                    panel.selection.add(entity_id, label or catalogue[entity_id])
                elif path == "/settings/rename":
                    panel.selection.rename(entity_id, label)
                else:
                    panel.selection.remove(entity_id)
            except ValueError as error:
                self.respond(page("Settings error", f'<h1>{escape(str(error))}</h1><a href="/settings">Back to settings</a>'), 400)
                return
            except OSError:
                self.respond("Could not save dashboard settings", 500, "text/plain")
                return
            panel.changed.set()
            self.redirect("/settings?notice=saved")

        def log_message(self, format, *args):
            pass

    return Handler
