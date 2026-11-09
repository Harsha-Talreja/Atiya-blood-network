"""A lighter PBKDF2 setting for sign-in speed on a small shared server.

Same algorithm and same stored format as Django's PBKDF2 hasher; only the number
of rounds is lower (600,000, the figure OWASP currently recommends for
PBKDF2-SHA256). Existing passwords still verify, and Django re-saves them with
this hasher the next time the person signs in, because it is first in the list.
"""
from django.contrib.auth.hashers import PBKDF2PasswordHasher


class FastPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    iterations = 600_000
