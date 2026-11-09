"""Tests for the donor pages: registration form, dashboard, availability switch, 'I donated today'."""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.matching import find_matching_donors
from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from core.constants import STATUS_FULFILLED, URGENCY_CRITICAL, URGENCY_NORMAL
from donors.models import DonorProfile
from donors.views import DASHBOARD_REQUESTS, RING_LENGTH

User = get_user_model()

# Real password hashing is deliberately slow; these tests are about donor pages, so use a fast hasher.
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def form_data(area, omit=(), **overrides):
    """A valid registration form as the browser would send it (unticked boxes are simply absent)."""
    data = {"full_name": "Ali Raza", "phone": "03001234567", "blood_type": "O-", "location": str(area.pk),
            "last_donation_date": "", "is_available": "on", "phone_consent": "on", "eligibility_declared": "on",
            "cnic": "4210112345671", "weight_kg": "68", "height_cm": "172", "conditions": ["none"]}
    data["never_donated"] = "on"          # the last donation is asked of everyone: a date, or "never donated"
    data.update(overrides)
    if overrides.get("last_donation_date") and "never_donated" not in overrides:
        data.pop("never_donated")          # a date was given, so the box is not ticked
    for key in omit:
        data.pop(key, None)
    return data


@FAST_HASHER
class AccessTests(TestCase):
    def test_every_donor_page_needs_a_login(self):
        for name in ("donors:profile", "donors:edit", "donors:toggle", "donors:donated"):
            for method in ("get", "post"):
                with self.subTest(page=name, method=method):
                    response = getattr(self.client, method)(reverse(name))
                    self.assertEqual(response.status_code, 302)
                    self.assertIn(reverse("accounts:login"), response["Location"])


