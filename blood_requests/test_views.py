"""Tests for the request pages: board, detail, post, mine, fulfil, respond."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest, DonorResponse, Report
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from core.constants import STATUS_FULFILLED

User = get_user_model()

# Real password hashing is deliberately slow; these tests are about request pages, so use a fast hasher.
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def request_form_data(hospital, **overrides):
    data = {
        "patient_name": "Ahmed Khan", "blood_type": "O-", "units_needed": "1",
        "urgency": "Normal", "hospital": str(hospital.pk),
        "contact_phone": "03001234567", "note": "", "cnic": "4210112345671",
    }
    data.update(overrides)
    return data


@FAST_HASHER
class AccessTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")

    def test_pages_that_need_a_login_redirect_anonymous_users(self):
        for name, method in (
            ("blood_requests:new", "get"), ("blood_requests:mine", "get"),
        ):
            with self.subTest(page=name, method=method):
                response = getattr(self.client, method)(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_fulfil_and_respond_need_a_login(self):
        req = make_request(User.objects.create_user(username="requester"), self.location)
        for name in ("blood_requests:fulfil", "blood_requests:respond"):
            with self.subTest(page=name):
                response = self.client.post(reverse(name, args=[req.pk]))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_list_and_detail_are_public(self):
        req = make_request(User.objects.create_user(username="requester"), self.location)
        self.assertEqual(self.client.get(reverse("blood_requests:list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("blood_requests:detail", args=[req.pk])).status_code, 200)

    def test_only_get_and_post_fulfil_and_respond_reject_get(self):
        req = make_request(User.objects.create_user(username="requester", password="x"), self.location)
        self.client.force_login(User.objects.create_user(username="someone", password="x"))
        for name in ("blood_requests:fulfil", "blood_requests:respond"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=[req.pk]))
                self.assertEqual(response.status_code, 405)


@FAST_HASHER
class ContactVisibilityTests(TestCase):
    def test_contact_phone_is_hidden_from_anonymous_visitors(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="requester"), location, contact_phone="03009998888")
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertNotIn("03009998888", html)

    def test_contact_phone_is_shown_to_the_person_who_posted_the_request(self):
        location = make_location("Sukkur", "Military Road")
        owner = User.objects.create_user(username="requester", password="x")
        req = make_request(owner, location, contact_phone="03009998888")
        self.client.force_login(owner)
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertIn("03009998888", html)

    def test_contact_phone_is_hidden_from_an_ordinary_signed_in_user(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="requester"), location, contact_phone="03009998888")
        self.client.force_login(User.objects.create_user(username="viewer", password="x"))
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertNotIn("03009998888", html)

    def test_report_modal_renders_for_a_signed_in_visitor(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="requester"), location)
        self.client.force_login(User.objects.create_user(username="viewer", password="x"))
        response = self.client.get(reverse("blood_requests:detail", args=[req.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "reportModal")
        self.assertContains(response, "Fake or hoax")  # a real reason choice actually rendered

    def test_report_link_is_hidden_from_anonymous_visitors(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="requester"), location)
        response = self.client.get(reverse("blood_requests:detail", args=[req.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "reportModal")


@FAST_HASHER
class PostRequestTests(TestCase):
    def test_the_form_page_itself_renders_and_lists_hospitals_grouped_by_city(self):
        location = make_location("Sukkur", "Military Road")
        hospital = make_hospital("Civil Hospital", location)
        self.client.force_login(User.objects.create_user(username="requester", password="x"))
        response = self.client.get(reverse("blood_requests:new"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Civil Hospital")
        self.assertContains(response, str(hospital.pk))

    def test_valid_form_creates_a_request_owned_by_the_signed_in_user(self):
        location = make_location("Sukkur", "Military Road")
        hospital = make_hospital("Civil Hospital", location)
        user = User.objects.create_user(username="requester", password="x")
        self.client.force_login(user)
        response = self.client.post(reverse("blood_requests:new"), request_form_data(hospital))
        self.assertEqual(BloodRequest.objects.count(), 1)
        req = BloodRequest.objects.get()
        self.assertEqual(req.requester, user)
        self.assertEqual(req.hospital, hospital)
        self.assertEqual(req.location, location)  # derived from the hospital, not asked separately
        self.assertFalse(req.is_verified)  # not visible to donors until the hospital verifies it
        self.assertRedirects(response, reverse("blood_requests:detail", args=[req.pk]))

    def test_requester_cannot_be_spoofed_via_post_data(self):
        location = make_location("Sukkur", "Military Road")
        hospital = make_hospital("Civil Hospital", location)
        user = User.objects.create_user(username="requester", password="x")
        other = User.objects.create_user(username="other", password="x")
        self.client.force_login(user)
        self.client.post(reverse("blood_requests:new"), request_form_data(hospital, requester=other.pk))
        self.assertEqual(BloodRequest.objects.get().requester, user)


@FAST_HASHER
class FulfilTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location)

    def test_owner_can_mark_their_request_fulfilled(self):
        DonorResponse.objects.create(request=self.req, donor=make_donor("Helper", "O+", self.location))
        self.client.force_login(self.owner)
        self.client.post(reverse("blood_requests:fulfil", args=[self.req.pk]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_FULFILLED)
        self.assertIsNotNone(self.req.fulfilled_at)

    def test_a_different_user_gets_403(self):
        self.client.force_login(User.objects.create_user(username="stranger", password="x"))
        response = self.client.post(reverse("blood_requests:fulfil", args=[self.req.pk]))
        self.assertEqual(response.status_code, 403)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "Pending")

    def test_staff_can_mark_someone_elses_request_fulfilled(self):
        self.client.force_login(User.objects.create_user(username="admin", password="x", is_staff=True))
        self.client.post(reverse("blood_requests:fulfil", args=[self.req.pk]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_FULFILLED)


@FAST_HASHER
class RespondTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location, blood_type="O-")

    def test_donor_offering_help_creates_a_response(self):
        donor_user = User.objects.create_user(username="donor", password="x")
        make_donor("Donor One", "O-", self.location, user=donor_user)
        self.client.force_login(donor_user)
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertEqual(DonorResponse.objects.filter(request=self.req).count(), 1)

    def test_responding_twice_does_not_error_or_duplicate(self):
        donor_user = User.objects.create_user(username="donor", password="x")
        make_donor("Donor One", "O-", self.location, user=donor_user)
        self.client.force_login(donor_user)
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertEqual(DonorResponse.objects.filter(request=self.req).count(), 1)

    def test_a_user_with_no_donor_profile_is_sent_to_register(self):
        self.client.force_login(User.objects.create_user(username="no_profile", password="x"))
        response = self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertRedirects(response, reverse("donors:edit"))
        self.assertEqual(DonorResponse.objects.count(), 0)

    def test_the_owner_cannot_respond_to_their_own_request(self):
        make_donor("Owner as donor", "O-", self.location, user=self.owner)
        self.client.force_login(self.owner)
        response = self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertEqual(response.status_code, 403)


@FAST_HASHER
class ListFilterTests(TestCase):
    def test_blood_type_filter_narrows_results(self):
        location = make_location("Sukkur", "Military Road")
        requester = User.objects.create_user(username="requester")
        make_request(requester, location, blood_type="O-")
        make_request(requester, location, blood_type="A+")
        html = self.client.get(reverse("blood_requests:list"), {"blood_type": "O-"}).content.decode()
        self.assertIn("O", html)
        response = self.client.get(reverse("blood_requests:list"), {"blood_type": "O-"})
        self.assertEqual(len(response.context["requests"]), 1)

    def test_city_filter_narrows_results(self):
        requester = User.objects.create_user(username="requester")
        make_request(requester, make_location("Sukkur", "Military Road"))
        make_request(requester, make_location("Rohri", "Rohri City"))
        response = self.client.get(reverse("blood_requests:list"), {"city": "Rohri"})
        self.assertEqual(len(response.context["requests"]), 1)
        self.assertEqual(response.context["requests"][0].location.city, "Rohri")


@FAST_HASHER
class UrgencyFilterTests(TestCase):
    def setUp(self):
        self.url = reverse("blood_requests:list")
        location = make_location("Sukkur", "Military Road")
        requester = User.objects.create_user(username="requester")
        make_request(requester, location, blood_type="O-", urgency="Critical")
        make_request(requester, location, blood_type="O-", urgency="Critical")
        make_request(requester, location, blood_type="A+", urgency="Urgent")
        make_request(requester, location, blood_type="A+", urgency="Normal")

    def test_urgency_narrows_the_list(self):
        response = self.client.get(self.url, {"urgency": "Critical"})
        self.assertEqual(len(response.context["requests"]), 2)
        self.assertEqual({r.urgency for r in response.context["requests"]}, {"Critical"})
        self.assertEqual(response.context["selected_urgency"], "Critical")
        self.assertTrue(response.context["has_filters"])

    def test_an_unknown_urgency_is_ignored(self):
        response = self.client.get(self.url, {"urgency": "Whatever"})
        self.assertEqual(len(response.context["requests"]), 4)
        self.assertEqual(response.context["selected_urgency"], "")
        self.assertFalse(response.context["has_filters"])

    def test_tiles_count_what_each_urgency_would_show_and_ignore_the_urgency_filter(self):
        response = self.client.get(self.url, {"urgency": "Normal"})
        counts = {level: count for level, count, _ in response.context["urgency_tiles"]}
        self.assertEqual(counts, {"Critical": 2, "Urgent": 1, "Normal": 1})

    def test_tiles_follow_the_blood_type_filter(self):
        response = self.client.get(self.url, {"blood_type": "A+"})
        counts = {level: count for level, count, _ in response.context["urgency_tiles"]}
        self.assertEqual(counts, {"Critical": 0, "Urgent": 1, "Normal": 1})

    def test_tile_links_keep_other_filters_and_the_active_tile_clears_itself(self):
        response = self.client.get(self.url, {"blood_type": "O-", "city": "Sukkur", "urgency": "Critical"})
        links = {level: href for level, _, href in response.context["urgency_tiles"]}
        self.assertIn("blood_type=O-", links["Urgent"])
        self.assertIn("city=Sukkur", links["Urgent"])
        self.assertIn("urgency=Urgent", links["Urgent"])
        self.assertNotIn("urgency", links["Critical"])
        self.assertIn("blood_type=O-", links["Critical"])

    def test_sort_links_keep_the_urgency_filter(self):
        response = self.client.get(self.url, {"urgency": "Urgent"})
        for _, _, href in response.context["sort_links"]:
            self.assertIn("urgency=Urgent", href)

    def test_the_page_has_the_tiles_and_eight_blood_type_chips(self):
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('class="utile '), 3)
        self.assertEqual(html.count('name="blood_type"'), 9)  # eight types plus "Any type"
        self.assertNotIn("not by distance", html)

    def test_apply_keeps_the_urgency_filter(self):
        html = self.client.get(self.url, {"urgency": "Urgent"}).content.decode()
        self.assertIn('<input type="hidden" name="urgency" value="Urgent">', html)


@FAST_HASHER
class RequestPageTimelineTests(TestCase):
    def test_the_detail_page_reports_how_far_the_timeline_fills(self):
        location = make_location("Sukkur", "Military Road")
        requester = User.objects.create_user(username="requester")
        req = make_request(requester, location)
        response = self.client.get(reverse("blood_requests:detail", args=[req.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.context["track_fill"], range(0, 101))
        self.assertContains(response, "--fill: %d" % response.context["track_fill"])
        self.assertContains(response, 'class="facts"')


@FAST_HASHER
class MineTests(TestCase):
    def test_shows_only_the_signed_in_users_own_requests(self):
        location = make_location("Sukkur", "Military Road")
        mine = User.objects.create_user(username="mine", password="x")
        make_request(mine, location)
        make_request(User.objects.create_user(username="someone_else"), location)
        self.client.force_login(mine)
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertEqual(len(response.context["requests"]), 1)
        self.assertEqual(response.context["requests"][0].requester, mine)


@FAST_HASHER
class DailyLimitViewTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.user = User.objects.create_user(username="requester", password="x")
        self.client.force_login(self.user)

    def test_the_4th_request_today_is_blocked_with_a_clear_message(self):
        from core.constants import MAX_REQUESTS_PER_USER_PER_DAY
        for _ in range(MAX_REQUESTS_PER_USER_PER_DAY):
            make_request(self.user, self.location, hospital=self.hospital)

        response = self.client.post(
            reverse("blood_requests:new"), request_form_data(self.hospital), follow=True,
        )
        self.assertContains(response, "You have reached your daily limit of 3 blood requests. Please try again tomorrow.")
        self.assertEqual(BloodRequest.objects.filter(requester=self.user).count(), MAX_REQUESTS_PER_USER_PER_DAY)

    def test_the_blocked_page_redirects_to_my_requests(self):
        from core.constants import MAX_REQUESTS_PER_USER_PER_DAY
        for _ in range(MAX_REQUESTS_PER_USER_PER_DAY):
            make_request(self.user, self.location, hospital=self.hospital)

        response = self.client.get(reverse("blood_requests:new"))
        self.assertRedirects(response, reverse("blood_requests:mine"))

    def test_a_different_user_is_not_affected_by_someone_elses_limit(self):
        from core.constants import MAX_REQUESTS_PER_USER_PER_DAY
        for _ in range(MAX_REQUESTS_PER_USER_PER_DAY):
            make_request(self.user, self.location, hospital=self.hospital)

        other = User.objects.create_user(username="other", password="x")
        self.client.force_login(other)
        response = self.client.get(reverse("blood_requests:new"))
        self.assertEqual(response.status_code, 200)  # not blocked


@FAST_HASHER
class MatchBannerTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")

    def test_banner_shows_for_the_owner_when_verified_with_a_compatible_donor(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="O-", is_verified=True)
        make_donor("Donor One", "O-", self.location)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("blood_requests:detail", args=[req.pk]))
        self.assertContains(response, "match-banner")
        self.assertContains(response, "Match found")

    def test_banner_hidden_when_not_yet_verified_even_with_a_matching_donor(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="O-", is_verified=False)
        make_donor("Donor One", "O-", self.location)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("blood_requests:detail", args=[req.pk]))
        self.assertNotContains(response, "match-banner")

    def test_banner_hidden_when_verified_but_no_matching_donor(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="O-", is_verified=True)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("blood_requests:detail", args=[req.pk]))
        self.assertNotContains(response, "match-banner")

    def test_banner_hidden_from_a_visitor_who_is_not_the_owner(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="O-", is_verified=True)
        make_donor("Donor One", "O-", self.location)
        self.client.force_login(User.objects.create_user(username="someone_else", password="x"))
        response = self.client.get(reverse("blood_requests:detail", args=[req.pk]))
        self.assertNotContains(response, "match-banner")


@FAST_HASHER
class ReportViewTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location, hospital=self.hospital)

    def test_report_needs_a_login(self):
        response = self.client.post(reverse("blood_requests:report", args=[self.req.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_report_rejects_get(self):
        self.client.force_login(User.objects.create_user(username="reporter", password="x"))
        response = self.client.get(reverse("blood_requests:report", args=[self.req.pk]))
        self.assertEqual(response.status_code, 405)

    def test_a_valid_report_is_recorded(self):
        self.client.force_login(User.objects.create_user(username="reporter", password="x"))
        self.client.post(reverse("blood_requests:report", args=[self.req.pk]), {
            "reason": "Fake or hoax", "details": "This looks suspicious",
        })
        self.assertEqual(Report.objects.filter(request=self.req).count(), 1)
        report = Report.objects.get(request=self.req)
        self.assertEqual(report.reason, "Fake or hoax")
        self.assertEqual(report.details, "This looks suspicious")

    def test_reporting_twice_does_not_error_or_duplicate(self):
        reporter = User.objects.create_user(username="reporter", password="x")
        self.client.force_login(reporter)
        self.client.post(reverse("blood_requests:report", args=[self.req.pk]), {"reason": "Fake or hoax"})
        self.client.post(reverse("blood_requests:report", args=[self.req.pk]), {"reason": "Spam or advertising"})
        self.assertEqual(Report.objects.filter(request=self.req, reporter=reporter).count(), 1)

    def test_missing_reason_shows_an_error_and_does_not_create_a_report(self):
        self.client.force_login(User.objects.create_user(username="reporter", password="x"))
        self.client.post(reverse("blood_requests:report", args=[self.req.pk]), {"reason": ""}, follow=True)
        self.assertEqual(Report.objects.count(), 0)

    def test_the_owner_can_report_their_own_request_too(self):
        # Not restricted - simplest correct behaviour per the spec, which doesn't
        # single out the owner.
        self.client.force_login(self.owner)
        self.client.post(reverse("blood_requests:report", args=[self.req.pk]), {"reason": "Other"})
        self.assertEqual(Report.objects.filter(request=self.req, reporter=self.owner).count(), 1)


@FAST_HASHER
class MinePageContentTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.me = User.objects.create_user(username="requester", password="x")
        self.client.force_login(self.me)

    def test_empty_state_and_heading_when_nothing_posted(self):
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertContains(response, 'class="dpage-title">Request blood</h1>')
        self.assertContains(response, "You haven't posted a request")
        self.assertContains(response, "3 of 3 requests remaining today")
        self.assertEqual(response.context["total_count"], 0)

    def test_counts_open_and_fulfilled_and_offers(self):
        open_request = make_request(self.me, self.location)
        done = make_request(self.me, self.location)
        done.status = STATUS_FULFILLED
        done.fulfilled_at = timezone.now()
        done.save(update_fields=["status", "fulfilled_at"])
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertEqual(response.context["open_count"], 1)
        self.assertEqual(response.context["fulfilled_count"], 1)
        self.assertEqual(response.context["total_count"], 2)
        self.assertContains(response, "no offers yet")
        rows = {row["req"].pk: row for row in response.context["rows"]}
        self.assertEqual(len(rows[open_request.pk]["tracking"]), 4)

    def test_mark_fulfilled_is_switched_off_until_a_donor_offers(self):
        waiting = make_request(self.me, self.location)
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertNotContains(response, reverse("blood_requests:fulfil", args=[waiting.pk]))
        self.assertContains(response, "Available once a donor offers to help")
        self.assertContains(response, "disabled")
        DonorResponse.objects.create(request=waiting, donor=make_donor("Helper", "O+", self.location))
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertContains(response, reverse("blood_requests:fulfil", args=[waiting.pk]))
        self.assertNotContains(response, "Available once a donor offers to help")

    def test_the_detail_page_switches_the_button_on_after_an_offer(self):
        waiting = make_request(self.me, self.location)
        url = reverse("blood_requests:detail", args=[waiting.pk])
        self.assertContains(self.client.get(url), "Available once a donor offers to help")
        self.assertNotContains(self.client.get(url), reverse("blood_requests:fulfil", args=[waiting.pk]))
        DonorResponse.objects.create(request=waiting, donor=make_donor("Helper", "O+", self.location))
        self.assertContains(self.client.get(url), reverse("blood_requests:fulfil", args=[waiting.pk]))

    def test_only_open_requests_offer_mark_fulfilled(self):
        open_request = make_request(self.me, self.location)
        DonorResponse.objects.create(request=open_request, donor=make_donor("Helper", "O+", self.location))
        done = make_request(self.me, self.location)
        done.status = STATUS_FULFILLED
        done.fulfilled_at = timezone.now()
        done.save(update_fields=["status", "fulfilled_at"])
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertContains(response, reverse("blood_requests:fulfil", args=[open_request.pk]))
        self.assertNotContains(response, reverse("blood_requests:fulfil", args=[done.pk]))

    def test_each_card_carries_the_fill_for_its_timeline(self):
        make_request(self.me, self.location)
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertContains(response, 'class="tl tl-mini"')
        self.assertContains(response, "--fill:")
