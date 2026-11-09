"""Tests for the home page, template helpers, and the 'works offline' guarantee."""
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from blood_requests.tests import make_donor, make_location, make_request
from core.constants import (
    STATUS_FULFILLED, URGENCY_CRITICAL, URGENCY_NORMAL, URGENCY_URGENT,
)
from core.templatetags.core_extras import pretty_blood, time_ago, time_left

User = get_user_model()


class HomePageTests(TestCase):
    def setUp(self):
        self.url = reverse("core:home")
        self.requester = User.objects.create_user(username="requester")
        self.sukkur = make_location("Sukkur", "Military Road")

    def test_home_loads_with_site_name(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, settings.SITE_NAME)

    def test_empty_database_shows_friendly_empty_states(self):
        response = self.client.get(self.url)
        self.assertContains(response, "No open requests right now")
        self.assertContains(response, "No donors registered yet")
        self.assertEqual(response.context["donor_count"], 0)
        self.assertEqual(response.context["open_count"], 0)

    def test_counts_come_from_the_database(self):
        make_donor("d1", "O-", self.sukkur)
        make_donor("d2", "A+", self.sukkur)
        make_request(self.requester, self.sukkur)
        make_request(self.requester, self.sukkur, status=STATUS_FULFILLED)
        response = self.client.get(self.url)
        self.assertEqual(response.context["donor_count"], 2)
        self.assertEqual(response.context["open_count"], 1)
        self.assertEqual(response.context["fulfilled_count"], 1)
        self.assertEqual(response.context["city_count"], 6)  # cities seeded by the migration

    def test_expired_and_fulfilled_requests_are_not_listed_as_open(self):
        make_request(self.requester, self.sukkur, patient_name="Open One")
        make_request(self.requester, self.sukkur, patient_name="Fulfilled", status=STATUS_FULFILLED)
        make_request(self.requester, self.sukkur, patient_name="Expired",
                     expires_at=timezone.now() - timedelta(minutes=1))
        listed = list(self.client.get(self.url).context["latest_requests"])
        self.assertEqual([r.patient_name for r in listed], ["Open One"])

    def test_most_urgent_requests_come_first(self):
        make_request(self.requester, self.sukkur, urgency=URGENCY_NORMAL, patient_name="normal")
        make_request(self.requester, self.sukkur, urgency=URGENCY_CRITICAL, patient_name="critical")
        make_request(self.requester, self.sukkur, urgency=URGENCY_URGENT, patient_name="urgent")
        listed = list(self.client.get(self.url).context["latest_requests"])
        self.assertEqual([r.patient_name for r in listed], ["critical", "urgent", "normal"])

    def test_home_shows_at_most_three_requests(self):
        for i in range(5):
            make_request(self.requester, self.sukkur, patient_name=f"p{i}")
        self.assertEqual(len(self.client.get(self.url).context["latest_requests"]), 3)

    def test_phone_numbers_never_appear_on_the_public_home_page(self):
        make_request(self.requester, self.sukkur, contact_phone="03009998877")
        donor = make_donor("private_donor", "O-", self.sukkur)
        donor.phone = "03001112233"
        donor.save()
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("03009998877", html)
        self.assertNotIn("03001112233", html)

    def test_availability_bars_only_count_ready_donors(self):
        make_donor("ready", "O-", self.sukkur)
        make_donor("resting", "O-", self.sukkur, days_since_donation=10)
        make_donor("away", "O-", self.sukkur, is_available=False)
        rows = {r["blood_type"]: r for r in self.client.get(self.url).context["availability"]}
        self.assertEqual(rows["O-"]["count"], 1)
        self.assertEqual(rows["O-"]["percent"], 100)
        self.assertEqual(rows["A+"]["count"], 0)
        self.assertEqual(rows["A+"]["percent"], 0)

    def test_compatibility_data_is_embedded_for_the_checker(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'id="compat-data"')
        self.assertEqual(response.context["compatibility"]["O-"], ["O-"])

    def test_headline_reads_as_one_sentence(self):
        # The headline has one word wrapped in <em> for the red accent.
        # Screen readers and search engines must still get one clean sentence.
        html = self.client.get(self.url).content.decode()
        heading = re.search(r'<h1 class="hero-title[^"]*"[^>]*>(.*?)</h1>', html, re.S).group(1)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", heading)).strip()
        self.assertEqual(text, "Post. Match. Donate.")

    def test_hero_numbers_are_real_counts_not_made_up_ones(self):
        # The hero shows four figures. They must be the database's own counts:
        # an empty site shows zeros rather than a flattering invented number.
        html = self.client.get(self.url).content.decode()
        hero = html[html.index('class="hero hero-premium"'):html.index("<!-- HOW IT WORKS -->")]
        counts = re.findall(r'class="metric-n" data-count="(\d+)">(\d+)<', hero)
        self.assertEqual(len(counts), 4)
        for target, shown in counts:
            self.assertEqual(target, shown)
        context = self.client.get(self.url).context
        self.assertEqual(
            [int(t) for t, _ in counts],
            [context["donor_count"], context["open_count"],
             context["fulfilled_count"], context["city_count"]],
        )

    def test_hero_makes_no_claim_that_donors_are_verified(self):
        # Nobody checks a donor's identity here, so the artwork must not say so.
        html = self.client.get(self.url).content.decode()
        hero = html[html.index('class="hero hero-premium"'):html.index("<!-- HOW IT WORKS -->")]
        self.assertNotIn("Verified profile", hero)
        self.assertNotIn("verified donor", hero.lower())

    def test_page_has_reduced_motion_support(self):
        css = Path(finders.find("css/theme.css")).read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion: reduce", css)
        js = Path(finders.find("js/main.js")).read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion: reduce", js)

    def test_logged_in_staff_sees_admin_link(self):
        User.objects.create_superuser("boss", password="x-Strong-pass-1")
        self.client.login(username="boss", password="x-Strong-pass-1")
        # An admin has no donor dashboard: the dashboard address leads to the panel,
        # and the name in the top bar is a plain link to it.
        self.assertRedirects(self.client.get(reverse("core:dashboard")), reverse("siteadmin:overview"))
        self.assertContains(self.client.get(self.url), reverse("siteadmin:overview"))
        self.assertNotContains(self.client.get(self.url), "Admin panel")


