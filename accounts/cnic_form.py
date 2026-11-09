"""A form mixin that asks for the CNIC once.

Both the donor form and the request form use it. When the signed-in person has no CNIC
on file, the form gets a required `cnic` field and cannot be saved without it. When one is
already saved, the field is not there at all and the page shows the last four digits instead.
"""
import re

from django import forms
from django.core.exceptions import ValidationError

from accounts.identity import (RETIRED_MESSAGE, cnic_is_retired, cnic_taken_by_someone_else, get_identity,
                               save_identity)
from core.validators import cnic_validator
from django.utils.translation import gettext, gettext_lazy as _


# The box shows the CNIC with dashes as it is typed (12345-1234567-1). Only that exact shape is
# accepted with dashes; it is turned back into the 13 digits before anything is checked or saved.
_DASHED_CNIC = re.compile(r"^(\d{5})-(\d{7})-(\d)\Z")


def normalise_cnic(text):
    """'42101-1234567-1' -> '4210112345671'. Anything else is returned as it is, to be refused later."""
    text = (text or "").strip()
    match = _DASHED_CNIC.match(text)
    return "".join(match.groups()) if match else text


class CnicFieldMixin:
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.identity = get_identity(user) if user is not None else None
        # No user passed (a form built outside a signed-in view): no CNIC step, so nothing is
        # asked twice. Every real view passes the user.
        if user is not None and self.identity is None:
            self.fields["cnic"] = forms.CharField(
                label=_("Your CNIC number"),
                widget=forms.TextInput(attrs={
                    "placeholder": "12345-1234567-1", "inputmode": "numeric", "autocomplete": "off",
                    "maxlength": "15", "pattern": r"\d{5}-?\d{7}-?\d", "data-digits": "13", "data-format": "cnic",
                    "title": _("Enter all 13 digits of your CNIC."),
                }),
                error_messages={"required": _("Enter your CNIC number to continue.")},
            )

    @property
    def needs_cnic(self):
        return "cnic" in self.fields

    def clean_cnic(self):
        cnic = normalise_cnic(self.cleaned_data.get("cnic"))
        cnic_validator(cnic)
        if cnic_taken_by_someone_else(cnic, self.user):
            raise ValidationError(gettext("This CNIC is already used by another account."), code="cnic_taken")
        if cnic_is_retired(cnic):
            raise ValidationError(gettext(RETIRED_MESSAGE), code="cnic_retired")
        return cnic

    def save_identity(self):
        """Save the CNIC if this form asked for one. Call it inside the same transaction as the save."""
        if self.needs_cnic:
            self.identity = save_identity(self.user, self.cleaned_data["cnic"])
