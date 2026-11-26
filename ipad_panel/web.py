import hmac
import json
import re
from datetime import datetime, timezone
from html import escape
from http.client import HTTPException
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from ipaddress import ip_address
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from auth import MIN_PASSWORD, LoginForms, Sessions
from selection import MAX_ENTITIES
from views import editor_page, fields, navigation, page, render

ASSETS = {f"/{name}": Path(__file__).with_name(name) for name in ("dashboard.js", "editor.js", "style.css")}
UPSTREAM_ERRORS = (OSError, ValueError, HTTPException)
RESULTS = {
    "saved": "Panel updated.", "sent": "Command sent to Home Assistant. State confirmed.",
    "failed": "The device did not confirm the command. Check its state and try again.",
    "unavailable": "Home Assistant is unavailable or denied the request.",
}


def settings_page(panel, csrf, query, notice):
    selected = panel.selection.entities
    body = '<h1>Panel settings</h1>'
    if notice:
        body += f'<p role="status" class="notice">{escape(notice)}</p>'
    if panel.settings.demo:
        body += '<p>Demo mode is active. Turn it off in the installation settings to browse and control your devices.</p>'
        return page("Panel settings", body, navigation=navigation(csrf, True), theme=panel.selection.theme)
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
    return page("Panel settings", body, navigation=navigation(csrf, True), theme=panel.selection.theme)


