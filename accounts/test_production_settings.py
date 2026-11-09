"""The settings a hosted site runs with. Checked in a fresh process, because
settings are read once when Django starts."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
PROBE = (
    "import json, django; django.setup(); from django.conf import settings as s; "
    "print(json.dumps({'debug': s.DEBUG, 'hosts': s.ALLOWED_HOSTS, 'csrf': s.CSRF_TRUSTED_ORIGINS, "
    "'session_secure': s.SESSION_COOKIE_SECURE, 'csrf_secure': s.CSRF_COOKIE_SECURE}))"
)


def settings_with(**env):
    full = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
    full.update(DJANGO_SETTINGS_MODULE="config.settings", PYTHONPATH=str(ROOT), **env)
    out = subprocess.run([sys.executable, "-c", PROBE], env=full, cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


class ProductionSettingsTests(SimpleTestCase):
    def test_local_defaults_are_unchanged(self):
        got = settings_with()
        self.assertTrue(got["debug"])
        self.assertFalse(got["session_secure"])
        self.assertEqual(got["csrf"], [])

    def test_a_hosted_site_trusts_its_own_https_origin_and_uses_secure_cookies(self):
        got = settings_with(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="x" * 50,
                            DJANGO_ALLOWED_HOSTS="bloodnet.pythonanywhere.com")
        self.assertFalse(got["debug"])
        self.assertEqual(got["hosts"], ["bloodnet.pythonanywhere.com"])
        self.assertEqual(got["csrf"], ["https://bloodnet.pythonanywhere.com"])
        self.assertTrue(got["session_secure"] and got["csrf_secure"])

    def test_the_trusted_origins_can_be_set_by_hand(self):
        got = settings_with(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="x" * 50, DJANGO_ALLOWED_HOSTS="a.example",
                            DJANGO_CSRF_TRUSTED_ORIGINS="https://a.example,https://b.example")
        self.assertEqual(got["csrf"], ["https://a.example", "https://b.example"])
