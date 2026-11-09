"""Slows down password guessing on the login form.

After MAX_PER_USERNAME wrong passwords for one username, or MAX_PER_IP wrong
passwords from one address, further attempts are refused for WINDOW_SECONDS, even
with the right password. A success clears that username's counter.

It uses Django's cache, so it needs no table and no migration. The default cache
is per server process, which is right for a single-process university project; a
deployment with several workers would point CACHES at a shared cache instead.
Only REMOTE_ADDR is used for the address: X-Forwarded-For can be forged by the
person being limited.
"""
from django.core.cache import cache

MAX_PER_USERNAME = 5
MAX_PER_IP = 20
WINDOW_SECONDS = 5 * 60


def _keys(request, username):
    ip = request.META.get("REMOTE_ADDR", "unknown") if request is not None else "unknown"
    return (f"login-fail:user:{(username or '').strip().lower()[:150]}", f"login-fail:ip:{ip}")


def is_locked(request, username):
    user_key, ip_key = _keys(request, username)
    return cache.get(user_key, 0) >= MAX_PER_USERNAME or cache.get(ip_key, 0) >= MAX_PER_IP


def record_failure(request, username):
    for key in _keys(request, username):
        # add() sets the window only on the first failure, so the lock ends
        # WINDOW_SECONDS after it began and cannot be extended forever by trying more.
        cache.add(key, 0, WINDOW_SECONDS)
        try:
            cache.incr(key)
        except ValueError:  # the key expired between add() and incr()
            cache.set(key, 1, WINDOW_SECONDS)


def reset(request, username):
    cache.delete(_keys(request, username)[0])
