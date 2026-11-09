from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.cnic_form import CnicFieldMixin
from core.constants import BLOOD_TYPES
from core.models import Location
from donors.health import CONDITIONS
from donors.models import DonorProfile
from django.utils.translation import gettext, gettext_lazy as _


class DonorProfileForm(CnicFieldMixin, forms.ModelForm):
    """Create or edit the signed-in person's donor profile.

    The user is never part of the form: the view attaches request.user, so nobody can
    create or change someone else's profile by tampering with the request.
    """

    # One dropdown, grouped by city (works on every phone, no JavaScript needed).
    location = forms.ChoiceField(label=_("Your area"), choices=[])

    # Health question: the conditions the donor knows about.
    conditions = forms.MultipleChoiceField(
        label=_("Existing diseases or medical conditions"), choices=CONDITIONS, widget=forms.CheckboxSelectMultiple,
        error_messages={"required": _("Choose at least one. Choose None if you have no known condition.")},
    )

    # Not saved as a column: ticking it means "no last donation date". An empty date on a saved
    # profile already means the donor has never donated, so the box starts ticked when editing it.
    never_donated = forms.BooleanField(required=False, label=_("I have never donated blood before"))

    class Meta:
        model = DonorProfile
        fields = ["full_name", "phone", "blood_type", "location", "last_donation_date",
                  "weight_kg", "height_cm", "conditions_other",
                  "is_available", "phone_consent", "eligibility_declared"]
        labels = {
            "full_name": _("Full name"),
            "phone": _("Mobile number"),
            "blood_type": _("Blood type"),
            "last_donation_date": _("Date of your last donation"),
            "weight_kg": _("Weight (kg)"),
            "height_cm": _("Height (cm)"),
            "conditions_other": _("Tell us which condition"),
            "is_available": _("Available to donate"),
            "phone_consent": _("People with a matching blood request may see my phone number"),
            "eligibility_declared": _("I confirm I am 18 or older and in good health"),
        }
        help_texts = {
            "last_donation_date": _("Needed so we know when you can give again (90 days after)."),
            "phone_consent": _("Only signed-in users with an open, matching request can see it. It is never shown publicly."),
            "eligibility_declared": _("I understand that a hospital or blood bank will screen me before any donation."),
        }
        widgets = {
            "full_name": forms.TextInput(attrs={"placeholder": _("e.g. Ali Raza"), "autocomplete": "name"}),
            "phone": forms.TextInput(attrs={
                "placeholder": "03001234567", "inputmode": "numeric", "autocomplete": "tel", "data-digits": "11",
                "maxlength": "11", "pattern": r"03\d{9}",
                "title": _("Enter an 11-digit mobile number that starts with 03, e.g. 03001234567"),
            }),
            "weight_kg": forms.NumberInput(attrs={"placeholder": "e.g. 68", "inputmode": "numeric", "min": 30, "max": 250}),
            "height_cm": forms.NumberInput(attrs={"placeholder": "e.g. 172", "inputmode": "numeric", "min": 100, "max": 230}),
            "conditions_other": forms.TextInput(attrs={"placeholder": _("Type the condition"), "maxlength": "100"}),
            "last_donation_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            # Eight tap-buttons instead of a dropdown: one tap, and it takes less room.
            "blood_type": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["blood_type"].choices = [
            (blood_type, blood_type.replace("-", "\u2212")) for blood_type in BLOOD_TYPES
        ]
        self.fields["blood_type"].error_messages["required"] = _("Choose your blood type.")

        groups = {}
        for location in Location.objects.order_by("city", "area"):
            groups.setdefault(location.city, []).append((str(location.pk), location.area))
        self.fields["location"].choices = [("", _("Choose your area"))] + list(groups.items())

        # Never a future date, in the picker as well as on the server.
        self.fields["last_donation_date"].widget.attrs["max"] = timezone.localdate().isoformat()

        # The basics are asked of every new donor.
        self.fields["weight_kg"].required = True
        self.fields["height_cm"].required = True
        self.fields["conditions_other"].required = False
        self.fields["last_donation_date"].required = False   # checked in clean(): a date, or "never donated"
        if self.instance and self.instance.pk:
            self.initial["conditions"] = self.instance.condition_keys
            self.initial["never_donated"] = self.instance.last_donation_date is None
            # Numbers saved the old way (+923...) are shown the new way so they pass the new check.
            phone = self.instance.phone or ""
            if phone.startswith("+92") and len(phone) == 13:
                self.initial["phone"] = "0" + phone[3:]

        # The two declarations must be ticked to register.
        self.fields["phone_consent"].required = True
        self.fields["phone_consent"].error_messages["required"] = _("Please tick this so requesters can contact you.")
        self.fields["eligibility_declared"].required = True
        self.fields["eligibility_declared"].error_messages["required"] = _("Please confirm this to register as a donor.")

    def clean_conditions(self):
        picked = self.cleaned_data.get("conditions") or []
        if "none" in picked and len(picked) > 1:
            raise ValidationError(gettext("Choose None on its own, or pick the conditions you have."))
        return picked

    def clean(self):
        cleaned = super().clean()
        # The last donation is asked of everyone: either the date, or "I have never donated".
        if cleaned.get("never_donated"):
            cleaned["last_donation_date"] = None
        elif not cleaned.get("last_donation_date") and "last_donation_date" not in self.errors:
            self.add_error("last_donation_date",
                           gettext("Enter the date you last donated, or tick \u201cI have never donated blood before\u201d."))
        picked = cleaned.get("conditions") or []
        if "other" in picked:
            if not (cleaned.get("conditions_other") or "").strip():
                self.add_error("conditions_other", gettext("Tell us which condition."))
        else:
            cleaned["conditions_other"] = ""
        return cleaned

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.conditions_other = self.cleaned_data.get("conditions_other", "")
        profile.conditions = ",".join(self.cleaned_data.get("conditions") or [])
        if commit:
            profile.save()
        return profile

    def clean_location(self):
        try:
            return Location.objects.get(pk=self.cleaned_data["location"])
        except (Location.DoesNotExist, ValueError, TypeError):
            raise ValidationError(gettext("Please choose your area from the list.")) from None