class NoDeadLinksTests(TestCase):
    """A button that does nothing (or just toasts "coming soon") is worse than no
    button, especially in a demo. Zero donors is the state a fresh database is in,
    so that's the case that has to be right."""

    def test_home_page_has_no_placeholder_links_for_a_visitor(self):
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, "data-soon")
        self.assertNotContains(response, 'href="#"')

    def test_visitor_empty_state_button_goes_to_signup_then_the_donor_form(self):
        response = self.client.get(reverse("core:home"))
        expected = f'href="{reverse("accounts:signup")}?next={reverse("donors:edit")}" class="btn btn-brand">Become a donor'
        self.assertContains(response, expected)

    def test_signed_in_users_empty_state_button_goes_to_their_donor_page(self):
        self.client.force_login(User.objects.create_user(username="someone"))
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, f'href="{reverse("donors:profile")}" class="btn btn-brand">Become a donor')

    def test_component_never_renders_a_button_without_a_real_destination(self):
        from django.template.loader import render_to_string
        html = render_to_string("components/empty_state.html", {"title": "T", "text": "x", "cta_label": "Click me"})
        self.assertNotIn("Click me", html)
        self.assertNotIn('href="#"', html)

    def test_component_renders_a_real_button_when_given_a_url(self):
        from django.template.loader import render_to_string
        html = render_to_string(
            "components/empty_state.html",
            {"title": "T", "text": "x", "cta_label": "Go", "cta_url": "/somewhere/", "cta_next": "/after/"},
        )
        self.assertIn('href="/somewhere/?next=/after/"', html)