@FAST_HASHER
class EditProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ali", "ali@example.com", "x")
        self.client.force_login(self.user)
        self.sukkur = make_location("Sukkur", "Military Road")
        self.url = reverse("donors:edit")

    def test_registration_form_has_every_field_and_grouped_areas(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for name in ("full_name", "phone", "blood_type", "location", "last_donation_date",
                     "is_available", "phone_consent", "eligibility_declared"):
            self.assertContains(response, f'name="{name}"')
        self.assertContains(response, '<optgroup label="Sukkur">')
        self.assertContains(response, "Become a donor")
        self.assertContains(response, 'data-digits="11"')

    def test_date_picker_cannot_choose_the_future(self):
        self.assertContains(self.client.get(self.url), f'max="{timezone.localdate().isoformat()}"')

    def test_valid_form_creates_the_profile_for_the_signed_in_user(self):
        response = self.client.post(self.url, form_data(self.sukkur), follow=True)
        self.assertRedirects(response, reverse("donors:profile"))
        donor = DonorProfile.objects.get()
        self.assertEqual(donor.user, self.user)
        self.assertEqual((donor.full_name, donor.blood_type, donor.location), ("Ali Raza", "O-", self.sukkur))
        self.assertTrue(donor.is_available and donor.phone_consent and donor.eligibility_declared)
        self.assertContains(response, "data-flash-dialog")
        self.assertContains(response, "a donor now")

    def test_invalid_input_is_rejected_and_nothing_is_saved(self):
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        cases = {
            "blank name": ({"full_name": ""}, (), "full_name"),
            "bad phone": ({"phone": "12345"}, (), "phone"),
            "future donation date": ({"last_donation_date": tomorrow}, (), "last_donation_date"),
            "no declaration": ({}, ("eligibility_declared",), "eligibility_declared"),
            "no phone consent": ({}, ("phone_consent",), "phone_consent"),
            "unknown blood type": ({"blood_type": "Z+"}, (), "blood_type"),
            "no blood type": ({"blood_type": ""}, (), "blood_type"),
            "unknown area": ({"location": "999999"}, (), "location"),
            "no area": ({"location": ""}, (), "location"),
        }
        for label, (overrides, omit, field) in cases.items():
            with self.subTest(case=label):
                response = self.client.post(self.url, form_data(self.sukkur, omit=omit, **overrides))
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertFalse(DonorProfile.objects.exists())

    def test_errors_are_shown_with_accessibility_hooks(self):
        response = self.client.post(self.url, form_data(self.sukkur, phone="12345"))
        self.assertContains(response, "is-invalid")
        self.assertContains(response, 'aria-invalid="true"')

    def test_only_an_eleven_digit_mobile_number_is_accepted(self):
        self.client.post(self.url, form_data(self.sukkur, phone="03001234567"))
        self.assertEqual(DonorProfile.objects.get().phone, "03001234567")
        for phone in ("+923001234567", "030012345678", "0300123456", "0300-1234567", "abcdefghijk"):
            with self.subTest(phone=phone):
                response = self.client.post(self.url, form_data(self.sukkur, phone=phone))
                self.assertIn("phone", response.context["form"].errors)
        self.assertEqual(DonorProfile.objects.get().phone, "03001234567")

    def test_submitting_again_updates_instead_of_creating_a_second_profile(self):
        self.client.post(self.url, form_data(self.sukkur))
        response = self.client.post(self.url, form_data(self.sukkur, full_name="Ali R. Khan", blood_type="A+"), follow=True)
        self.assertEqual(DonorProfile.objects.count(), 1)
        donor = DonorProfile.objects.get()
        self.assertEqual((donor.full_name, donor.blood_type), ("Ali R. Khan", "A+"))
        self.assertContains(response, "Your donor profile has been updated.")

    def test_editing_shows_the_saved_values(self):
        self.client.post(self.url, form_data(self.sukkur))
        response = self.client.get(self.url)
        self.assertContains(response, 'value="Ali Raza"')
        self.assertRegex(response.content.decode(), r'value="O-"[^>]*checked')
        self.assertContains(response, f'value="{self.sukkur.pk}" selected')
        self.assertContains(response, "Edit your donor profile")

    def test_the_owner_cannot_be_changed_through_the_form(self):
        other = User.objects.create_user("other", "other@example.com", "x")
        self.client.post(self.url, form_data(self.sukkur, user=str(other.pk)))
        self.assertEqual(DonorProfile.objects.get().user, self.user)
        self.assertFalse(DonorProfile.objects.filter(user=other).exists())

    def test_someone_elses_details_are_never_shown(self):
        self.client.post(self.url, form_data(self.sukkur), follow=True)   # follow: the welcome message is shown and used up
        stranger = User.objects.create_user("stranger", "s@example.com", "x")
        self.client.force_login(stranger)
        page = self.client.get(self.url).content.decode()
        self.assertNotIn('value="Ali Raza"', page)
        self.assertNotIn('value="03001234567"', page)   # (the greyed example text is only a placeholder)
        self.assertIn("Become a donor", page)          # a fresh, empty form, not Ali's profile


@FAST_HASHER
class DashboardTests(TestCase):
    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(self.donor.user)
        self.url = reverse("donors:profile")

    def test_people_without_a_profile_are_sent_to_the_form(self):
        self.client.force_login(User.objects.create_user("newbie", "n@example.com", "x"))
        self.assertRedirects(self.client.get(self.url), reverse("donors:edit"))

    def test_shows_the_donors_details(self):
        response = self.client.get(self.url + "?tab=details")
        # The greeting follows the time of day; what must always be there is
        # the donor's first name in it and their full name in the profile strip.
        self.assertContains(response, f"{response.context['greeting']}, Ali")
        self.assertContains(response, "Ali Raza")
        self.assertContains(response, "Military Road, Sukkur")
        self.assertContains(response, "03001234567")

    def test_ready_state_when_never_donated(self):
        response = self.client.get(self.url)
        self.assertContains(response, "You can donate now.")
        self.assertContains(response, "--ring-offset: 0.0")
        self.assertContains(response, "visible to matching requests")
        self.assertNotContains(response, "not being matched right now")

    def test_resting_state_counts_the_days_left(self):
        self.donor.last_donation_date = timezone.localdate() - timedelta(days=30)
        self.donor.save()
        response = self.client.get(self.url)
        self.assertContains(response, "You can donate again on")
        self.assertContains(response, "60")
        self.assertContains(response, "days left")
        self.assertContains(response, "resting until")
        self.assertContains(response, "You are in your resting period until")
        self.assertContains(response, "requests are hidden")
        expected = round(RING_LENGTH * (1 - 33 / 100), 2)   # 30 of 90 days done = 33%
        self.assertContains(response, f"--ring-offset: {expected}")

    def test_switched_off_donor_is_told_they_are_hidden(self):
        self.donor.is_available = False
        self.donor.save()
        response = self.client.get(self.url)
        self.assertContains(response, "Not available right now")
        self.assertContains(response, "hidden from matching")
        self.assertContains(response, "You are marked as unavailable, so requests are hidden")

    def test_shows_only_requests_this_donor_can_actually_help_with(self):
        rohri = make_location("Rohri", "Rohri City")
        someone = User.objects.create_user("family", "f@example.com", "x")
        make_request(someone, self.sukkur, blood_type="A+", patient_name="compatible A+")      # O+ can give to A+
        make_request(someone, self.sukkur, blood_type="O+", patient_name="compatible O+")
        make_request(someone, self.sukkur, blood_type="O-", patient_name="wrong type")         # O+ cannot give to O-
        make_request(someone, rohri, blood_type="A+", patient_name="other city")
        make_request(someone, self.sukkur, blood_type="A+", patient_name="expired",
                     expires_at=timezone.now() - timedelta(minutes=1))
        make_request(someone, self.sukkur, blood_type="A+", patient_name="fulfilled", status=STATUS_FULFILLED)
        make_request(self.donor.user, self.sukkur, blood_type="A+", patient_name="own request")
        names = {r.patient_name for r in self.client.get(self.url).context["matching_requests"]}
        self.assertEqual(names, {"compatible A+", "compatible O+"})

    def test_most_urgent_matching_request_comes_first(self):
        someone = User.objects.create_user("family", "f@example.com", "x")
        make_request(someone, self.sukkur, blood_type="A+", urgency=URGENCY_NORMAL, patient_name="normal")
        make_request(someone, self.sukkur, blood_type="A+", urgency=URGENCY_CRITICAL, patient_name="critical")
        first = self.client.get(self.url).context["matching_requests"][0]
        self.assertEqual(first.patient_name, "critical")

    def test_friendly_message_when_nothing_matches(self):
        self.assertContains(self.client.get(self.url), "No matching requests right now")


@FAST_HASHER
class AvailabilityToggleTests(TestCase):
    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Ali Raza", "O-", self.sukkur)
        self.client.force_login(self.donor.user)
        self.url = reverse("donors:toggle")

    def test_post_switches_availability_each_time(self):
        self.client.post(self.url)
        self.donor.refresh_from_db()
        self.assertFalse(self.donor.is_available)
        self.client.post(self.url)
        self.donor.refresh_from_db()
        self.assertTrue(self.donor.is_available)

    def test_normal_form_post_redirects_back_with_a_message(self):
        response = self.client.post(self.url, follow=True)
        self.assertRedirects(response, reverse("donors:profile"))
        self.assertContains(response, "You are now marked as not available.")

    def test_background_request_gets_json(self):
        response = self.client.post(self.url, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False})

    def test_a_plain_link_cannot_change_anything(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.donor.refresh_from_db()
        self.assertTrue(self.donor.is_available)

    def test_no_profile_yet(self):
        self.client.force_login(User.objects.create_user("newbie", "n@example.com", "x"))
        self.assertRedirects(self.client.post(self.url), reverse("donors:edit"), fetch_redirect_response=False)
        self.assertEqual(self.client.post(self.url, HTTP_ACCEPT="application/json").status_code, 404)

    def test_switching_off_really_removes_the_donor_from_matching(self):
        requester = User.objects.create_user("family", "f@example.com", "x")
        request = make_request(requester, self.sukkur, blood_type="A+")
        self.assertIn(self.donor, list(find_matching_donors(request)))
        self.client.post(self.url)
        self.assertNotIn(self.donor, list(find_matching_donors(request)))

    def test_only_the_signed_in_donors_own_profile_is_changed(self):
        stranger = make_donor("Stranger", "A+", self.sukkur)
        self.client.post(self.url)
        stranger.refresh_from_db()
        self.assertTrue(stranger.is_available)


@FAST_HASHER
class DonatedTodayTests(TestCase):
    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Ali Raza", "O-", self.sukkur)
        self.client.force_login(self.donor.user)
        self.url = reverse("donors:donated")
        # The button only works for a donor who has offered to help an open request.
        family = User.objects.create_user("needy_family", "nf@example.com", "x")
        self.offered_to = make_request(family, self.sukkur, blood_type="A+", patient_name="Offered Patient")
        DonorResponse.objects.create(request=self.offered_to, donor=self.donor)

    def test_records_today_and_starts_the_rest_period(self):
        response = self.client.post(self.url, follow=True)
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.last_donation_date, timezone.localdate())
        self.assertFalse(self.donor.is_eligible)
        self.assertEqual(self.donor.days_until_eligible, 90)
        self.assertContains(response, "Thank you for donating")

    def test_the_donor_stops_being_matched_straight_away(self):
        requester = User.objects.create_user("family", "f@example.com", "x")
        request = make_request(requester, self.sukkur, blood_type="A+")
        self.assertIn(self.donor, list(find_matching_donors(request)))
        self.client.post(self.url)
        self.assertNotIn(self.donor, list(find_matching_donors(request)))

    def test_a_plain_link_cannot_do_it(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.donor.refresh_from_db()
        self.assertIsNone(self.donor.last_donation_date)

    def test_no_profile_yet(self):
        self.client.force_login(User.objects.create_user("newbie", "n@example.com", "x"))
        self.assertRedirects(self.client.post(self.url), reverse("donors:edit"), fetch_redirect_response=False)

    def test_the_button_asks_for_confirmation_first(self):
        self.assertContains(self.client.get(reverse("donors:profile")), "data-confirm=")

    def test_posting_twice_in_one_day_does_not_move_the_date_or_error(self):
        self.client.post(self.url)
        self.donor.refresh_from_db()
        first_date = self.donor.last_donation_date
        response = self.client.post(self.url, follow=True)
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.last_donation_date, first_date)
        self.assertContains(response, "already recorded")

    def test_button_is_shown_before_todays_donation_is_recorded(self):
        html = self.client.get(reverse("donors:profile")).content.decode()
        self.assertIn("I donated today", html)

    def test_without_an_offer_the_button_is_hidden_and_the_post_is_refused(self):
        DonorResponse.objects.all().delete()
        html = self.client.get(reverse("donors:profile")).content.decode()
        self.assertNotIn(">I donated today<", html)
        self.assertNotIn(self.url, html)
        self.assertIn("After you offer to help a request", html)
        response = self.client.post(self.url, follow=True)
        self.donor.refresh_from_db()
        self.assertIsNone(self.donor.last_donation_date)
        self.assertContains(response, "after you offer to help a request")

    def test_a_resting_donor_cannot_record_another_donation(self):
        self.donor.last_donation_date = timezone.localdate() - timedelta(days=20)
        self.donor.save()
        self.client.post(self.url)
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.last_donation_date, timezone.localdate() - timedelta(days=20))

    def test_button_is_hidden_after_todays_donation_is_recorded(self):
        self.client.post(self.url)
        html = self.client.get(reverse("donors:profile")).content.decode()
        self.assertNotIn("I donated today", html)
        self.assertIn("Donation recorded for today", html)


