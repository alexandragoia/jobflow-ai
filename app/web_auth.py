"""Password access for the private, single-user online deployment."""
import hashlib
import hmac
import os
import secrets
import time
from collections import deque
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from .config import ROOT

COOKIE = 'jobflow_session'
SESSION_SECONDS = 12 * 60 * 60
failures = deque(maxlen=30)


def online_enabled():
    return os.getenv('JOBFLOW_ONLINE') == '1'


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or int(rounds) != 600000:
            return False
        computed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(computed, digest)
    except (ValueError, TypeError):
        return False


def validate_online_config():
    if not online_enabled():
        return
    encoded = os.getenv('JOBFLOW_PASSWORD_HASH', '')
    try:
        algorithm, rounds, salt, digest = encoded.split('$')
        valid_hash = algorithm == 'pbkdf2_sha256' and rounds == '600000' and len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 32
    except ValueError:
        valid_hash = False
    if not valid_hash or len(os.getenv('JOBFLOW_SESSION_SECRET', '')) < 32:
        raise RuntimeError('Configura JOBFLOW_PASSWORD_HASH y JOBFLOW_SESSION_SECRET antes de publicar JobFlow.')
    if not os.getenv('JOBFLOW_ALLOWED_HOSTS') and not os.getenv('RENDER_EXTERNAL_HOSTNAME'):
        raise RuntimeError('Configura el dominio permitido antes de publicar JobFlow.')


def _signature(value):
    return hmac.new(os.environ['JOBFLOW_SESSION_SECRET'].encode(), value.encode(), hashlib.sha256).hexdigest()


def session_token():
    value = f'{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}'
    return value + '.' + _signature(value)


def valid_session(token):
    try:
        expiry, nonce, signature = (token or '').split('.')
        value = expiry + '.' + nonce
        remaining = int(expiry) - time.time()
        return 0 < remaining <= SESSION_SECONDS and len(nonce) == 32 and hmac.compare_digest(signature, _signature(value))
    except (ValueError, TypeError):
        return False


def access_response(request):
    if not online_enabled():
        return None
    path = request.url.path
    if path in ('/login', '/api/login', '/api/health') or path.startswith('/static/'):
        return None
    if valid_session(request.cookies.get(COOKIE)):
        return None
    if path.startswith('/api/'):
        return JSONResponse({'detail': 'Entra con tu contraseña para usar JobFlow.'}, status_code=401)
    return RedirectResponse('/login', status_code=303)


def install_auth(app):
    @app.get('/login', include_in_schema=False)
    def login_page():
        if not online_enabled():
            return RedirectResponse('/', status_code=303)
        return FileResponse(ROOT / 'frontend' / 'login.html')

    @app.post('/api/login', include_in_schema=False)
    async def login(request: Request):
        if not online_enabled():
            return JSONResponse({'detail': 'El acceso online no está activado.'}, status_code=404)
        now = time.monotonic()
        while failures and failures[0] < now - 300:
            failures.popleft()
        if len(failures) >= 10:
            return JSONResponse({'detail': 'Demasiados intentos. Espera cinco minutos.'}, status_code=429)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 4096:
                return JSONResponse({'detail': 'Solicitud demasiado larga.'}, status_code=413)
            body.extend(chunk)
        try:
            password = parse_qs(body.decode('utf-8')).get('password', [''])[0]
        except UnicodeError:
            password = ''
        if not verify_password(password, os.environ['JOBFLOW_PASSWORD_HASH']):
            failures.append(now)
            return JSONResponse({'detail': 'La contraseña no es correcta.'}, status_code=401)
        failures.clear()
        response = JSONResponse({'ok': True})
        response.set_cookie(COOKIE, session_token(), max_age=SESSION_SECONDS, secure=True,
                            httponly=True, samesite='strict', path='/')
        return response

    @app.post('/api/logout', include_in_schema=False)
    def logout():
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
        return response

    @app.get('/api/access')
    def access():
        return {'online': online_enabled(), 'demo': os.getenv('JOBFLOW_DEMO') == '1'}
