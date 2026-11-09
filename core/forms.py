"""Forms used by the developer style guide. Real feature forms follow the same pattern."""
from django import forms

from core.constants import BLOOD_TYPE_CHOICES
from core.validators import phone_validator


class StyleGuideDemoForm(forms.Form):
    full_name = forms.CharField(
        label="Full name", max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Ali Raza", "autocomplete": "name"}),
    )
    phone = forms.CharField(
        label="Mobile number", validators=[phone_validator], max_length=11,
        help_text="11 digits, like 03001234567",
        widget=forms.TextInput(attrs={
            "placeholder": "03001234567", "inputmode": "numeric", "autocomplete": "tel",
            "data-digits": "11", "maxlength": "11", "pattern": r"03\d{9}",
            "title": "Enter an 11-digit mobile number that starts with 03, e.g. 03001234567",
        }),
    )
    blood_type = forms.ChoiceField(
        label="Blood type", choices=[("", "Choose blood type")] + BLOOD_TYPE_CHOICES,
    )
    password = forms.CharField(
        label="Password", min_length=8,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "minlength": "8"}),
        help_text="At least 8 characters.",
    )
    note = forms.CharField(
        label="Note for donors", required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Anything the donor should know"}),
    )
