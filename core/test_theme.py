"""Tests for the theme system: dark mode contrast, error pages, form helpers, request cards."""
import re
from pathlib import Path

from django.contrib.staticfiles import finders
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.views.defaults import server_error

from blood_requests.tests import make_location, make_request
from core.forms import StyleGuideDemoForm


# --------------------------------------------------------------------------- #
# Colour contrast (WCAG): every text/background pair must stay readable in BOTH
# the light and the dark palette. Values are read straight from theme.css.
# --------------------------------------------------------------------------- #
def _theme_css():
    return Path(finders.find("css/theme.css")).read_text(encoding="utf-8")


def _tokens(block_start):
    css = _theme_css()
    start = css.index(block_start)
    body = css[css.index("{", start) + 1: css.index("}", start)]
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\b", body))


def _luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_PAIRS = [  # (foreground token, background token, minimum ratio)
    ("text", "bg", 4.5), ("text", "surface", 4.5),
    ("muted", "bg", 4.5), ("muted", "surface", 4.5),
    ("brand-text", "surface", 4.5), ("brand-text", "bg", 4.5), ("brand-text", "tint", 4.5),
    ("on-tint", "tint", 4.5),
    ("blood-text", "surface", 4.5), ("blood-text", "bg", 4.5),
    ("brand-accent", "tint", 3.0), ("brand-accent", "surface", 3.0),  # icons and large accents
]


class ContrastTests(SimpleTestCase):
    def check(self, palette_name, tokens):
        for fg, bg, minimum in TEXT_PAIRS:
            with self.subTest(palette=palette_name, fg=fg, bg=bg):
                ratio = contrast(tokens[fg], tokens[bg])
                self.assertGreaterEqual(ratio, minimum, f"{fg} on {bg} is only {ratio:.2f}:1 in {palette_name} mode")

    def test_light_palette_is_readable(self):
        self.check("light", _tokens(":root {"))

    def test_dark_palette_is_readable(self):
        tokens = _tokens(":root {")
        tokens.update(_tokens('[data-bs-theme="dark"] {'))
        self.check("dark", tokens)

    def test_white_text_on_filled_buttons_is_readable(self):
        tokens = _tokens(":root {")
        for name in ("brand", "blood"):
            with self.subTest(button=name):
                self.assertGreaterEqual(contrast("#FFFFFF", tokens[name]), 4.5)

    def test_dark_palette_defines_every_token_the_light_one_switches(self):
        light, dark = _tokens(":root {"), _tokens('[data-bs-theme="dark"] {')
        for token in ("bg", "surface", "text", "muted", "line", "tint", "brand-text", "on-tint", "blood-text"):
            with self.subTest(token=token):
                self.assertIn(token, dark)
                self.assertNotEqual(light[token].lower(), dark[token].lower())


