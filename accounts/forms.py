from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext, gettext_lazy as _

User = get_user_model()


class SignupForm(UserCreationForm):
    """Create an account. Django hashes the password: it is never stored as typed."""

    email = forms.EmailField(
        label=_("Email"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "off", "placeholder": "you@example.com"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        username = self.fields["username"]
        username.label = _("Username")
        username.help_text = ""
        # autocomplete is off on purpose: a shared computer should not offer the
        # last person's details to the next one.
        username.widget.attrs.update({"autofocus": True, "autocomplete": "off", "autocapitalize": "none", "spellcheck": "false", "placeholder": _("e.g. ali.raza")})

        password = self.fields["password1"]
        password.label = _("Password")
        # Django's default help text is an HTML list that our form components escape, so it is switched off.
        password.help_text = ""
        password.widget.attrs.update({"autocomplete": "new-password", "minlength": "4"})

        confirm = self.fields["password2"]
        confirm.label = _("Confirm password")
        confirm.help_text = ""
        confirm.widget.attrs.update({"autocomplete": "new-password", "minlength": "4"})

    def clean_username(self):
        username = self.cleaned_data["username"]
        # "Ali" and "ali" must not become two different accounts.
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(gettext("That username is already taken. Please choose another."))
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(gettext("An account with this email already exists. Try logging in instead."))
        return email


class LoginForm(AuthenticationForm):
    remember = forms.BooleanField(
        required=False,
        label=_("Remember me on this device"),
    )

    error_messages = {
        # One message for a wrong username OR a wrong password, so nobody can probe which accounts exist.
        "invalid_login": _("That username and password don't match. Please check them and try again."),
        "inactive": _("This account is switched off. Please contact an administrator."),
        "blocked": _("This account has been blocked by an admin, so it cannot sign in."),
        "throttled": _("Too many wrong attempts. Please wait a few minutes and try again."),
    }

    def clean(self):
        from accounts import throttle

        username = self.data.get(self.add_prefix("username"), "")
        # Checked before the password is even tried, so a locked-out guesser
        # learns nothing from the answer, right or wrong.
        if throttle.is_locked(self.request, username):
            raise forms.ValidationError(self.error_messages["throttled"], code="throttled")
        try:
            cleaned = super().clean()
        except forms.ValidationError as error:
            if error.code == "invalid_login":
                throttle.record_failure(self.request, username)
            raise
        throttle.reset(self.request, username)
        return cleaned

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        # Checked after the password, so the message does not reveal that a
        # username exists to someone who does not know its password.
        from accounts.models import is_blocked

        if not user.is_staff and is_blocked(user):
            raise forms.ValidationError(self.error_messages["blocked"], code="blocked")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        username = self.fields["username"]
        username.label = _("Username")
        # Both fields tell the browser not to fill them in. "new-password" is the
        # value browsers respect on a password box; "current-password" would
        # invite them to offer whoever signed in here last.
        username.widget.attrs.update({"autofocus": True, "autocomplete": "off", "autocapitalize": "none", "spellcheck": "false", "placeholder": _("Your username")})
        password = self.fields["password"]
        password.label = _("Password")
        password.widget.attrs.update({"autocomplete": "new-password"})