@FAST_HASHER
class LinkTests(TestCase):
    def test_signed_in_people_get_a_donor_dashboard_link(self):
        self.client.force_login(User.objects.create_user("ali", "a@example.com", "x"))
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn(f'href="{reverse("donors:profile")}"', html)
        self.assertNotIn("?next=" + reverse("donors:edit"), html)

    def test_admin_lists_the_consent_column(self):
        make_donor("Ali Raza", "O-", make_location("Sukkur", "Military Road"))
        self.client.force_login(User.objects.create_superuser("boss", "b@example.com", "x"))
        self.assertContains(self.client.get("/admin/donors/donorprofile/"), "column-phone_consent")


@FAST_HASHER
class SearchViewTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.viewer = User.objects.create_user("viewer", "v@example.com", "x")

    def test_search_needs_a_login(self):
        response = self.client.get(reverse("donors:search"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_no_query_shows_no_results_yet(self):
        make_donor("Ali Raza", "O-", self.location)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("donors:search"))
        self.assertEqual(list(response.context["donors"]), [])
        self.assertFalse(response.context["has_searched"])

    def test_blood_type_query_returns_compatible_donors(self):
        make_donor("Compatible", "O-", self.location)
        make_donor("Incompatible", "B+", self.location)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("donors:search"), {"blood_type": "A+"})
        names = [d.full_name for d in response.context["donors"]]
        self.assertEqual(names, ["Compatible"])

    def test_phone_number_is_never_shown_on_the_general_search_page(self):
        make_donor("Ali Raza", "O-", self.location, user=User.objects.create_user("ali", "a@x.com", "x"))
        self.client.force_login(self.viewer)
        html = self.client.get(reverse("donors:search"), {"city": "Sukkur"}).content.decode()
        self.assertIn("Ali Raza", html)
        self.assertNotIn("03001234567", html)  # the phone number make_donor() sets by default


