from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext, gettext_lazy as _

from accounts.cnic_form import CnicFieldMixin
from blood_requests.models import BloodRequest, Report
from blood_requests.visibility import max_units_per_request
from core.constants import BLOOD_TYPES, EXTRA_REASON_MIN_LENGTH, REPORT_REASONS, UNITS_HARD_CAP, URGENCY_LEVELS
from hospitals.models import Hospital


class BloodRequestForm(CnicFieldMixin, forms.ModelForm):
    """Post a new blood request.

    The requester is never part of the form: the view attaches request.user,
    so nobody can post on someone else's behalf by tampering with the request.
    status, expires_at and is_verified are all set elsewhere (model / view / a
    hospital verifying it), never editable here.

    `location` isn't a form field: it's set from the chosen hospital's own
    location in the view, so a request can never end up pointing at a
    different city than the hospital that's meant to verify it.
    """

    # One dropdown, grouped by city, same pattern as DonorProfileForm's location field.
    hospital = forms.ChoiceField(label=_("Hospital"), choices=[])

    class Meta:
        model = BloodRequest
        fields = [
            "patient_name", "blood_type", "units_needed", "urgency",
            "hospital", "contact_phone", "note", "extra_reason",
        ]
        labels = {
            "patient_name": _("Patient's name"),
            "blood_type": _("Blood type needed"),
            "units_needed": _("Units needed"),
            "urgency": _("How urgent?"),
            "contact_phone": _("Contact number"),
            "note": _("Note for donors"),
            "extra_reason": _("Why is extra blood needed?"),
        }
        help_texts = {
            # The labels and placeholders say it all; the old hint lines are gone.
            "units_needed": "", "urgency": "", "contact_phone": "", "note": "",
        }
        widgets = {
            "patient_name": forms.TextInput(attrs={"placeholder": _("e.g. Ahmed Khan"), "autocomplete": "name"}),
            "units_needed": forms.NumberInput(attrs={"min": 1, "max": UNITS_HARD_CAP}),
            "contact_phone": forms.TextInput(attrs={
                "placeholder": "03001234567", "inputmode": "numeric", "autocomplete": "tel", "data-digits": "11",
                "maxlength": "11", "pattern": r"03\d{9}",
                "title": _("Enter an 11-digit mobile number that starts with 03, e.g. 03001234567"),
            }),
            "note": forms.Textarea(attrs={
                "rows": 2, "placeholder": _("Ward, doctor's name, anything that helps a donor find you"),
            }),
            "extra_reason": forms.Textarea(attrs={
                "rows": 2, "data-extra-reason": "", "placeholder": _("Who needs the extra blood, and why"),
            }),
            # Buttons instead of dropdowns: one tap, and they take less room.
            "blood_type": forms.RadioSelect,
            "urgency": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["blood_type"].choices = [
            (blood_type, blood_type.replace("-", "\u2212")) for blood_type in BLOOD_TYPES
        ]
        self.fields["blood_type"].error_messages["required"] = _("Choose the blood type needed.")

        groups = {}
        for hospital in Hospital.objects.select_related("location").order_by("location__city", "name"):
            groups.setdefault(hospital.location.city, []).append((str(hospital.pk), hospital.name))
        self.fields["hospital"].choices = [("", gettext("Choose the hospital"))] + list(groups.items())

        # Urgency words are stored in English; only their labels are translated.
        self.fields["urgency"].choices = [(level, gettext(level)) for level in URGENCY_LEVELS]

        self.fields["note"].required = False
        self.fields["extra_reason"].required = False

        # The limit is read when the form is built, so a change an admin makes in
        # the panel shows up on the next page load.
        self.unit_limit = max_units_per_request()
        units = self.fields["units_needed"]
        # No hint line: the box says the limit itself, but only once someone goes above it.
        units.widget.attrs["data-unit-limit"] = self.unit_limit

    def clean_units_needed(self):
        units = self.cleaned_data["units_needed"]
        if units > UNITS_HARD_CAP:
            raise ValidationError(
                gettext("A single request can ask for at most %(max)s units.") % {"max": UNITS_HARD_CAP})
        return units

    def clean(self):
        cleaned = super().clean()
        units = cleaned.get("units_needed")
        reason = (cleaned.get("extra_reason") or "").strip()
        cleaned["extra_reason"] = reason
        if units and units > self.unit_limit and len(reason) < EXTRA_REASON_MIN_LENGTH:
            self.add_error(
                "extra_reason",
                gettext("You asked for %(units)s units, which is more than %(limit)s. "
                        "Please explain why this much blood is needed, in a sentence or two.")
                % {"units": units, "limit": self.unit_limit},
            )
        return cleaned

    def clean_hospital(self):
        try:
            return Hospital.objects.select_related("location").get(pk=self.cleaned_data["hospital"])
        except (Hospital.DoesNotExist, ValueError, TypeError):
            raise ValidationError(gettext("Please choose a hospital from the list.")) from None


class ReportForm(forms.ModelForm):
    """Flag a request as suspicious. request and reporter are set by the view,
    never from form data, so nobody can file a report as someone else."""

    class Meta:
        model = Report
        fields = ["reason", "details"]
        labels = {"reason": _("Why are you reporting this?"), "details": _("Anything else? (optional)")}
        widgets = {
            "details": forms.Textarea(attrs={"rows": 3, "placeholder": _("Optional details that would help an admin review this")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["details"].required = False
        self.fields["reason"].choices = [("", "---------")] + [(reason, gettext(reason)) for reason in REPORT_REASONS]
