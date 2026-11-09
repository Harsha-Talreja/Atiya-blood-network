"""The signed-in dashboard: the overview page and the side panel shared by its pages."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from hospitals.models import HospitalAccount

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def panel_of(html):
    """Just the side panel's markup, so a check cannot pass on the navbar or footer."""
    return html[html.index('<nav class="dside"'):html.index("</nav>", html.index('<nav class="dside"'))]


@FAST_HASHER
class OverviewAccessTests(TestCase):
    def test_signed_out_people_are_sent_to_log_in(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(response, f'{reverse("accounts:login")}?next={reverse("core:dashboard")}')

    def test_logging_in_lands_on_the_dashboard(self):
        User.objects.create_user("ali", password="pw")
        response = self.client.post(reverse("accounts:login"), {"username": "ali", "password": "pw"}, follow=True)
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertContains(response, "Dashboard")

    def test_a_hospital_account_is_sent_to_its_own_desk(self):
        location = make_location("Sukkur", "Military Road")
        hospital = make_hospital("Civil Hospital", location)
        user = User.objects.create_user("civil", password="pw")
        HospitalAccount.objects.create(user=user, hospital=hospital, staff_name="Dr. Test")
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse("core:dashboard")), reverse("hospitals:dashboard"))


@FAST_HASHER
class OverviewContentTests(TestCase):
    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(self.donor.user)
        self.url = reverse("core:dashboard")

    def test_a_donor_gets_both_roles_on_one_page(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Donate blood", html)
        self.assertIn("Request blood", html)
        self.assertIn("Ready to donate", html)
        self.assertIn(reverse("donors:toggle"), html)
        self.assertIn(reverse("blood_requests:new"), html)

    def test_counts_are_real(self):
        other = User.objects.create_user("family", password="x")
        hospital = make_hospital("Civil Hospital", self.sukkur)
        make_request(other, self.sukkur, hospital=hospital, blood_type="O+", is_verified=True)
        make_request(self.donor.user, self.sukkur, hospital=hospital)
        response = self.client.get(self.url)
        self.assertEqual(response.context["matching_total"], 1)
        self.assertEqual(response.context["open_count"], 1)
        self.assertContains(response, "1 request open")
        self.assertContains(response, "1 matching request in Sukkur")

    def test_a_person_who_is_not_a_donor_is_invited_to_become_one(self):
        self.client.force_login(User.objects.create_user("plain", password="x"))
        response = self.client.get(self.url)
        self.assertContains(response, "You are not a donor yet")
        self.assertContains(response, reverse("donors:edit"))
        self.assertNotContains(response, reverse("donors:toggle"))
        self.assertContains(response, "0 requests open")

    def test_no_invented_numbers(self):
        html = self.client.get(self.url).content.decode()
        for claim in ("Lives saved", "Lives impacted", "verified donor", "in minutes"):
            self.assertNotIn(claim, html)


@FAST_HASHER
class SidePanelTests(TestCase):
    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")

    def test_a_donor_sees_the_donor_and_requester_sections(self):
        donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(donor.user)
        panel = panel_of(self.client.get(reverse("core:dashboard")).content.decode())
        for target in (reverse("donors:profile"), reverse("blood_requests:mine"),
                       reverse("donors:edit"), reverse("accounts:logout")):
            with self.subTest(target=target):
                self.assertIn(target, panel)
        # Post a request and Find donors are tabs on the Request blood pages, not panel links
        for target in (reverse("blood_requests:new"), reverse("donors:search")):
            with self.subTest(tab=target):
                self.assertNotIn(target, panel)
                self.assertContains(self.client.get(reverse("blood_requests:mine")), f'href="{target}"')
        self.assertNotIn(reverse("siteadmin:overview"), panel)

    def test_the_current_page_is_marked(self):
        donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(donor.user)
        panel = panel_of(self.client.get(reverse("blood_requests:mine")).content.decode())
        marked = panel[panel.index('aria-current="page"') - 120:panel.index('aria-current="page"') + 60]
        self.assertIn(reverse("blood_requests:mine"), marked)

    def test_staff_have_no_donor_dashboard_only_the_admin_panel(self):
        staff = User.objects.create_user("boss", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertRedirects(self.client.get(reverse("core:dashboard")), reverse("siteadmin:overview"))

    def test_a_hospital_sees_only_its_desk_and_no_donor_or_patient_entries(self):
        hospital = make_hospital("Civil Hospital", self.sukkur)
        user = User.objects.create_user("civil", password="pw")
        HospitalAccount.objects.create(user=user, hospital=hospital, staff_name="Dr. Test")
        self.client.force_login(user)
        panel = panel_of(self.client.get(reverse("hospitals:dashboard")).content.decode())
        self.assertIn("Verification desk", panel)
        for target in (reverse("blood_requests:new"), reverse("donors:search"), reverse("donors:edit"),
                       reverse("blood_requests:mine"), reverse("donors:profile")):
            with self.subTest(target=target):
                self.assertNotIn(target, panel)
        self.assertNotIn("Donate blood", panel)
        self.assertNotIn("Request blood", panel)

    def test_the_panel_is_on_every_dashboard_page(self):
        donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(donor.user)
        for name in ("core:dashboard", "donors:profile", "blood_requests:mine"):
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name)), 'class="dside"')


@FAST_HASHER
class PageTabsTests(TestCase):
    """The old panel links now live as tabs at the top of the Donate blood and Request blood pages."""

    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(self.donor.user)

    def tabs_of(self, url):
        html = self.client.get(url).content.decode()
        start = html.index('<nav class="dtabs"')
        return html[start:html.index("</nav>", start)]

    def test_donate_pages_have_two_tabs_and_mark_the_open_one(self):
        for tab, other in (("requests", "details"), ("details", "requests")):
            with self.subTest(tab=tab):
                bar = self.tabs_of(f'{reverse("donors:profile")}?tab={tab}')
                self.assertIn("Requests for you", bar)
                self.assertIn("My details", bar)
                self.assertEqual(bar.count('aria-current="page"'), 1)
                self.assertIn(f'?tab={tab}"', bar[:bar.index('aria-current="page"')][-80:] + '"')

    def test_request_pages_have_three_tabs_on_every_page(self):
        for name in ("blood_requests:mine", "donors:search"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="dside"')
                bar = self.tabs_of(reverse(name))
                for label in ("My requests", "Post a request", "Find donors"):
                    self.assertIn(label, bar)
                self.assertEqual(bar.count('aria-current="page"'), 1)

    def test_the_panel_marks_request_blood_on_all_three_request_pages(self):
        for name in ("blood_requests:mine", "donors:search"):
            with self.subTest(page=name):
                panel = panel_of(self.client.get(reverse(name)).content.decode())
                marked = panel[panel.index('aria-current="page"') - 140:panel.index('aria-current="page"') + 40]
                self.assertIn(reverse("blood_requests:mine"), marked)

    def test_a_hospital_account_gets_no_tabs(self):
        hospital = make_hospital("Civil Hospital", self.sukkur)
        user = User.objects.create_user("civil", password="pw")
        HospitalAccount.objects.create(user=user, hospital=hospital, staff_name="Dr. Test")
        self.client.force_login(user)
        self.assertNotContains(self.client.get(reverse("hospitals:dashboard")), 'class="dtabs"')
