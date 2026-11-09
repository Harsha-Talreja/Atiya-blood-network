"""The compact dashboard: a narrow side panel that can fold, totals in the title
row, one-line empty states and a shorter footer. Every feature that was there
before must still be there (the donor's Availability switch lives on Overview
and the donor page; only its side link was dropped)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from core.constants import STATUS_FULFILLED
from hospitals.models import HospitalAccount

User = get_user_model()
FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST
class MyRequestsCompactTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Suhani", "O+", self.location)
        self.me = self.donor.user
        self.client.force_login(self.me)
        self.url = reverse("blood_requests:mine")

    def html(self):
        return self.client.get(self.url).content.decode()

    def test_the_three_totals_sit_in_the_title_row_not_in_a_separate_strip(self):
        make_request(self.me, self.location)
        html = self.html()
        self.assertIn('class="dd-chips"', html)
        self.assertNotIn("dd-strip", html)
        for word in ("open", "fulfilled", "total posted"):
            self.assertIn(word, html)

    def test_the_post_button_and_daily_allowance_are_still_there(self):
        html = self.html()
        self.assertIn(reverse("blood_requests:new"), html)
        self.assertIn("of 3 requests remaining today", html)

    def test_nothing_posted_gives_a_one_line_message(self):
        html = self.html()
        self.assertIn('class="mine-empty"', html)
        self.assertIn("You haven't posted a request", html)
        self.assertNotIn('class="empty-state"', html)

    def test_everything_closed_gives_a_one_line_message_and_keeps_past_requests(self):
        done = make_request(self.me, self.location)
        done.status = STATUS_FULFILLED
        done.fulfilled_at = timezone.now()
        done.save(update_fields=["status", "fulfilled_at"])
        html = self.html()
        self.assertIn("No open requests", html)
        self.assertIn('class="mine-empty"', html)
        self.assertIn("Past requests", html)


@FAST
class SidePanelTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")

    def test_the_panel_keeps_the_links_a_donor_needs_and_drops_only_the_availability_link(self):
        donor = make_donor("Ali Raza", "O+", self.location)
        self.client.force_login(donor.user)
        html = self.client.get(reverse("core:dashboard")).content.decode()
        bar = html[html.index('<nav class="dside"'):html.index("</nav>", html.index('<nav class="dside"'))]
        for label in ("Overview", "Donate blood", "Request blood", "Edit profile", "Log out"):
            with self.subTest(label=label):
                self.assertIn(label, bar)
        # the sub-pages are tabs on the pages, not links in the panel
        for label in ("As a donor", "As a requester", "My details", "Post a request", "Find donors"):
            with self.subTest(gone=label):
                self.assertNotIn(label, bar)
        self.assertNotIn("#availability", bar)
        self.assertIn("Ready to donate", html)  # who you are, and your state, are still shown
        # the switch itself is still on the overview page
        self.assertIn("Available to donate", html)

    def test_every_link_has_a_tooltip_name_so_the_folded_panel_is_usable(self):
        donor = make_donor("Ali Raza", "O+", self.location)
        self.client.force_login(donor.user)
        html = self.client.get(reverse("core:dashboard")).content.decode()
        bar = html[html.index('<nav class="dside"'):html.index("</nav>", html.index('<nav class="dside"'))]
        for label in ("Overview", "Donate blood", "Request blood", "Edit profile", "Log out"):
            with self.subTest(label=label):
                self.assertIn(f'title="{label}"', bar)
        self.assertEqual(bar.count("data-dash-toggle"), 1)
        self.assertIn('aria-expanded="true"', bar)

    def test_a_hospital_panel_is_marked_and_has_no_donor_or_patient_links(self):
        hospital = make_hospital("Civil Hospital", self.location)
        user = User.objects.create_user("civil", password="pw")
        HospitalAccount.objects.create(user=user, hospital=hospital, staff_name="Dr. Test")
        self.client.force_login(user)
        html = self.client.get(reverse("hospitals:dashboard")).content.decode()
        self.assertIn("is-hospital", html)
        bar = html[html.index('<nav class="dside"'):html.index("</nav>", html.index('<nav class="dside"'))]
        self.assertIn("Verification desk", bar)
        self.assertNotIn(reverse("blood_requests:new"), bar)
        self.assertNotIn(reverse("donors:search"), bar)


class FooterTests(TestCase):
    def test_the_shorter_footer_keeps_its_words_links_and_buttons(self):
        html = self.client.get(reverse("core:home")).content.decode()
        footer = html[html.index('<footer class="site-footer">'):]
        self.assertIn("Helping people who need blood", footer)
        self.assertIn("is not a medical service", footer)
        self.assertIn(reverse("core:about"), footer)
        self.assertIn(reverse("blood_requests:new"), footer)
        for text in ("How it works", "Blood compatibility", "FAQ", "Become a donor"):
            self.assertIn(text, footer)


@FAST
class DonorPageCompactTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Suhani", "O+", self.location)
        self.client.force_login(self.donor.user)
        # "I donated today" only shows for a donor who has offered to help a request.
        from blood_requests.models import DonorResponse
        from django.contrib.auth import get_user_model
        family = get_user_model().objects.create_user("compact_family", "cf@example.com", "x")
        other_city = make_location("Rohri", "Rohri City")  # keeps the donor's own list empty
        DonorResponse.objects.create(request=make_request(family, other_city, blood_type="A+"), donor=self.donor)
        self.html = self.client.get(reverse("donors:profile")).content.decode()

    def test_every_part_of_the_availability_card_is_still_there(self):
        for text in ("Ready to donate", "Available to donate", "I donated today",
                     "data-availability-toggle", "data-availability-note", "data-availability-label", 'id="availability"'):
            with self.subTest(text=text):
                self.assertIn(text, self.html)

    def test_the_switch_and_donated_button_sit_in_their_own_column(self):
        card = self.html[self.html.index('id="availability"'):self.html.index('class="panel" id=')]
        self.assertIn('class="av-acts"', card)
        self.assertLess(card.index("data-availability-note"), card.index('class="av-acts"'))
        self.assertNotIn('class="av-fine"', card)

    def test_requests_and_details_are_still_there_and_the_empty_box_is_one_line(self):
        details = self.client.get(reverse("donors:profile") + "?tab=details").content.decode()
        for text in ("Requests you can help with", "View all"):
            with self.subTest(text=text):
                self.assertIn(text, self.html)
        for text in ("Your details", "Blood type", "Mobile number", "Area", "Last donation", "Phone sharing"):
            with self.subTest(text=text):
                self.assertIn(text, details)
        self.assertIn('class="mine-empty"', self.html)
        self.assertIn("No matching requests right now", self.html)
        self.assertNotIn('class="empty-state"', self.html)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DeskNavbarTests(TestCase):
    """An admin or hospital login sees one link in the navbar: its own dashboard."""

    PUBLIC_LINKS = ("Live requests", "Compatibility", "How it works", "FAQ")

    def nav(self, user, url):
        from django.contrib.auth import get_user_model  # noqa: F401
        self.client.force_login(user)
        html = self.client.get(url, follow=True).content.decode()
        start = html.index('<header class="site-header')
        return html[start:html.index("</header>", start)]

    def test_an_admin_sees_only_the_dashboard_link(self):
        from django.contrib.auth import get_user_model
        admin = get_user_model().objects.create_user("boss", password="x", is_staff=True)
        nav = self.nav(admin, reverse("core:about"))
        self.assertIn(">Dashboard</a>", nav)
        for text in self.PUBLIC_LINKS + (">Home</a>",):
            with self.subTest(text=text):
                self.assertNotIn(text, nav)
        self.assertNotIn("Request blood", nav)

    def test_a_hospital_login_sees_only_the_dashboard_link(self):
        from hospitals.models import HospitalAccount
        account = HospitalAccount.objects.first()
        nav = self.nav(account.user, reverse("hospitals:dashboard"))
        self.assertIn(reverse("hospitals:dashboard"), nav)
        self.assertIn(">Dashboard</a>", nav)
        for text in self.PUBLIC_LINKS + (">Home</a>",):
            with self.subTest(text=text):
                self.assertNotIn(text, nav)

    def test_an_ordinary_visitor_still_sees_the_public_links(self):
        html = self.client.get(reverse("core:home")).content.decode()
        nav = html[html.index('<header class="site-header'):html.index("</header>")]
        for text in self.PUBLIC_LINKS:
            with self.subTest(text=text):
                self.assertIn(text, nav)
