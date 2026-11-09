"""The small grey notes on a request page keep each sentence together.

`.status-note` is a flex row (icon, then text). A link or a countdown written straight
inside it becomes its own column and cuts the sentence into pieces, so any note that
has one must put its words in a single <span>.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.tests import make_location, make_request

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


class StatusNoteLayoutTests(TestCase):
    def test_no_note_has_a_link_or_time_directly_inside_the_flex_row(self):
        template = Path("templates/blood_requests/detail.html").read_text(encoding="utf-8")
        for note in re.findall(r'<p class="status-note[^"]*"[^>]*>(.*?)</p>', template, flags=re.S):
            without_span = re.sub(r"<span>.*?</span>", "", note, flags=re.S)
            self.assertNotRegex(without_span, r"<(a|time)\b", note[:80])

    @FAST_HASHER
    def test_the_waiting_sentence_is_one_piece_with_the_countdown_inside(self):
        owner = User.objects.create_user("owner", password="x")
        req = make_request(owner, make_location("Sukkur", "Military Road"), is_verified=False)
        self.client.force_login(owner)
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertRegex(html, r"<span>Waiting for .*? to verify this\. If they don't verify it within <time [^>]*>.*?</time>, an admin decides whether donors see it\.</span>")
