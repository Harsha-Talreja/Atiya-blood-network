"""The health answers on the donor form, and where they show. Blood pressure and sugar are no longer asked."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.tests import make_donor, make_location
from donors.models import DonorProfile
from donors.test_views import form_data

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class HealthFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ali", "ali@example.com", "x")
        self.client.force_login(self.user)
        self.area = make_location("Sukkur", "Military Road")
        self.url = reverse("donors:edit")

    def post(self, **overrides):
        return self.client.post(self.url, form_data(self.area, **overrides))

    def test_the_form_has_every_health_field(self):
        html = self.client.get(self.url).content.decode()
        for name in ("weight_kg", "height_cm", "conditions", "conditions_other"):
            with self.subTest(field=name):
                self.assertIn(f'name="{name}"', html)
        for gone in ("blood_pressure", "blood_sugar"):
            with self.subTest(gone=gone):
                self.assertNotIn(f'name="{gone}"', html)
        self.assertIn("Health check", html)
        self.assertIn("None", html)

    def test_weight_and_height_are_required(self):
        for field in ("weight_kg", "height_cm"):
            with self.subTest(field=field):
                response = self.post(**{field: ""})
                self.assertIn(field, response.context["form"].errors)
        self.assertFalse(DonorProfile.objects.exists())

    def test_weight_and_height_must_be_believable(self):
        for field, bad in (("weight_kg", "5"), ("weight_kg", "900"), ("height_cm", "20"), ("height_cm", "400"), ("weight_kg", "abc")):
            with self.subTest(field=field, value=bad):
                self.assertIn(field, self.post(**{field: bad}).context["form"].errors)

    def test_a_donor_with_no_condition_chosen_is_asked_to_choose(self):
        data = form_data(self.area)
        data.pop("conditions")
        response = self.client.post(self.url, data)
        self.assertIn("conditions", response.context["form"].errors)

    def test_none_cannot_be_mixed_with_a_condition(self):
        response = self.post(conditions=["none", "diabetes"])
        self.assertIn("conditions", response.context["form"].errors)

    def test_blood_pressure_and_sugar_are_not_asked_or_shown_even_if_an_old_profile_has_them(self):
        self.post()
        DonorProfile.objects.update(blood_pressure="190/110", blood_sugar=260)
        for page in (self.client.get(self.url), self.client.get(reverse("donors:profile") + "?tab=details")):
            html = page.content.decode()
            for text in ("190/110", "260", "Blood pressure", "Blood sugar", "usual range", "Health check needed"):
                with self.subTest(text=text):
                    self.assertNotIn(text, html)

    def test_there_are_no_know_my_bp_tick_boxes_any_more(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("has_bp", html)
        self.assertNotIn("has_sugar", html)

    def test_blood_type_is_eight_buttons_and_is_required(self):
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('name="blood_type"'), 8)
        self.assertNotIn("<select name=\"blood_type\"", html)
        response = self.post(blood_type="")
        self.assertIn("blood_type", response.context["form"].errors)
        self.assertContains(response, "Choose your blood type.")

    def test_other_needs_the_condition_to_be_typed(self):
        response = self.post(conditions=["other"], conditions_other="")
        self.assertIn("conditions_other", response.context["form"].errors)
        self.post(conditions=["other", "anaemia"], conditions_other="Thyroid")
        donor = DonorProfile.objects.get()
        self.assertEqual(donor.condition_keys, ["other", "anaemia"])
        self.assertEqual(donor.condition_labels, ["Thyroid", "Anaemia"])

    def test_the_saved_answers_come_back_when_editing(self):
        self.post(conditions=["diabetes"])
        html = self.client.get(self.url).content.decode()
        self.assertIn('value="68"', html)
        self.assertIn('value="172"', html)

    def test_the_details_page_lists_the_answers(self):
        self.post(conditions=["diabetes", "heart"])
        page = self.client.get(reverse("donors:profile") + "?tab=details").content.decode()
        for text in ("68 kg", "172 cm", "Diabetes, Heart disease"):
            with self.subTest(text=text):
                self.assertIn(text, page)

    def test_an_old_profile_without_answers_is_asked_to_add_them(self):
        donor = make_donor("Old Donor", "O+", self.area, user=self.user)
        self.assertFalse(donor.has_health_details)
        page = self.client.get(reverse("donors:profile") + "?tab=details").content.decode()
        self.assertIn("Add it", page)
        self.assertIn("Add them", page)

    def test_an_old_plus92_number_is_shown_the_new_way_when_editing(self):
        donor = make_donor("Old Donor", "O+", self.area, user=self.user)
        DonorProfile.objects.filter(pk=donor.pk).update(phone="+923001234567")
        self.assertIn('value="03001234567"', self.client.get(self.url).content.decode())


@FAST_HASHER
class HealthShowsOnlyAsATickToOthersTests(TestCase):
    def setUp(self):
        self.area = make_location("Sukkur", "Military Road")
        self.viewer = User.objects.create_user("viewer", password="x")
        self.client.force_login(self.viewer)

    def test_search_shows_a_tick_but_never_the_numbers(self):
        donor = make_donor("Ali Raza", "O+", self.area)
        DonorProfile.objects.filter(pk=donor.pk).update(
            weight_kg=71, height_cm=177, conditions="diabetes")
        page = self.client.get(reverse("donors:search"), {"blood_type": "O+"}).content.decode()
        self.assertIn("Health details added", page)
        for secret in ("71 kg", "177", "Diabetes"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, page)

    def test_no_tick_without_answers(self):
        make_donor("Sana", "O+", self.area)
        page = self.client.get(reverse("donors:search"), {"blood_type": "O+"}).content.decode()
        self.assertNotIn("Health details added", page)


@FAST_HASHER
class LastDonationRequiredTests(TestCase):
    """Everyone says when they last donated: a date, or "I have never donated blood before"."""

    def setUp(self):
        self.user = User.objects.create_user("ali", "ali@example.com", "x")
        self.client.force_login(self.user)
        self.area = make_location("Sukkur", "Military Road")
        self.url = reverse("donors:edit")

    def test_the_date_and_the_never_box_are_in_the_open_not_hidden_away(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("dform-more", html)
        self.assertNotIn("Optional details", html)
        for name in ("last_donation_date", "never_donated", "is_available"):
            with self.subTest(field=name):
                self.assertIn(f'name="{name}"', html)
        self.assertNotIn("Last donation date (optional)", html)

    def test_neither_a_date_nor_the_box_is_refused(self):
        response = self.client.post(self.url, form_data(self.area, never_donated=""))
        self.assertIn("last_donation_date", response.context["form"].errors)
        self.assertContains(response, "Enter the date you last donated")
        self.assertFalse(DonorProfile.objects.exists())

    def test_a_date_alone_is_enough(self):
        self.client.post(self.url, form_data(self.area, last_donation_date="2026-01-05"))
        self.assertEqual(str(DonorProfile.objects.get().last_donation_date), "2026-01-05")

    def test_ticking_never_donated_saves_no_date(self):
        self.client.post(self.url, form_data(self.area))
        self.assertIsNone(DonorProfile.objects.get().last_donation_date)

    def test_ticking_never_donated_ignores_a_date_typed_before(self):
        self.client.post(self.url, form_data(self.area, last_donation_date="2026-01-05", never_donated="on"))
        self.assertIsNone(DonorProfile.objects.get().last_donation_date)

    def test_a_future_date_is_still_refused(self):
        response = self.client.post(self.url, form_data(self.area, last_donation_date="2999-01-01"))
        self.assertIn("last_donation_date", response.context["form"].errors)
        self.assertFalse(DonorProfile.objects.exists())

    def test_editing_a_donor_who_never_donated_starts_with_the_box_ticked(self):
        self.client.post(self.url, form_data(self.area))
        self.assertIn("checked", self._never_input())

    def test_editing_a_donor_with_a_date_starts_with_the_box_unticked(self):
        self.client.post(self.url, form_data(self.area, last_donation_date="2026-01-05"))
        self.assertNotIn("checked", self._never_input())

    def _never_input(self):
        import re
        html = self.client.get(self.url).content.decode()
        return re.search(r'<input[^>]*name="never_donated"[^>]*>', html).group(0)

    def test_the_details_page_says_never_donated(self):
        self.client.post(self.url, form_data(self.area))
        page = self.client.get(reverse("donors:profile") + "?tab=details").content.decode()
        self.assertIn("Never donated", page)

    def test_availability_off_is_still_saved(self):
        data = form_data(self.area)
        data.pop("is_available")
        self.client.post(self.url, data)
        self.assertFalse(DonorProfile.objects.get().is_available)
