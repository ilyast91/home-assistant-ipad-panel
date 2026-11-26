import hashlib
import hmac
import re
import secrets
import time
from collections import OrderedDict
from threading import Lock


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

    def verify(self, token, now=None):
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            return None
        now = time.monotonic() if now is None else now
        with self.lock:
            session = self.tokens.get(token)
            if session and now < session[0]:
                return session[1]
            self.tokens.pop(token, None)
        return None

    def revoke(self, token):
        with self.lock:
            self.tokens.pop(token, None)

    def cookie(self, token):
        age = self.max_age if token else 0
        secure = "; Secure" if self.secure else ""
        return f"{self.name}={token}; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax{secure}"
