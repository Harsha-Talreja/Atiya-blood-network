from django import forms

from core.constants import (
    AUTO_APPROVE_MINUTES_MAX,
    AUTO_APPROVE_MINUTES_MIN,
    MAX_UNITS_LIMIT_MAX,
    MAX_UNITS_LIMIT_MIN,
)
from siteadmin.models import SiteSetting


class WaitTimesForm(forms.ModelForm):
    """The three auto-approve windows, and the standard unit limit per request.

    Bounds come from core.constants rather than being written here, so the form,
    the model validators and anything else that checks a window agree.
    """

    class Meta:
        model = SiteSetting
        fields = [
            "critical_wait_minutes", "urgent_wait_minutes", "normal_wait_minutes",
            "max_units_per_request",
        ]
        labels = {
            "critical_wait_minutes": "Critical waits",
            "urgent_wait_minutes": "Urgent waits",
            "normal_wait_minutes": "Normal waits",
            "max_units_per_request": "Units per request before approval is needed",
        }
        # No help_texts: the panel keeps its pages free of explanatory prose, and
        # the labels plus the "minutes" suffix say what each box takes.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("critical_wait_minutes", "urgent_wait_minutes", "normal_wait_minutes"):
            field = self.fields[name]
            field.min_value = AUTO_APPROVE_MINUTES_MIN
            field.max_value = AUTO_APPROVE_MINUTES_MAX
            field.widget.attrs.update(
                {
                    "class": "form-control",
                    "min": AUTO_APPROVE_MINUTES_MIN,
                    "max": AUTO_APPROVE_MINUTES_MAX,
                    "inputmode": "numeric",
                }
            )

        units = self.fields["max_units_per_request"]
        # Left out of a submission, it keeps the current value.
        units.required = False
        units.widget.attrs.update(
            {"class": "form-control", "min": MAX_UNITS_LIMIT_MIN, "max": MAX_UNITS_LIMIT_MAX,
             "inputmode": "numeric"}
        )

    def clean_max_units_per_request(self):
        value = self.cleaned_data.get("max_units_per_request")
        return self.instance.max_units_per_request if value is None else value

    def clean(self):
        cleaned = super().clean()
        critical = cleaned.get("critical_wait_minutes")
        urgent = cleaned.get("urgent_wait_minutes")
        normal = cleaned.get("normal_wait_minutes")
        # A Critical request waiting longer than a Normal one is almost certainly a
        # typo, and it is the kind of typo that costs someone time in an emergency.
        # Warn about the order rather than silently accepting it.
        if None not in (critical, urgent, normal) and not (critical <= urgent <= normal):
            raise forms.ValidationError(
                "Critical should wait the least and Normal the most. "
                f"You entered Critical {critical}, Urgent {urgent}, Normal {normal} minutes."
            )
        return cleaned


class ExtraUnitsReviewForm(forms.Form):
    """An admin's decision on a request that asked for more than the unit limit."""

    decision = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject")])
    note = forms.CharField(
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Note for the record"}),
    )

    def clean(self):
        cleaned = super().clean()
        note = (cleaned.get("note") or "").strip()
        cleaned["note"] = note
        # Turning someone down without saying why leaves the requester guessing
        # and the audit log with nothing to explain it.
        if cleaned.get("decision") == "reject" and len(note) < 5:
            self.add_error("note", "Please say why this is being rejected.")
        return cleaned


class ActionNoteForm(forms.Form):
    """The one-line reason attached to an admin action.

    Optional, because demanding a reason for every click gets people typing "x".
    It is stored on the audit entry when given.
    """

    note = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Reason (optional)"}
        ),
    )
