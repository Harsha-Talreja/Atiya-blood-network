from django.test import SimpleTestCase

from core.blood import COMPATIBLE_DONORS, can_donate, compatible_recipient_types
from core.constants import BLOOD_TYPES


class RecipientLookupTests(SimpleTestCase):
    def test_o_negative_can_give_to_everyone(self):
        self.assertEqual(set(compatible_recipient_types("O-")), set(BLOOD_TYPES))

    def test_ab_positive_can_only_give_to_ab_positive(self):
        self.assertEqual(compatible_recipient_types("AB+"), ["AB+"])

    def test_a_positive_recipients(self):
        self.assertEqual(set(compatible_recipient_types("A+")), {"A+", "AB+"})

    def test_reverse_lookup_agrees_with_the_forward_rule_for_all_64_pairs(self):
        for donor in BLOOD_TYPES:
            recipients = set(compatible_recipient_types(donor))
            for recipient in BLOOD_TYPES:
                with self.subTest(donor=donor, recipient=recipient):
                    self.assertEqual(recipient in recipients, can_donate(donor, recipient))

    def test_total_number_of_compatible_pairs_is_27(self):
        self.assertEqual(sum(len(compatible_recipient_types(d)) for d in BLOOD_TYPES), 27)
        self.assertEqual(sum(len(v) for v in COMPATIBLE_DONORS.values()), 27)

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(ValueError):
            compatible_recipient_types("Z+")
