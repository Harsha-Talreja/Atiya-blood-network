from django.test import TestCase

from blood_requests.tests import make_donor, make_location
from core.constants import BLOOD_TYPES
from donors.selectors import ready_donor_counts, search_donors


class ReadyDonorCountsTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")

    def test_returns_all_eight_types_in_order_with_zeros(self):
        result = ready_donor_counts()
        self.assertEqual([blood_type for blood_type, _ in result], BLOOD_TYPES)
        self.assertTrue(all(count == 0 for _, count in result))

    def test_counts_only_available_donors_past_cooldown(self):
        make_donor("a", "A+", self.location)                              # ready (never donated)
        make_donor("b", "A+", self.location, days_since_donation=90)      # ready (cooldown just ended)
        make_donor("c", "A+", self.location, days_since_donation=89)      # still resting
        make_donor("d", "A+", self.location, is_available=False)          # switched off
        make_donor("e", "B-", self.location)                              # different type
        counts = dict(ready_donor_counts())
        self.assertEqual(counts["A+"], 2)
        self.assertEqual(counts["B-"], 1)
        self.assertEqual(counts["O+"], 0)


class SearchDonorsTests(TestCase):
    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.rohri = make_location("Rohri", "Rohri City")

    def test_no_filters_returns_every_available_eligible_donor(self):
        make_donor("a", "A+", self.sukkur)
        make_donor("b", "O-", self.rohri)
        self.assertEqual(search_donors().count(), 2)

    def test_blood_type_filter_only_returns_compatible_donor_types(self):
        make_donor("compatible", "O-", self.sukkur)
        make_donor("incompatible", "B+", self.sukkur)
        names = [d.full_name for d in search_donors(blood_type="A+")]
        self.assertEqual(names, ["compatible"])

    def test_city_filter_narrows_to_that_city(self):
        make_donor("here", "O-", self.sukkur)
        make_donor("elsewhere", "O-", self.rohri)
        names = [d.full_name for d in search_donors(city="Sukkur")]
        self.assertEqual(names, ["here"])

    def test_excludes_unavailable_and_cooling_down_donors(self):
        make_donor("available", "O-", self.sukkur)
        make_donor("unavailable", "O-", self.sukkur, is_available=False)
        make_donor("cooling_down", "O-", self.sukkur, days_since_donation=10)
        names = [d.full_name for d in search_donors()]
        self.assertEqual(names, ["available"])
