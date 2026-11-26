import hashlib
import hmac
import os
import re
import secrets
import tempfile
import time
from collections import OrderedDict
from threading import Lock

MIN_PASSWORD = 6


def choose_password(configured, path):
    if configured:
        return configured, False
    if path is not None and path.is_file():
        password = path.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{24}", password):
            raise ValueError("saved generated password is invalid; configure your own password")
        return password, False
    password = secrets.token_hex(12)
    if path is not None:
        fd, temporary = tempfile.mkstemp(prefix=".password-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(password + "\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return password, True


class Sessions:
    max_age = 7 * 24 * 60 * 60
    name = "ipad_panel_session"

    def __init__(self, password, secure=False):
        self.password = self.digest(password) if password else None
        self.secure = secure
        self.tokens = OrderedDict()
        self.attempts = OrderedDict()
        self.lock = Lock()

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).digest()

    def login(self, password, client):
        now = time.monotonic()
        with self.lock:
            count, until = self.attempts.get(client, (0, 0))
            if now >= until:
                count, until = 0, now + 60
            if count >= 5:
                return None, 429
            if self.password is None or not hmac.compare_digest(self.password, self.digest(password)):
                self.attempts[client] = (count + 1, until)
                self.attempts.move_to_end(client)
                if len(self.attempts) > 256:
                    self.attempts.popitem(last=False)
                return None, 401
            self.attempts.pop(client, None)
        return self.issue(), 303

    def issue(self, now=None):
        now = time.monotonic() if now is None else now
        token, csrf = secrets.token_hex(32), secrets.token_hex(32)
        with self.lock:
            self.tokens[token] = (now + self.max_age, csrf)
            if len(self.tokens) > 128:
                self.tokens.popitem(last=False)
        return token

    def verify(self, token, now=None, proof=None):
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            return None
        now = time.monotonic() if now is None else now
        with self.lock:
            session = self.tokens.get(token)
            if not session or now >= session[0]:
                self.tokens.pop(token, None)
                return None
            if proof is not None:
                if not hmac.compare_digest(session[1].encode(), proof.encode()):
                    return None
                self.tokens.pop(token)
            return session[1]

    def revoke(self, token):
        with self.lock:
            self.tokens.pop(token, None)

    def cookie(self, token):
        age = self.max_age if token else 0
        secure = "; Secure" if self.secure else ""
        return f"{self.name}={token}; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax{secure}"


class LoginForms(Sessions):
    max_age = 10 * 60
    name = "ipad_panel_login"
