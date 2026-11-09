"""Reusable field validators shared by donors and blood_requests."""
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Pakistani mobile: exactly 11 digits, 03XXXXXXXXX. Numbers saved earlier as +923XXXXXXXXX
# still work wherever they are shown (see blood_requests/contact.py); new ones are 11 digits.
# \Z anchors the true end of the string (a plain $ would allow a trailing newline).
phone_validator = RegexValidator(
    regex=r"^03\d{9}\Z",
    message=_("Enter an 11-digit mobile number that starts with 03, e.g. 03001234567."),
    code="invalid_phone",
)

# CNIC: exactly 13 digits, no dashes or spaces.
cnic_validator = RegexValidator(
    regex=r"^\d{13}\Z",
    message=_("Enter all 13 digits of the CNIC, numbers only."),
    code="invalid_cnic",
)


def validate_not_in_future(value):
    """A donation date can't be later than today (Karachi time)."""
    if value > timezone.localdate():
        raise ValidationError(_("This date cannot be in the future."), code="future_date")