@FAST_HASHER
class DonorSearchDiscoverabilityTests(TestCase):
    """Donor search is kept off the main nav on purpose: a patient who sees it tends
    to browse donors instead of posting a request, which skips hospital verification.
    It must still be reachable for donors, and the page itself must keep working."""

    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.user = User.objects.create_user("some_donor", "d@example.com", "x")

    def test_the_main_nav_does_not_offer_donor_search(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertNotIn(f'href="{reverse("donors:search")}"', html)

    def test_an_anonymous_visitor_is_not_offered_donor_search_either(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertNotIn(f'href="{reverse("donors:search")}"', html)

    def test_a_registered_donor_can_still_reach_it_from_their_dashboard(self):
        make_donor("Some Donor", "O-", self.location, user=self.user)
        self.client.force_login(self.user)
        # Request blood in the panel opens My requests, which has a Find donors tab
        html = self.client.get(reverse("blood_requests:mine")).content.decode()
        self.assertIn(f'href="{reverse("donors:search")}"', html)

    def test_the_search_page_itself_still_works(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("donors:search")).status_code, 200)



class DashboardLayoutTests(TestCase):
    """The side panel and the numbers on the donor dashboard."""

    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(self.donor.user)
        self.url = reverse("donors:profile")

    def test_greeting_changes_with_the_hour(self):
        from donors.views import greeting_for
        for hour, expected in ((0, "Good morning"), (11, "Good morning"), (12, "Good afternoon"),
                               (16, "Good afternoon"), (17, "Good evening"), (23, "Good evening")):
            with self.subTest(hour=hour):
                self.assertEqual(greeting_for(hour), expected)

    def test_side_panel_links_to_the_sections_that_exist(self):
        html = self.client.get(self.url).content.decode()
        # The panel is shared by every dashboard page, so its links carry the
        # page address. It links to two sections (requests and details); the
        # availability switch has no side link but its card keeps its id.
        self.assertIn(f'href="{reverse("core:dashboard")}"', html)
        for tab in ("requests", "details"):
            with self.subTest(tab=tab):
                self.assertIn(f'href="{self.url}?tab={tab}"', html)
                page = self.client.get(f"{self.url}?tab={tab}").content.decode()
                self.assertIn(f'id="{tab}"', page)
        self.assertNotIn(f'href="{self.url}#availability"', html)
        self.assertIn('id="availability"', html)

    def test_each_side_link_opens_only_its_own_page(self):
        requests_page = self.client.get(f"{self.url}?tab=requests").content.decode()
        self.assertIn("Requests you can help with", requests_page)
        self.assertNotIn('id="details"', requests_page)
        self.assertNotIn("Mobile number", requests_page)
        details_page = self.client.get(f"{self.url}?tab=details").content.decode()
        self.assertIn("Your details", details_page)
        self.assertIn("Mobile number", details_page)
        self.assertNotIn('id="requests"', details_page)
        self.assertNotIn("Requests you can help with", details_page)

    def test_the_open_page_is_marked_in_the_side_panel(self):
        requests_page = self.client.get(f"{self.url}?tab=requests").content.decode()
        details_page = self.client.get(f"{self.url}?tab=details").content.decode()
        mark = 'aria-current="page"'
        # Match the links themselves (href="...?tab=..."), not the language box, which
        # also carries the current address in a hidden field.
        def link(page, tab):
            return page[re.search(r'href="[^"]*\?tab=' + tab + '"', page).start():]

        self.assertIn(mark, link(requests_page, "requests")[:200])
        self.assertIn(mark, link(details_page, "details")[:200])
        self.assertNotIn(mark, link(requests_page, "details")[:160])

    def test_no_tab_or_an_unknown_tab_shows_the_requests(self):
        for url in (self.url, f"{self.url}?tab=nonsense"):
            with self.subTest(url=url):
                page = self.client.get(url).content.decode()
                self.assertIn("Requests you can help with", page)
                self.assertNotIn("Mobile number", page)

    def test_saving_the_profile_returns_to_the_details_page(self):
        data = {"full_name": "Ali Raza", "blood_type": "O+", "phone": "03001234567", "location": self.donor.location_id,
                "is_available": "on", "phone_consent": "on", "eligibility_declared": "on",
                "cnic": "4210112345671", "weight_kg": "68", "height_cm": "172", "conditions": ["none"],
                "never_donated": "on"}
        response = self.client.post(reverse("donors:edit"), data)
        self.assertRedirects(response, f"{self.url}?tab=details")

    def test_the_details_page_shows_the_account_name_and_username(self):
        page = self.client.get(f"{self.url}?tab=details").content.decode()
        self.assertIn("Username", page)
        self.assertIn(self.donor.user.get_username(), page)

    def test_side_panel_still_reaches_the_other_donor_pages(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn(reverse("donors:edit"), html)
        self.assertIn(reverse("blood_requests:mine"), html)
        self.assertIn(reverse("blood_requests:list"), html)

    def test_request_count_is_the_whole_count_not_just_the_rows_shown(self):
        owner = User.objects.create_user("owner", "o@example.com", "x")
        hospital = make_hospital("Civil Hospital", self.sukkur)
        # More compatible open requests than the dashboard lists.
        for _ in range(DASHBOARD_REQUESTS + 2):
            make_request(owner, self.sukkur, hospital=hospital, blood_type="O+", is_verified=True)
        response = self.client.get(self.url)
        self.assertEqual(response.context["matching_total"], DASHBOARD_REQUESTS + 2)
        self.assertEqual(len(response.context["matching_requests"]), DASHBOARD_REQUESTS)

    def test_summary_shows_what_is_recorded_and_invents_nothing(self):
        html = self.client.get(self.url + "?tab=details").content.decode()
        # No donation recorded yet, so no total and no "lives impacted".
        self.assertIn("Never donated", html)
        self.assertNotIn("Lives impacted", html)
        self.assertNotIn("Total donations", html)

    def test_a_donor_is_told_how_many_blood_types_they_can_give_to(self):
        # O+ red cells can go to O+, A+, B+ and AB+.
        response = self.client.get(self.url + "?tab=details")
        self.assertEqual(response.context["can_give_to"], 4)
        self.assertContains(response, "can give to 4 types")


@FAST_HASHER
class DashboardBannerTests(TestCase):
    """The availability card at the top of the donor dashboard says one honest thing about the donor."""

    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.donor = make_donor("Ali Raza", "O+", self.sukkur)
        self.client.force_login(self.donor.user)
        self.url = reverse("donors:profile")

    def test_ready_donor_gets_the_ready_banner(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("availc is-ready", html)
        self.assertIn("<h2>Ready to donate</h2>", html)

    def test_resting_donor_gets_the_resting_banner_with_the_days(self):
        self.donor.last_donation_date = timezone.localdate() - timedelta(days=30)
        self.donor.save()
        html = self.client.get(self.url).content.decode()
        self.assertIn("availc is-rest", html)
        self.assertIn("Resting for 60 more days", html)
        self.assertNotIn("<h2>Ready to donate</h2>", html)

    def test_switched_off_donor_gets_the_paused_banner(self):
        self.donor.is_available = False
        self.donor.save()
        html = self.client.get(self.url).content.decode()
        self.assertIn("availc is-paused", html)
        self.assertIn("<h2>Not available</h2>", html)
        self.assertNotIn("<h2>Ready to donate</h2>", html)

    def test_the_switch_and_the_donated_button_live_in_the_availability_card(self):
        family = User.objects.create_user("offer_family", "of@example.com", "x")
        DonorResponse.objects.create(request=make_request(family, self.sukkur, blood_type="A+"), donor=self.donor)
        html = self.client.get(self.url).content.decode()
        card = html[html.index('id="availability"'):html.index('class="panel" id=')]
        self.assertIn(reverse("donors:toggle"), card)
        self.assertIn(reverse("donors:donated"), card)
        self.assertIn('role="switch"', card)

    def test_matching_rows_carry_their_urgency_for_the_edge_colour(self):
        someone = User.objects.create_user("family", "f@example.com", "x")
        make_request(someone, self.sukkur, blood_type="A+", urgency=URGENCY_CRITICAL, patient_name="critical")
        html = self.client.get(self.url).content.decode()
        self.assertIn("activity-row is-critical", html)

