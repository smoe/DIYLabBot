"""Local operator/observer credentials and short-lived scoped access tokens.

Passwords are PBKDF2 hashes; access tokens stay in memory and expire against
monotonic wall time, independently of an injected simulator test clock.
"""
import hashlib
import hmac
import secrets
import threading
import time


ITERATIONS = 600_000
TOKEN_LIFETIME_S = 900


def credential(username, password, role):
    if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or len(password) < 12:
        raise ValueError('A named user and a password of at least 12 characters are required')
    if role not in {'operator', 'observer'}:
        raise ValueError('Role must be operator or observer')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return {'username': username, 'role': role, 'salt': salt, 'iterations': ITERATIONS, 'password_sha256': digest}


class Access:
    def __init__(self, users, server_uuid, features, clock=time.monotonic):
        self.users = {u['username']: u for u in users}
        if not self.users or len(self.users) != len(users):
            raise ValueError('Unique configured users required; no default credentials exist')
        for user in users:
            if user['role'] not in {'operator', 'observer'} or user['iterations'] < ITERATIONS:
                raise ValueError('Unsupported role or weak password derivation')
        self.server_uuid = server_uuid
        self.features = set(features)
        self.clock = clock
        self.tokens = {}
        self.failures = {}
        self._mutex = threading.RLock()

    def login(self, username, password, requested_server, requested_features):
        # Bound repeated password attempts without retaining submitted secrets.
        with self._mutex:
            last, failures = self.failures.get(username, (0., 0))
        if failures >= 5 and self.clock() - last < 30:
            raise PermissionError('Authentication failed')
        user = self.users.get(username)
        salt = bytes.fromhex(user['salt']) if user else bytes(16)
        derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt,
                                     user['iterations'] if user else ITERATIONS).hex()
        granted = set(requested_features) if requested_features else self.features
        if (user is None or not hmac.compare_digest(derived, user['password_sha256'])
                or requested_server != self.server_uuid or not granted <= self.features):
            with self._mutex:
                current = self.failures.get(username, (0., 0))[1]
                self.failures[username] = (self.clock(), current + 1)
            raise PermissionError('Authentication failed')
        token = secrets.token_urlsafe(32)
        with self._mutex:
            self.failures.pop(username, None)
            self.tokens[hashlib.sha256(token.encode()).hexdigest()] = {
                'username': username, 'role': user['role'], 'features': granted,
                'deadline': self.clock() + TOKEN_LIFETIME_S}
        return token, TOKEN_LIFETIME_S

    def authorize(self, token, handler=None):
        with self._mutex:
            return self._authorize(token, handler)

    def _authorize(self, token, handler=None):
        digest = hashlib.sha256(token.encode()).hexdigest()
        entry = self.tokens.get(digest)
        if entry is None or self.clock() >= entry['deadline']:
            self.tokens.pop(digest, None)
            raise PermissionError('Invalid access token')
        if handler is not None:
            feature = str(handler.feature.fully_qualified_identifier)
            if feature not in entry['features']:
                raise PermissionError('Token is not valid for this feature')
            readonly = handler.identifier in {'GetStatus', 'GetRotationFeedback'} or 'Property' in type(handler).__name__
            if entry['role'] == 'observer' and not readonly:
                raise PermissionError('Token is not valid for this operation')
        entry['deadline'] = self.clock() + TOKEN_LIFETIME_S
        return entry['username']

    def logout(self, token):
        with self._mutex:
            self._authorize(token)
            self.tokens.pop(hashlib.sha256(token.encode()).hexdigest())