class AboutPageTests(TestCase):
    def test_page_loads_and_shows_the_cooldown_and_expiry_hours(self):
        response = self.client.get(reverse("core:about"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "90")   # DONATION_COOLDOWN_DAYS
        self.assertContains(response, "24")   # Critical urgency hours
        self.assertContains(response, "48")   # Urgent urgency hours
        self.assertContains(response, "72")   # Normal urgency hours

    def test_reachable_from_the_footer(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn(f'href="{reverse("core:about")}"', html)


class TemplateFilterTests(SimpleTestCase):
    def test_pretty_blood_uses_a_real_minus_sign(self):
        self.assertEqual(pretty_blood("O-"), "O\u2212")
        self.assertEqual(pretty_blood("AB-"), "AB\u2212")
        self.assertEqual(pretty_blood("A+"), "A+")


class WorksOfflineTests(TestCase):
    """The demo must work with no internet: every file is local, nothing loads from a CDN."""

    def test_every_static_file_referenced_by_templates_exists(self):
        found = set()
        for template in Path(settings.BASE_DIR, "templates").rglob("*.html"):
            found |= set(re.findall(r"{%\s*static\s+'([^']+)'\s*%}", template.read_text(encoding="utf-8")))
        self.assertGreater(len(found), 8)
        for path in sorted(found):
            with self.subTest(static=path):
                self.assertIsNotNone(finders.find(path), f"missing static file: {path}")

    def test_files_referenced_inside_css_exist(self):
        for css in ("css/theme.css", "vendor/bootstrap-icons/bootstrap-icons.min.css"):
            css_path = Path(finders.find(css))
            for ref in re.findall(r"url\(\s*[\"']?([^\"')]+)[\"']?\s*\)", css_path.read_text(encoding="utf-8")):
                if ref.startswith(("data:", "#", "http")):
                    continue
                target = (css_path.parent / ref.split("?")[0].split("#")[0]).resolve()
                with self.subTest(css=css, ref=ref):
                    self.assertTrue(target.exists(), f"{css} points to a missing file: {ref}")

    def test_home_page_loads_nothing_from_the_internet(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIsNone(re.search(r"""(?:src|href)=["']https?://""", html))
        for host in ("googleapis", "gstatic", "cdn.", "unpkg", "jsdelivr", "cloudflare"):
            self.assertNotIn(host, html)

    def test_css_never_imports_remote_files(self):
        for css in ("css/theme.css", "vendor/bootstrap/bootstrap.min.css", "vendor/aos/aos.css"):
            text = Path(finders.find(css)).read_text(encoding="utf-8")
            with self.subTest(css=css):
                self.assertIsNone(re.search(r"@import[^;]*https?://", text))


class TimeFilterTests(SimpleTestCase):
    def test_time_ago_says_just_now_for_fresh_items(self):
        self.assertEqual(time_ago(timezone.now() - timedelta(seconds=10)), "just now")

    def test_time_ago_uses_a_single_unit(self):
        # Django joins number and unit with a non-breaking space so they never split across lines.
        result = time_ago(timezone.now() - timedelta(hours=2, minutes=30))
        self.assertEqual(result.replace("\xa0", " "), "2 hours ago")

    def test_time_left_uses_a_single_unit(self):
        result = time_left(timezone.now() + timedelta(hours=5, minutes=30))
        self.assertEqual(result.replace("\xa0", " "), "5 hours")

    def test_filters_tolerate_none(self):
        self.assertEqual(time_ago(None), "")
        self.assertEqual(time_left(None), "")


class LiveRequestsNavTests(TestCase):
    """The navbar's "Live requests" item and the strip under the hero buttons."""

    def setUp(self):
        self.requester = User.objects.create_user(username="requester")
        self.sukkur = make_location("Sukkur", "Military Road")

    def test_navbar_says_live_requests_and_compatibility(self):
        html = self.client.get(reverse("core:home")).content.decode()
        nav = html[html.index('<nav class="navbar'):html.index("</nav>")]
        self.assertIn("Live requests", nav)
        self.assertIn(f'href="{reverse("core:home")}#compatibility"', nav)
        # The plain "Requests" link is gone: the live item points at the same list.
        self.assertNotRegex(nav, r">\s*Requests\s*</a>")

    def test_navbar_count_matches_what_donors_can_see(self):
        make_request(self.requester, self.sukkur, patient_name="Visible One")
        make_request(self.requester, self.sukkur, patient_name="Visible Two")
        # Unverified and still inside its wait: nobody but the requester can see it.
        make_request(self.requester, self.sukkur, patient_name="Hidden", is_verified=False)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertRegex(html, r'class="nav-count" aria-label="2 open">2<')

    def test_navbar_link_goes_to_the_public_board(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertRegex(html, rf'<a class="nav-link nav-live[^"]*" href="{reverse("blood_requests:list")}"')

    def test_hero_strip_lists_only_visible_requests(self):
        visible = make_request(self.requester, self.sukkur, patient_name="Visible One")
        make_request(self.requester, self.sukkur, patient_name="Hidden", is_verified=False)
        response = self.client.get(reverse("core:home"))
        self.assertEqual([r.pk for r in response.context["live_requests"]], [visible.pk])
        self.assertContains(response, "data-live-strip")
        self.assertContains(response, reverse("blood_requests:detail", args=[visible.pk]))

    def test_strip_says_so_when_nothing_is_open(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "data-live-strip")
        self.assertContains(response, "No open requests right now")
        self.assertNotContains(response, 'class="live-slide')


class LiveBoxTests(TestCase):
    """The glass box in the hero: real counts, no names."""

    def setUp(self):
        self.requester = User.objects.create_user(username="requester")
        self.sukkur = make_location("Sukkur", "Military Road")

    def test_counts_are_real_and_empty_state_is_honest(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "data-live-box")
        self.assertContains(response, "Nothing yet.")
        self.assertRegex(response.content.decode(), r"Donors ready now</small><b>0</b>")
        self.assertRegex(response.content.decode(), r"Patients waiting</small><b>0</b>")

    def test_ready_and_waiting_numbers_match_the_database(self):
        make_donor("Ready One", "A+", self.sukkur)
        make_donor("Ready Two", "O-", self.sukkur, days_since_donation=200)
        make_donor("Resting", "B+", self.sukkur, days_since_donation=10)
        make_request(self.requester, self.sukkur, patient_name="Visible")
        make_request(self.requester, self.sukkur, patient_name="Hidden", is_verified=False)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertRegex(html, r"Donors ready now</small><b>2</b>")
        self.assertRegex(html, r"Patients waiting</small><b>1</b>")

    def test_feed_shows_blood_type_and_city_only(self):
        make_donor("Secret Name", "A+", self.sukkur)
        make_request(self.requester, self.sukkur, blood_type="O-", patient_name="Private Patient")
        html = self.client.get(reverse("core:home")).content.decode()
        box = html[html.index("data-live-box"):html.index("</ul>", html.index("data-live-box"))]
        self.assertIn("donor ready", box)
        self.assertIn("needed", box)
        self.assertIn("Sukkur", box)
        for private in ("Secret Name", "Private Patient", "03001234567"):
            self.assertNotIn(private, box)


class HomeSectionsTests(TestCase):
    """The home page sections after the glass redesign: no duplicates, honest numbers."""

    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")

    def test_each_idea_appears_once(self):
        html = self.client.get(reverse("core:home")).content.decode()
        for marker in ('id="how-it-works"', 'id="matching"', 'id="compatibility"', 'id="requests"',
                       'id="availability"', 'id="faq"', "data-home-cta"):
            self.assertEqual(html.count(marker), 1, marker)
        # Said by the matching section already, so the old cards and banner are gone.
        for gone in ("Built for emergencies", "cta-band", "trust-card", "step-card", "eq-row", "flow-card"):
            self.assertNotIn(gone, html)

    def test_how_it_works_is_four_rows_of_old_way_against_network_way(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertEqual(html.count('class="lrow'), 5)  # a header row and four steps
        for step in ("Post in a group", "Request posted", "Search restarts", "Direct contact"):
            self.assertEqual(html.count(step), 1, step)

    def test_need_and_give_share_one_tabbed_card_with_both_panels_in_the_page(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertEqual(html.count("data-tabs"), 1)
        self.assertEqual(html.count('role="tabpanel"'), 2)
        self.assertIn("broadcast an emergency", html)
        self.assertIn("Be found when your blood type", html)

    def test_matching_funnel_says_it_is_an_idea_not_a_count(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("They are not counts", html)
        self.assertEqual(html.count('class="frow'), 5)

    def test_footer_keeps_its_links_and_the_not_a_medical_service_notice(self):
        html = self.client.get(reverse("core:home")).content.decode()
        footer = html[html.index('<footer class="site-footer">'):]
        self.assertIn(reverse("core:about"), footer)
        self.assertIn("is not a medical service", footer)

    def test_matching_section_describes_only_what_the_code_checks(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("Same city", html)
        self.assertIn("90-day rest", html)
        self.assertNotIn("closer to the hospital", html)  # distance is not part of matching
        self.assertIn("Not a guarantee", html)

    def test_amber_bars_only_when_groups_differ_and_total_is_shown(self):
        from core.constants import BLOOD_TYPES
        total = 0
        for blood_type in BLOOD_TYPES:
            for n in range(1 if blood_type == "B+" else 2):
                make_donor(f"{blood_type}-{n}", blood_type, self.sukkur)
                total += 1
        response = self.client.get(reverse("core:home"))
        rows = {row["blood_type"]: row for row in response.context["availability"]}
        self.assertTrue(rows["B+"]["low"])
        self.assertFalse(rows["A+"]["low"])
        self.assertTrue(response.context["show_low_key"])
        self.assertContains(response, f"<strong>{total}</strong> donors ready now")

    def test_an_empty_blood_type_is_not_painted_amber(self):
        make_donor("A One", "A+", self.sukkur)
        make_donor("A Two", "A+", self.sukkur)
        response = self.client.get(reverse("core:home"))
        self.assertFalse(any(row["low"] for row in response.context["availability"]))
        self.assertFalse(response.context["show_low_key"])

    def test_no_amber_when_every_group_is_equal(self):
        from core.constants import BLOOD_TYPES
        for index, blood_type in enumerate(BLOOD_TYPES):
            make_donor(f"Donor {index}", blood_type, self.sukkur)
        response = self.client.get(reverse("core:home"))
        self.assertFalse(any(row["low"] for row in response.context["availability"]))
        self.assertFalse(response.context["show_low_key"])
