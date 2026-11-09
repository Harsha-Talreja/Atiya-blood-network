"""The health question on the donor form: the list of conditions."""
from django.utils.translation import gettext_lazy as _

CONDITIONS = [
    ("none", _("None")),
    ("diabetes", _("Diabetes")),
    ("high_bp", _("High blood pressure")),
    ("heart", _("Heart disease")),
    ("anaemia", _("Anaemia")),
    ("hepatitis_hiv", _("Hepatitis or HIV")),
    ("other", _("Other")),
]
CONDITION_LABELS = dict(CONDITIONS)
