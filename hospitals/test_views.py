"""Tests for the hospital dashboard: who can see it, who can verify what."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.models import BloodRequest
from blood_requests.selectors import open_requests
from blood_requests.tests import make_hospital, make_location, make_request
from hospitals.models import HospitalAccount

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def make_hospital_account(username, hospital, staff_name="Dr. Test"):
    user = User.objects.create_user(username=username, password="x")
    return HospitalAccount.objects.create(user=user, hospital=hospital, staff_name=staff_name)


@FAST_HASHER
class NavbarLinkTests(TestCase):
    def test_hospital_account_sees_a_dashboard_link_in_the_navbar(self):
        location = make_location("Sukkur", "Military Road")
        hospital = make_hospital("Civil Hospital", location)
        account = make_hospital_account("hospital_staff", hospital)
        self.client.force_login(account.user)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn(f'href="{reverse("hospitals:dashboard")}"', html)

    def test_a_regular_user_does_not_see_a_hospital_dashboard_link(self):
        self.client.force_login(User.objects.create_user(username="regular", password="x"))
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertNotIn(f'href="{reverse("hospitals:dashboard")}"', html)


@FAST_HASHER
class HospitalAccountSeesOnlyItsOwnToolsTests(TestCase):
    """A hospital login is a single-purpose institutional account: it verifies
    requests. It shouldn't be shown donor or patient options as if it were a person."""

    # Links that only make sense for a person who donates or needs blood.
    PERSONAL_LINKS = (
        "donors:profile", "donors:edit", "blood_requests:mine", "blood_requests:new",
    )

    def _html_as(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("core:home")).content.decode()

    def test_hospital_account_is_not_shown_donor_or_patient_links(self):
        location = make_location("Sukkur", "Military Road")
        account = make_hospital_account("hospital_staff", make_hospital("Civil Hospital", location))
        html = self._html_as(account.user)
        for name in self.PERSONAL_LINKS:
            with self.subTest(link=name):
                self.assertNotIn(f'href="{reverse(name)}"', html)
        # Check the buttons themselves (">Label</a>"), not the words: "Post a request"
        # also appears in ordinary explanatory text, which is fine to show.
        for label in ("Become a donor", "I need blood", "Post a request", "Request blood"):
            with self.subTest(button=label):
                self.assertNotIn(f">{label}</a>", html)
        # The whole closing banner is aimed at donors/patients, so it's hidden too
        # rather than left as a headline with nothing to click.
        self.assertNotIn("data-home-cta", html)

    def test_hospital_account_still_gets_its_own_dashboard_link(self):
        location = make_location("Sukkur", "Military Road")
        account = make_hospital_account("hospital_staff", make_hospital("Civil Hospital", location))
        self.assertIn(f'href="{reverse("hospitals:dashboard")}"', self._html_as(account.user))

    def test_a_regular_signed_in_user_still_sees_the_donor_and_patient_options(self):
        html = self._html_as(User.objects.create_user(username="regular", password="x"))
        for name in ("core:dashboard", "blood_requests:new"):
            with self.subTest(link=name):
                self.assertIn(f'href="{reverse(name)}"', html)
        self.assertIn("Become a donor", html)
        self.assertIn("I need blood", html)
        self.assertIn("data-home-cta", html)

    def test_an_anonymous_visitor_still_sees_the_calls_to_action(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("Become a donor", html)
        self.assertIn("I need blood", html)
        self.assertIn(f'href="{reverse("blood_requests:new")}"', html)


@FAST_HASHER
class DashboardAccessTests(TestCase):
    def test_dashboard_needs_a_login(self):
        response = self.client.get(reverse("hospitals:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_a_user_with_no_hospital_account_is_redirected_home(self):
        self.client.force_login(User.objects.create_user(username="nobody", password="x"))
        response = self.client.get(reverse("hospitals:dashboard"))
        self.assertRedirects(response, reverse("core:home"))

    def test_donor_or_requester_accounts_cannot_see_a_hospital_dashboard(self):
        # A donor/requester is a completely ordinary User with no HospitalAccount -
        # same redirect as the "nobody" case above, just checked against a realistic account.
        location = make_location("Sukkur", "Military Road")
        make_hospital("Civil Hospital", location)
        self.client.force_login(User.objects.create_user(username="regular_donor", password="x"))
        response = self.client.get(reverse("hospitals:dashboard"))
        self.assertRedirects(response, reverse("core:home"))


@FAST_HASHER
class DashboardContentTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.other_hospital = make_hospital("Al-Khidmat Blood Bank", self.location)
        self.account = make_hospital_account("hospital_staff", self.hospital)
        self.requester = User.objects.create_user(username="requester", password="x")

    def test_shows_only_this_hospitals_unverified_pending_requests(self):
        mine_pending = make_request(self.requester, self.location, hospital=self.hospital, is_verified=False)
        make_request(self.requester, self.location, hospital=self.hospital, is_verified=True)  # already verified
        make_request(self.requester, self.location, hospital=self.other_hospital, is_verified=False)  # different hospital

        self.client.force_login(self.account.user)
        response = self.client.get(reverse("hospitals:dashboard"))
        self.assertEqual(list(response.context["pending"]), [mine_pending])

    def test_recently_verified_shows_this_hospitals_verified_requests(self):
        verified = make_request(self.requester, self.location, hospital=self.hospital, is_verified=True)
        self.client.force_login(self.account.user)
        response = self.client.get(reverse("hospitals:dashboard"))
        self.assertIn(verified, list(response.context["recently_verified"]))

    def test_a_staff_members_own_pending_request_is_kept_separate_from_the_verify_queue(self):
        own_request = make_request(
            self.account.user, self.location, hospital=self.hospital, is_verified=False,
        )
        someone_elses = make_request(self.requester, self.location, hospital=self.hospital, is_verified=False)

        self.client.force_login(self.account.user)
        response = self.client.get(reverse("hospitals:dashboard"))
        self.assertEqual(list(response.context["pending"]), [someone_elses])
        self.assertEqual(list(response.context["own_pending"]), [own_request])


@FAST_HASHER
class VerifyActionTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.other_hospital = make_hospital("Al-Khidmat Blood Bank", self.location)
        self.account = make_hospital_account("hospital_staff", self.hospital)
        self.requester = User.objects.create_user(username="requester", password="x")
        self.request_obj = make_request(
            self.requester, self.location, hospital=self.hospital, is_verified=False,
        )

    def test_verify_needs_a_login(self):
        response = self.client.post(reverse("hospitals:verify", args=[self.request_obj.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_verify_rejects_get(self):
        self.client.force_login(self.account.user)
        response = self.client.get(reverse("hospitals:verify", args=[self.request_obj.pk]))
        self.assertEqual(response.status_code, 405)

    def test_the_right_hospital_can_verify_its_own_request(self):
        self.client.force_login(self.account.user)
        self.client.post(reverse("hospitals:verify", args=[self.request_obj.pk]))
        self.request_obj.refresh_from_db()
        self.assertTrue(self.request_obj.is_verified)
        self.assertEqual(self.request_obj.verified_by, self.account.user)
        self.assertIsNotNone(self.request_obj.verified_at)

    def test_a_different_hospital_cannot_verify_someone_elses_request(self):
        other_account = make_hospital_account("other_hospital_staff", self.other_hospital)
        self.client.force_login(other_account.user)
        response = self.client.post(reverse("hospitals:verify", args=[self.request_obj.pk]))
        self.assertEqual(response.status_code, 403)
        self.request_obj.refresh_from_db()
        self.assertFalse(self.request_obj.is_verified)

    def test_a_donor_or_requester_account_cannot_verify_anything(self):
        self.client.force_login(User.objects.create_user(username="regular_user", password="x"))
        response = self.client.post(reverse("hospitals:verify", args=[self.request_obj.pk]))
        self.assertEqual(response.status_code, 403)

    def test_a_hospital_staff_member_cannot_verify_their_own_request(self):
        # The real conflict-of-interest case: same person as both requester and verifier.
        own_request = make_request(
            self.account.user, self.location, hospital=self.hospital, is_verified=False,
        )
        self.client.force_login(self.account.user)
        response = self.client.post(reverse("hospitals:verify", args=[own_request.pk]))
        self.assertEqual(response.status_code, 403)
        own_request.refresh_from_db()
        self.assertFalse(own_request.is_verified)

    def test_a_different_staff_member_at_the_same_hospital_can_still_verify_it(self):
        # The block is about the same PERSON, not the whole hospital - a colleague can verify.
        colleague = make_hospital_account("colleague_staff", self.hospital, staff_name="Dr. B")
        own_request = make_request(
            self.account.user, self.location, hospital=self.hospital, is_verified=False,
        )
        self.client.force_login(colleague.user)
        self.client.post(reverse("hospitals:verify", args=[own_request.pk]))
        own_request.refresh_from_db()
        self.assertTrue(own_request.is_verified)

    def test_verifying_twice_does_not_error_or_change_who_verified_it(self):
        self.client.force_login(self.account.user)
        self.client.post(reverse("hospitals:verify", args=[self.request_obj.pk]))
        first_verified_at = BloodRequest.objects.get(pk=self.request_obj.pk).verified_at
        self.client.post(reverse("hospitals:verify", args=[self.request_obj.pk]))
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.verified_at, first_verified_at)


@FAST_HASHER
class HiddenUntilVerifiedEndToEndTests(TestCase):
    """The actual point of this whole feature: an unverified request must not be
    something a donor can see or act on - and must become so the moment its
    hospital verifies it - checked as one real flow, not just unit by unit."""

    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.account = make_hospital_account("hospital_staff", self.hospital)
        self.requester = User.objects.create_user(username="requester", password="x")
        self.req = make_request(
            self.requester, self.location, hospital=self.hospital,
            blood_type="O-", is_verified=False,
        )

    def _detail_link(self):
        # Board and home cards show the hospital's name, not the patient's, so
        # looking for the patient name would pass even if hiding broke. Every card
        # links to its request, so that link is the real test of "is it listed".
        return f'href="{reverse("blood_requests:detail", args=[self.req.pk])}"'

    def test_unverified_request_is_absent_from_the_public_board_and_home_page(self):
        self.assertNotIn(self.req, list(open_requests()))
        list_html = self.client.get(reverse("blood_requests:list")).content.decode()
        self.assertNotIn(self._detail_link(), list_html)
        home_html = self.client.get(reverse("core:home")).content.decode()
        self.assertNotIn(self._detail_link(), home_html)

    def test_a_compatible_donor_cannot_respond_before_verification(self):
        from blood_requests.tests import make_donor
        donor_user = User.objects.create_user(username="donor", password="x")
        make_donor("Donor One", "O-", self.location, user=donor_user)
        self.client.force_login(donor_user)
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertEqual(self.req.responses.count(), 0)

    def test_verifying_makes_it_immediately_visible_and_respondable(self):
        from blood_requests.tests import make_donor
        self.client.force_login(self.account.user)
        self.client.post(reverse("hospitals:verify", args=[self.req.pk]))

        self.assertIn(self.req, list(open_requests()))
        # ...and it genuinely appears on the pages people look at, not just in a query.
        self.assertIn(self._detail_link(), self.client.get(reverse("blood_requests:list")).content.decode())

        donor_user = User.objects.create_user(username="donor", password="x")
        make_donor("Donor One", "O-", self.location, user=donor_user)
        self.client.force_login(donor_user)
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertEqual(self.req.responses.count(), 1)

    def test_the_owner_can_still_see_their_own_unverified_request(self):
        self.client.force_login(self.requester)
        response = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.req.patient_name)


class HospitalsAreKeptOutOfDonorPagesTests(TestCase):
    """A hospital login verifies requests; it must not be able to become a donor."""

    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.account = make_hospital_account("hospital_desk", self.hospital)
        self.requester = User.objects.create_user(username="needs_blood", password="x")
        self.request_obj = make_request(self.requester, self.location, hospital=self.hospital, is_verified=True)
        self.client.force_login(self.account.user)

    def test_typed_donor_addresses_send_a_hospital_back_to_its_desk(self):
        for name in ("donors:edit", "donors:profile", "donors:search"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(response, reverse("hospitals:dashboard"), fetch_redirect_response=False)

    def test_a_hospital_cannot_offer_to_help(self):
        response = self.client.post(reverse("blood_requests:respond", args=[self.request_obj.pk]))
        self.assertRedirects(response, reverse("hospitals:dashboard"), fetch_redirect_response=False)

    def test_a_hospital_is_not_invited_to_register_as_a_donor(self):
        html = self.client.get(reverse("blood_requests:detail", args=[self.request_obj.pk])).content.decode()
        self.assertNotIn(reverse("donors:edit"), html)
        self.assertNotIn("Register as a donor", html)

    def test_an_ordinary_account_still_sees_the_invitation_and_the_donor_pages(self):
        person = User.objects.create_user(username="plain_person", password="x")
        self.client.force_login(person)
        html = self.client.get(reverse("blood_requests:detail", args=[self.request_obj.pk])).content.decode()
        self.assertIn("Register as a donor", html)
        self.assertEqual(self.client.get(reverse("donors:edit")).status_code, 200)
