from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.tests import make_hospital, make_location, make_request

User = get_user_model()


class CheckRequests(TestCase):
    def test_it_names_the_tab_each_request_is_in(self):
        loc = make_location("Sukkur", "Military Road")
        h = make_hospital("Civil Hospital", loc)
        u = User.objects.create_user("fam", password="x")
        big = make_request(u, loc, hospital=h, units_needed=9, is_verified=False, extra_reason="x" * 30)
        late = make_request(u, loc, hospital=h, is_verified=False)
        BloodRequest.objects.filter(pk=late.pk).update(created_at=timezone.now() - timedelta(minutes=10))
        BloodRequest.objects.filter(pk=big.pk).update(created_at=timezone.now() - timedelta(days=1))
        fresh = make_request(u, loc, hospital=h, is_verified=False)
        out = StringIO()
        call_command("check_requests", stdout=out)
        text = out.getvalue()
        self.assertIn(f"#{big.pk}", text)
        self.assertIn("ADMIN: Extra units", text)
        self.assertIn("ADMIN: Timed out", text)
        self.assertIn("Hospital only", text)