class ThemeWiringTests(TestCase):
    def test_home_has_theme_toggle_and_early_theme_script(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("data-theme-toggle", html)
        self.assertIn('localStorage.getItem("theme")', html)   # applied before first paint: no flash
        self.assertIn('id="successModal"', html)

    def test_light_is_the_default_theme(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn('data-bs-theme="light"', html)


# --------------------------------------------------------------------------- #
# Error pages
# --------------------------------------------------------------------------- #
class ErrorPageTests(TestCase):
    def test_unknown_url_shows_branded_404(self):
        response = self.client.get("/definitely-not-a-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "We can't find that page", status_code=404)
        self.assertContains(response, "Back to home", status_code=404)

    def test_500_page_is_standalone_and_never_crashes(self):
        # Django renders 500.html with no request context, so it must not depend on any.
        response = server_error(RequestFactory().get("/"))
        self.assertEqual(response.status_code, 500)
        self.assertIn(b"Something went wrong", response.content)
        self.assertIn(b"blood bank", response.content)


class DeveloperPagesTests(TestCase):
    @override_settings(DEBUG=False)
    def test_style_guide_is_hidden_when_debug_is_off(self):
        for name in ("core:style_guide", "core:preview_404", "core:preview_500"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 404)

    @override_settings(DEBUG=True)
    def test_style_guide_renders_every_section_when_debug_is_on(self):
        response = self.client.get(reverse("core:style_guide"))
        self.assertEqual(response.status_code, 200)
        for text in ("Colours", "Buttons", "Request cards", "Forms", "Feedback", "loading placeholders"):
            self.assertContains(response, text)

    @override_settings(DEBUG=True)
    def test_preview_error_pages_work_when_debug_is_on(self):
        self.assertEqual(self.client.get(reverse("core:preview_404")).status_code, 404)
        self.assertEqual(self.client.get(reverse("core:preview_500")).status_code, 500)


# --------------------------------------------------------------------------- #
# Form helpers
# --------------------------------------------------------------------------- #
class FormFieldTests(SimpleTestCase):
    def render_field(self, form, name):
        return render_to_string("components/form_field.html", {"field": form[name]})

    def test_valid_field_has_no_error_markup(self):
        form = StyleGuideDemoForm()
        html = self.render_field(form, "full_name")
        self.assertIn('class="form-control"', html)
        self.assertNotIn("is-invalid", html)
        self.assertNotIn("aria-invalid", html)

    def test_invalid_field_shows_message_and_accessibility_hooks(self):
        form = StyleGuideDemoForm({"full_name": "Ali", "phone": "12345", "blood_type": "O+", "password": "longenough"})
        html = self.render_field(form, "phone")
        self.assertIn("is-invalid", html)
        self.assertIn('aria-invalid="true"', html)
        self.assertIn("11-digit mobile number", html)
        self.assertIn('aria-describedby="id_phone-hint id_phone-error"', html)

    def test_required_fields_are_reported(self):
        form = StyleGuideDemoForm({})
        self.assertFalse(form.is_valid())
        self.assertIn("full_name", form.errors)
        self.assertIn("password", form.errors)

    def test_optional_field_is_labelled_optional(self):
        self.assertIn("(optional)", self.render_field(StyleGuideDemoForm(), "note"))

    def test_password_field_gets_a_show_hide_button(self):
        html = self.render_field(StyleGuideDemoForm(), "password")
        self.assertIn("data-toggle-password", html)
        self.assertIn('aria-label="Show password"', html)

    def test_select_uses_form_select_class(self):
        self.assertIn('class="form-select"', self.render_field(StyleGuideDemoForm(), "blood_type"))

    def test_phone_field_has_cleanup_hook_and_pattern(self):
        html = self.render_field(StyleGuideDemoForm(), "phone")
        self.assertIn('data-digits="11"', html)
        self.assertIn('maxlength="11"', html)
        self.assertIn("pattern=", html)

    def test_non_field_errors_are_shown_in_an_alert(self):
        form = StyleGuideDemoForm({})
        form.is_valid()                      # a form must be validated before errors can be added
        form.add_error(None, "Invalid login details.")
        html = render_to_string("components/form_errors.html", {"form": form})
        self.assertIn('role="alert"', html)
        self.assertIn("Invalid login details.", html)


# --------------------------------------------------------------------------- #
# Request cards: urgency edge and live countdown
# --------------------------------------------------------------------------- #
class RequestCardTests(TestCase):
    def test_card_has_urgency_class_and_countdown_hook(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="r")
        req = make_request(user, make_location("Sukkur", "Military Road"), urgency="Critical")
        html = render_to_string("components/request_card.html", {"req": req})
        self.assertIn("is-critical", html)
        self.assertIn("data-countdown=", html)
        self.assertRegex(html, r'data-countdown="\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}"')  # ISO 8601 with time zone
        self.assertIn("Closes in", html)   # server-rendered fallback when JavaScript is off

    def test_each_urgency_gets_its_own_class(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="r2")
        location = make_location("Sukkur", "Barrage Road")
        for urgency in ("Critical", "Urgent", "Normal"):
            with self.subTest(urgency=urgency):
                req = make_request(user, location, urgency=urgency)
                self.assertIn(f"is-{urgency.lower()}", render_to_string("components/request_card.html", {"req": req}))


class ComponentTests(SimpleTestCase):
    def test_skeleton_and_success_components_render(self):
        self.assertIn("skeleton", render_to_string("components/skeleton_card.html"))
        self.assertIn("check-circle", render_to_string("components/success_check.html"))

    def test_reduced_motion_covers_new_animations(self):
        css = _theme_css()
        tail = css[css.rindex("@media (prefers-reduced-motion: reduce)"):]
        for selector in (".skeleton", ".check-circle", ".btn-pulse", ".drop"):
            with self.subTest(selector=selector):
                self.assertIn(selector, tail)
