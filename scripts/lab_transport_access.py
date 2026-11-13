"""Local T3 account credentials and bounded, short-lived bearer sessions.

These accounts authenticate a software subject. They do not identify a person,
verify a physical handover, or implement an institutional identity provider.
"""
import copy
import hashlib
import hmac
import secrets
import threading
import time

from async_transport_domain import exact, ident, require
from cf01_sila2_auth import ITERATIONS, TOKEN_LIFETIME_S


class AuthError(PermissionError):
    status = 401
    code = 'authentication_failed'


class AuthContext(dict):
    """Detached public identity plus an in-process, nonserialized token handle."""
    def __init__(self, value, access, key):
        super().__init__(value)
        self._access, self._key = access, key


def _subject(value):
    require(isinstance(value, str) and 0 < len(value) <= 160
            and value == value.strip() and all(32 <= ord(c) < 127 for c in value),
            'A named single-line local account is required')
    return value


def _grants(grants):
    require(isinstance(grants, list) and bool(grants), 'Explicit account grants required')
    found = set()
    for grant in grants:
        exact(grant, 'id kind resource_id', 'account grant')
        ident(grant['id']); ident(grant['resource_id'])
        require(grant['kind'] in {'owner', 'observer', 'endpoint', 'agent'}, 'Unsupported account grant kind')
        require(grant['id'] not in found, 'Duplicate account grant identity')
        found.add(grant['id'])
    return copy.deepcopy(grants)


def credential(username, password, principal, grants):
    """Create a private credential record; never write plaintext passwords."""
    _subject(username); ident(principal); normalized = _grants(grants)
    require(isinstance(password, str) and 12 <= len(password) <= 1024,
            'A password between 12 and 1024 characters is required')
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return {'username': username, 'principal': principal, 'grants': normalized,
            'salt': salt, 'iterations': ITERATIONS, 'password_sha256': hashed}


class Access:
    def __init__(self, users, server_uuid, clock=time.monotonic):
        require(isinstance(users, list) and bool(users), 'Named local accounts required; no default credentials')
        self.server_uuid, self.clock = str(server_uuid), clock
        self.users = {}
        for user in users:
            exact(user, 'username principal grants salt iterations password_sha256', 'local account')
            _subject(user['username']); ident(user['principal']); _grants(user['grants'])
            require(user['username'] not in self.users, 'Duplicate local account')
            require(type(user['iterations']) is int and ITERATIONS <= user['iterations'] <= 2_000_000,
                    'Unsupported password derivation strength')
            require(isinstance(user['salt'], str) and len(user['salt']) == 32
                    and all(c in '0123456789abcdef' for c in user['salt']), 'Invalid credential salt')
            require(isinstance(user['password_sha256'], str) and len(user['password_sha256']) == 64
                    and all(c in '0123456789abcdef' for c in user['password_sha256']), 'Invalid password hash')
            self.users[user['username']] = copy.deepcopy(user)
        self.tokens, self.failures = {}, {}
        self._mutex = threading.RLock()

    def login(self, username, password, server_uuid):
        if (not isinstance(username, str) or not isinstance(password, str)
                or not 0 < len(username) <= 160 or len(password) > 1024):
            raise AuthError('Authentication failed')
        # Unknown login names share one bounded failure bucket. Submitted
        # credentials and tokens never become journal data or exception text.
        user = self.users.get(username)
        bucket = username if user else '<unknown>'
        with self._mutex:
            last, attempts = self.failures.get(bucket, (0., 0))
            if attempts >= 5 and self.clock() - last < 30:
                raise AuthError('Authentication failed')
        salt = bytes.fromhex(user['salt']) if user else bytes(16)
        rounds = user['iterations'] if user else ITERATIONS
        derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, rounds).hex()
        if (user is None or not hmac.compare_digest(derived, user['password_sha256'])
                or server_uuid != self.server_uuid):
            with self._mutex:
                count = self.failures.get(bucket, (0., 0))[1]
                self.failures[bucket] = (self.clock(), count + 1)
            raise AuthError('Authentication failed')
        token = secrets.token_urlsafe(32)
        with self._mutex:
            now = self.clock()
            self.tokens = {key: entry for key, entry in self.tokens.items() if now < entry['deadline']}
            self.failures.pop(bucket, None)
            self.tokens[hashlib.sha256(token.encode()).hexdigest()] = {
                'subject': username, 'principal': user['principal'],
                'grants': copy.deepcopy(user['grants']), 'deadline': now + TOKEN_LIFETIME_S}
        return {'access_token': token, 'token_type': 'Bearer', 'expires_in_s': TOKEN_LIFETIME_S,
                'subject': username, 'server_uuid': self.server_uuid}

    def authorize(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 256:
            raise AuthError('Invalid or expired access token')
        key = hashlib.sha256(token.encode()).hexdigest()
        with self._mutex:
            entry = self.tokens.get(key)
            if entry is None or self.clock() >= entry['deadline']:
                self.tokens.pop(key, None)
                raise AuthError('Invalid or expired access token')
            return AuthContext({name: copy.deepcopy(entry[name])
                                for name in ('subject', 'principal', 'grants')}, self, key)

    def validate_context(self, context):
        """Recheck expiry/revocation; a JSON object cannot forge this handle."""
        if not isinstance(context, AuthContext) or context._access is not self:
            raise AuthError('Authenticated server context required')
        with self._mutex:
            entry = self.tokens.get(context._key)
            expected = None if entry is None else {
                name: copy.deepcopy(entry[name]) for name in ('subject', 'principal', 'grants')}
            if entry is None or self.clock() >= entry['deadline'] or context != expected:
                raise AuthError('Invalid or expired authenticated context')
            return expected

    def logout(self, token):
        self.authorize(token)
        with self._mutex:
            self.tokens.pop(hashlib.sha256(token.encode()).hexdigest(), None)
