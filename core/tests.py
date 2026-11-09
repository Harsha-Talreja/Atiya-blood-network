from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from core import constants
from core.blood import COMPATIBLE_DONORS, can_donate, compatible_donor_types
from core.validators import phone_validator

# ---------------------------------------------------------------------------
# Truth table typed by hand from the standard compatibility chart, on purpose
# NOT derived from COMPATIBLE_DONORS, so it is an independent check.
# Rows = recipient, columns = donor in ORDER; "1" = donor can give to recipient.
# ---------------------------------------------------------------------------
ORDER = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]
MATRIX = {
    "O-":  "10000000",
    "O+":  "11000000",
    "A-":  "10100000",
    "A+":  "11110000",
    "B-":  "10001000",
    "B+":  "11001100",
    "AB-": "10101010",
    "AB+": "11111111",
}
TRUTH_TABLE = {
    (donor, recipient): MATRIX[recipient][i] == "1"
    for recipient in MATRIX
    for i, donor in enumerate(ORDER)
}


def antigens(blood_type):
    """Second, independent method: which antigens does this type carry?"""
    abo, rh = blood_type[:-1], blood_type[-1]  # "AB+" -> ("AB", "+")
    found = set(abo) - {"O"}                   # "AB" -> {A, B}; "O" -> {}
    if rh == "+":
        found.add("Rh")
    return found


class CompatibilityTruthTableTests(SimpleTestCase):
    def test_truth_table_is_complete_and_has_27_compatible_pairs(self):
        self.assertEqual(len(TRUTH_TABLE), 64)
        self.assertEqual(sum(TRUTH_TABLE.values()), 27)  # known medical fact

    def test_all_64_pairs_match_truth_table(self):
        for (donor, recipient), expected in TRUTH_TABLE.items():
            with self.subTest(donor=donor, recipient=recipient):
                self.assertEqual(can_donate(donor, recipient), expected)

    def test_compatible_donor_types_match_truth_table(self):
        for recipient in ORDER:
            expected = {d for d in ORDER if TRUTH_TABLE[(d, recipient)]}
            with self.subTest(recipient=recipient):
                self.assertEqual(set(compatible_donor_types(recipient)), expected)


class CompatibilityAntigenTests(SimpleTestCase):
    def test_all_64_pairs_follow_the_antigen_subset_rule(self):
        # Compatible <=> donor's antigens are a subset of recipient's antigens.
        for donor in constants.BLOOD_TYPES:
            for recipient in constants.BLOOD_TYPES:
                with self.subTest(donor=donor, recipient=recipient):
                    expected = antigens(donor) <= antigens(recipient)
                    self.assertEqual(can_donate(donor, recipient), expected)


class CompatibilityRulesTests(SimpleTestCase):
    def test_o_negative_is_universal_donor(self):
        for recipient in constants.BLOOD_TYPES:
            self.assertTrue(can_donate("O-", recipient))

    def test_ab_positive_is_universal_recipient(self):
        for donor in constants.BLOOD_TYPES:
            self.assertTrue(can_donate(donor, "AB+"))

    def test_o_negative_receives_only_from_o_negative(self):
        self.assertEqual(compatible_donor_types("O-"), ["O-"])

    def test_rh_positive_never_gives_to_rh_negative(self):
        for donor in ("A+", "B+", "AB+", "O+"):
            for recipient in ("A-", "B-", "AB-", "O-"):
                self.assertFalse(can_donate(donor, recipient))

    def test_mapping_keys_match_constants(self):
        self.assertEqual(set(COMPATIBLE_DONORS), set(constants.BLOOD_TYPES))

    def test_unknown_types_raise_value_error(self):
        with self.assertRaises(ValueError):
            compatible_donor_types("Z+")
        with self.assertRaises(ValueError):
            can_donate("Z+", "A+")

    def test_returned_list_is_a_copy(self):
        result = compatible_donor_types("A+")
        result.append("HACKED")
        self.assertNotIn("HACKED", compatible_donor_types("A+"))


class ConstantsTests(SimpleTestCase):
    def test_cooldown_and_expiry_hours(self):
        self.assertEqual(constants.DONATION_COOLDOWN_DAYS, 90)
        self.assertEqual(constants.URGENCY_HOURS["Critical"], 24)
        self.assertEqual(constants.URGENCY_HOURS["Urgent"], 48)
        self.assertEqual(constants.URGENCY_HOURS["Normal"], 72)


class PhoneValidatorTests(SimpleTestCase):
    def test_valid_numbers(self):
        for number in ("03001234567", "03451234567"):
            with self.subTest(number=number):
                phone_validator(number)  # must not raise

    def test_invalid_numbers(self):
        for number in ("0300123456", "030012345678", "12345678901",
                       "+923001234567", "+92 300 1234567", "abc", ""):
            with self.subTest(number=number):
                with self.assertRaises(ValidationError):
                    phone_validator(number)