def sign_in(csrf, message=""):
    error = f'<p role="alert" class="notice">{escape(message)}</p>' if message else ""
    return page("Sign in", '<h1>Sign in</h1>' + error + '<form method="post" action="/login">' + fields(csrf) +
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
        return not names or host in names
    return True


def handler(panel):
    auth = Sessions(panel.settings.password, panel.settings.secure_cookie)
    login_forms = LoginForms(None, panel.settings.secure_cookie)

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def respond(self, body, code=200, kind="text/html", **headers):
            body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in headers.items():
                self.send_header(key.replace("_", "-"), value)
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, body, code=200):
            self.respond(json.dumps(body), code, "application/json")

        def redirect(self, path, **headers):
            self.respond("", 303, Location=path, **headers)

        def check_host(self):
            hosts = self.headers.get_all("Host", [])
            if len(hosts) == 1 and valid_host(hosts[0], panel.settings.allowed_hosts):
                return True
            self.respond("Unrecognized Host; check allowed_hosts", 400, "text/plain")
            return False

        def cookie_token(self, name):
            try:
                cookie = SimpleCookie(self.headers.get("Cookie", "")).get(name)
            except CookieError:
                cookie = None
            return cookie.value if cookie else ""

        def session(self):
            token = self.cookie_token(auth.name)
            return token, auth.verify(token)

        def show_sign_in(self, message="", code=200, **headers):
            token = self.cookie_token(login_forms.name)
            proof = login_forms.verify(token)
            if proof is None:
                token = login_forms.issue()
                proof = login_forms.verify(token) or ""
            self.respond(sign_in(proof, message), code, Set_Cookie=login_forms.cookie(token), **headers)

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
            if target.path in ASSETS:
                file = ASSETS[target.path]
                kind = "text/css" if file.suffix == ".css" else "application/javascript"
                self.respond(file.read_text(encoding="utf-8"), kind=kind)
                return
            if target.path not in {"/", "/index.html", "/settings", "/edit", "/data", "/catalogue"}:
                self.respond("Not found", 404, "text/plain")
                return
            if not auth.password:
                self.respond(page("Set up iPad Panel", '<h1>Set up iPad Panel</h1>'
                                  '<p>Set <strong>panel_password</strong> in the HAOS App configuration, '
                                  'or <strong>PANEL_PASSWORD</strong> in the Compose .env file '
                                  f'({MIN_PASSWORD} characters or more). Then restart the App or recreate the container.</p>'))
                return
            _, csrf = self.session()
            if not csrf:
                if target.path in {"/data", "/catalogue"}:
                    self.json_response({"error": "Sign in again to continue."}, 401)
                else:
                    self.show_sign_in()
                return
            try:
                query = parse_qs(target.query, keep_blank_values=True, max_num_fields=8)
            except ValueError:
                self.respond("Invalid query", 400, "text/plain")
                return
            notice = RESULTS.get(query.get("notice", [""])[0], "")
            if target.path == "/data":
                self.json_response(panel.dashboard(datetime.now(timezone.utc)))
            elif target.path == "/catalogue":
                self.send_catalogue(query)
            elif target.path == "/edit":
                self.respond(editor_page(panel, csrf))
            elif target.path == "/settings":
                search = query["q"][0].strip()[:100] if "q" in query else None
                self.respond(settings_page(panel, csrf, search, notice))
            else:
                layout = panel.selection.layout
                entities = panel.entities if panel.settings.demo else layout.entities
                self.respond(render(panel.settings, panel.snapshot, datetime.now(timezone.utc), entities, csrf, notice,
                                    layout.theme, panel.weather_source))

        def send_catalogue(self, query):
            try:
                catalogue = panel.catalogue()
                domain = query.get("type", ["all"])[0]
                needle = query.get("q", [""])[0].strip()[:100].casefold()
                offset = min(100000, max(0, int(query.get("offset", ["0"])[0])))
            except UPSTREAM_ERRORS as error:
                if isinstance(error, HTTPError):
                    error.close()
                self.json_response({"error": "Could not load devices from Home Assistant."}, 502)
                return
            types = {"sensor", "binary_sensor"} if domain == "sensor" else {domain}
            results = sorted(((id_, label) for id_, label in catalogue.items()
                              if (domain == "all" or id_.partition(".")[0] in types)
                              and needle in f"{label} {id_}".casefold()), key=lambda item: (item[1].casefold(), item[0]))
            total = len(results)
            self.json_response({"items": [{"id": i, "label": name} for i, name in results[offset:offset + 30]],
                                "offset": offset, "total": total})

        def do_POST(self):
            if not self.check_host() or (target := self.route()) is None:
                return
            path = target.path
            if path not in {"/login", "/logout", "/settings/add", "/settings/rename", "/settings/remove", "/control",
                            "/layout", "/theme"}:
                self.respond("Not found", 404, "text/plain")
                return
            if not auth.password:
                self.respond("Configure the panel password first", 401, "text/plain")
                return
            supplied_origin = self.headers.get("Origin")
            try:
                # Old browsers may omit Origin or send an opaque Origin. Form tokens protect both cases.
                if supplied_origin and supplied_origin != "null":
                    origin = urlsplit(supplied_origin)
                    if origin.scheme not in {"http", "https"} or origin.netloc.lower() != self.headers["Host"].lower():
                        self.respond("Invalid origin", 403, "text/plain")
                        return
                if self.headers.get_content_type() != "application/x-www-form-urlencoded" or self.headers.get("Transfer-Encoding"):
                    raise ValueError
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= (65536 if path == "/layout" else 4096):
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
                if login_forms.verify(self.cookie_token(login_forms.name), proof=data.get("csrf", "")) is None:
                    self.show_sign_in("The sign-in form expired. Please try again.", 403)
                    return
                token, status = auth.login(data.get("password", ""), self.client_address[0])
                if token:
                    old, _ = self.session()
                    auth.revoke(old)
                    self.redirect("/", Set_Cookie=auth.cookie(token))
                elif status == 429:
                    self.show_sign_in("Too many attempts. Try again in a minute.", status, Retry_After="60")
                else:
                    self.show_sign_in("Wrong password.", status)
                return
            token, csrf = self.session()
            if not csrf:
                self.show_sign_in("Sign in again to continue.", 401)
                return
            if not hmac.compare_digest(csrf.encode(), data.get("csrf", "").encode()):
                self.respond("Invalid form token", 403, "text/plain")
                return
            if path == "/logout":
                auth.revoke(token)
                self.redirect("/", Set_Cookie=auth.cookie(""))
                return
            if path == "/theme":
                try:
                    panel.selection.set_theme(data.get("theme"))
                except (ValueError, OSError) as error:
                    self.json_response({"error": str(error) if isinstance(error, ValueError) else "Could not save theme."}, 400)
                else:
                    self.json_response({"theme": panel.selection.theme})
                return
            entity_id, label = data.get("id", ""), data.get("label", "").strip()
            if path == "/control":
                ajax = self.headers.get("Accept") == "application/json"
                try:
                    sent = panel.confirm_control(entity_id, data.get("action", ""))
                except UPSTREAM_ERRORS as error:
                    if isinstance(error, HTTPError):
                        error.close()
                    if ajax:
                        self.json_response({"error": RESULTS["failed"]}, 502)
                    else:
                        self.redirect("/?notice=failed")
                else:
                    if not sent:
                        self.json_response({"error": "This widget cannot be controlled right now."}, 403)
                    elif ajax:
                        self.json_response(panel.dashboard(datetime.now(timezone.utc)))
                    else:
                        self.redirect("/?notice=sent")
                return
            if path == "/layout":
                self.save_layout(data)
                return
            if panel.settings.demo:
                self.respond("Demo mode cannot change real devices", 403, "text/plain")
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

        def save_layout(self, data):
            from selection import parse_entities, preferences
            try:
                widgets = json.loads(data.get("widgets", ""))
                weather = data.get("weather", "")
                requested = {entity.id for entity in parse_entities(widgets)}
                preferences(weather, panel.selection.theme)
                current = panel.selection.layout
                known = {entity.id for entity in (panel.entities if panel.settings.demo else current.entities)}
                if current.weather:
                    known.add(current.weather)
                if weather:
                    requested.add(weather)
                if requested - known:
                    available = panel.catalogue()
                    if (requested - known) - set(available):
                        raise ValueError("A selected device is no longer available in Home Assistant.")
                panel.selection.save(widgets, weather, demo=panel.settings.demo)
            except ValueError as error:
                self.json_response({"error": "Invalid layout data." if isinstance(error, json.JSONDecodeError) else str(error)}, 400)
                return
            except UPSTREAM_ERRORS as error:
                if isinstance(error, HTTPError):
                    error.close()
                self.json_response({"error": "Could not save the layout. Try again."}, 502)
                return
            panel.changed.set()
            self.json_response({"saved": True})

        def log_message(self, format, *args):
            pass

    return Handler
