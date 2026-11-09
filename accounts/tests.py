from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.templatetags.core_extras import dialog_text, dialog_title

User = get_user_model()

STRONG = "Strong-Pass-9271"

# Django's real password hashing is deliberately slow (that is what makes stolen hashes hard to crack).
# Most tests use a fast hasher so the suite stays quick; PasswordStorageTests below uses the real one.
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def signup_data(**overrides):
    data = {"username": "ali.raza", "email": "Ali@Example.com", "password1": STRONG, "password2": STRONG}
    data.update(overrides)
    return data


@FAST_HASHER
class SignupTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:signup")

    def test_page_loads_with_all_fields(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for name in ("username", "email", "password1", "password2"):
            self.assertContains(response, f'name="{name}"')
        self.assertContains(response, 'autocomplete="new-password"')

    def test_valid_signup_creates_user_and_logs_them_in(self):
        response = self.client.post(self.url, signup_data(), follow=True)
        self.assertRedirects(response, reverse("core:dashboard"))
        user = User.objects.get(username="ali.raza")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertTrue(response.context["user"].is_authenticated)

    def test_success_pop_up_is_queued_for_the_next_page(self):
        response = self.client.post(self.url, signup_data(), follow=True)
        self.assertContains(response, "data-flash-dialog")
        self.assertContains(response, 'data-title="Account created"')
        self.assertContains(response, "Welcome, ali.raza.")

    def test_email_is_saved_in_lowercase(self):
        self.client.post(self.url, signup_data())
        self.assertEqual(User.objects.get(username="ali.raza").email, "ali@example.com")

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(self.url, signup_data(password2="Different-Pass-1"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("password2"))
        self.assertFalse(User.objects.filter(username="ali.raza").exists())

    def test_only_very_short_passwords_are_rejected(self):
        for short in ("abc", "1", "ab"):
            with self.subTest(password=short):
                response = self.client.post(self.url, signup_data(password1=short, password2=short))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors.get("password2"))
                self.assertFalse(User.objects.filter(username="ali.raza").exists())

    def test_simple_passwords_are_allowed(self):
        # The same as the username, all numbers, a common word: all fine when signing up.
        for index, simple in enumerate(("ali.raza", "12345678", "password", "1234")):
            with self.subTest(password=simple):
                username = "ali.raza" if index == 0 else f"simple{index}"
                data = signup_data(username=username, email=f"s{index}@example.com", password1=simple, password2=simple)
                response = self.client.post(self.url, data)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(User.objects.get(username=username).check_password(simple))
                self.client.logout()

    def test_username_must_be_unique_ignoring_case(self):
        User.objects.create_user("Ali.Raza", "someone@example.com", STRONG)
        before = User.objects.count()
        response = self.client.post(self.url, signup_data(username="ali.raza", email="new@example.com"))
        self.assertTrue(response.context["form"].errors.get("username"))
        self.assertEqual(User.objects.count(), before)

    def test_email_must_be_unique_ignoring_case(self):
        User.objects.create_user("someone", "ali@example.com", STRONG)
        before = User.objects.count()
        response = self.client.post(self.url, signup_data(email="ALI@example.com"))
        self.assertTrue(response.context["form"].errors.get("email"))
        self.assertEqual(User.objects.count(), before)

    def test_bad_or_missing_input_is_rejected(self):
        cases = {"invalid email": {"email": "not-an-email"}, "no email": {"email": ""},
                 "no username": {"username": ""}, "spaces in username": {"username": "ali raza"}}
        before = User.objects.count()
        for label, override in cases.items():
            with self.subTest(case=label):
                response = self.client.post(self.url, signup_data(**override))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(User.objects.count(), before)

    def test_errors_are_shown_with_accessibility_hooks(self):
        response = self.client.post(self.url, signup_data(email="not-an-email"))
        self.assertContains(response, "is-invalid")
        self.assertContains(response, 'aria-invalid="true"')

    def test_no_help_lines_under_the_boxes_and_no_escaped_html(self):
        html = self.client.get(self.url).content.decode()
        for gone in ("At least 4 characters", "Used for account recovery", "Letters, numbers and"):
            self.assertNotIn(gone, html)
        self.assertNotIn("&lt;ul", html)
        self.assertNotIn('class="form-hint"', html)

    def test_a_too_short_password_is_still_refused_with_a_message(self):
        response = self.client.post(self.url, signup_data(password1="abc", password2="abc"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least 4 characters")

    def test_logged_in_users_are_sent_to_their_dashboard(self):
        self.client.post(self.url, signup_data())
        self.assertRedirects(self.client.get(self.url), reverse("core:dashboard"))

    def test_open_redirect_via_next_is_ignored(self):
        response = self.client.post(self.url + "?next=https://evil.example/", signup_data())
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)


@FAST_HASHER
class LoginTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:login")
        self.user = User.objects.create_user("ali.raza", "ali@example.com", STRONG)

    def test_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'autocomplete="new-password"')

    def test_correct_details_log_in_and_show_a_welcome(self):
        response = self.client.post(self.url, {"username": "ali.raza", "password": STRONG}, follow=True)
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertTrue(response.context["user"].is_authenticated)
        self.assertContains(response, "Welcome back, ali.raza.")

    def test_wrong_password_is_rejected(self):
        response = self.client.post(self.url, {"username": "ali.raza", "password": "wrong-password"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "don&#x27;t match")

    def test_unknown_user_and_wrong_password_give_the_same_message(self):
        # Different messages would let an attacker discover which usernames exist.
        wrong_pw = self.client.post(self.url, {"username": "ali.raza", "password": "nope"})
        no_user = self.client.post(self.url, {"username": "ghost", "password": "nope"})
        self.assertEqual(wrong_pw.context["form"].non_field_errors(), no_user.context["form"].non_field_errors())

    def test_switched_off_account_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {"username": "ali.raza", "password": STRONG})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 200)

    def test_next_on_this_site_is_followed(self):
        response = self.client.post(self.url + "?next=/dev/style-guide/", {"username": "ali.raza", "password": STRONG})
        self.assertRedirects(response, "/dev/style-guide/", fetch_redirect_response=False)

    def test_next_on_another_site_is_ignored(self):
        response = self.client.post(self.url + "?next=https://evil.example/", {"username": "ali.raza", "password": STRONG})
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_logged_in_users_are_sent_to_their_dashboard(self):
        self.client.login(username="ali.raza", password=STRONG)
        self.assertRedirects(self.client.get(self.url), reverse("core:dashboard"))

    def test_login_required_pages_send_people_here(self):
        from django.contrib.auth.decorators import login_required
        from django.http import HttpResponse
        from django.test import RequestFactory
        request = RequestFactory().get("/private/")
        request.user = type("Anon", (), {"is_authenticated": False})()
        response = login_required(lambda r: HttpResponse("secret"))(request)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(self.url))


@FAST_HASHER
class LogoutTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:logout")
        User.objects.create_user("ali.raza", "ali@example.com", STRONG)
        self.client.login(username="ali.raza", password=STRONG)

    def test_post_logs_out_and_says_so(self):
        response = self.client.post(self.url, follow=True)
        self.assertRedirects(response, reverse("core:home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "You have been logged out.")

    def test_get_is_not_allowed(self):
        # A plain link (or a hostile web page) must not be able to log someone out.
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)


@FAST_HASHER
class SecurityTests(TestCase):
    def test_csrf_protection_is_enforced_on_every_form(self):
        client = Client(enforce_csrf_checks=True)
        before = User.objects.count()
        for name, data in (("accounts:signup", signup_data()),
                           ("accounts:login", {"username": "x", "password": "y"}),
                           ("accounts:logout", {})):
            with self.subTest(page=name):
                self.assertEqual(client.post(reverse(name), data).status_code, 403)
        self.assertEqual(User.objects.count(), before)

    def test_forms_carry_a_csrf_token(self):
        for name in ("accounts:signup", "accounts:login"):
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name)), "csrfmiddlewaretoken")


@FAST_HASHER
class NavbarAndLinksTests(TestCase):
    def test_visitors_see_real_login_and_signup_links(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn(f'href="{reverse("accounts:login")}"', html)
        self.assertIn(f'href="{reverse("accounts:signup")}"', html)
        self.assertNotIn('data-soon="Log in"', html)
        self.assertNotIn('data-soon="Sign up"', html)

    def test_become_a_donor_buttons_lead_visitors_to_signup_then_the_donor_form(self):
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertNotIn('data-soon="Donor registration"', html)
        # hero button, call-to-action band and footer link
        after_signup = f'href="{reverse("accounts:signup")}?next={reverse("donors:edit")}"'
        self.assertGreaterEqual(html.count(after_signup), 3)

    def test_logged_in_users_see_their_name_as_one_link_to_the_dashboard(self):
        User.objects.create_user("ali.raza", "ali@example.com", STRONG)
        self.client.login(username="ali.raza", password=STRONG)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("ali.raza", html)
        self.assertIn(f'class="btn btn-outline-brand user-link" href="{reverse("core:dashboard")}"', html)
        # No menu under the name: the options live in the dashboard's side panel.
        self.assertNotIn("dropdown-menu", html)
        self.assertNotIn(f'action="{reverse("accounts:logout")}"', html)
        self.assertNotIn(f'href="{reverse("accounts:login")}" class="btn btn-ghost"', html)

    def test_the_post_logout_form_is_in_the_dashboard_panel(self):
        User.objects.create_user("ali.raza", "ali@example.com", STRONG)
        self.client.login(username="ali.raza", password=STRONG)
        html = self.client.get(reverse("core:dashboard")).content.decode()
        self.assertIn(f'action="{reverse("accounts:logout")}"', html)


class DialogFilterTests(SimpleTestCase):
    def test_title_and_text_are_split_on_the_first_line(self):
        message = "Account created\nWelcome, ali. Your account is ready."
        self.assertEqual(dialog_title(message), "Account created")
        self.assertEqual(dialog_text(message), "Welcome, ali. Your account is ready.")

    def test_message_without_a_second_line_has_empty_text(self):
        self.assertEqual(dialog_title("Just a title"), "Just a title")
        self.assertEqual(dialog_text("Just a title"), "")


class PasswordStorageTests(TestCase):
    """Uses Django's real, production password hashing (no FAST_HASHER on purpose)."""

    def test_password_is_stored_with_a_slow_salted_hash_never_as_typed(self):
        self.client.post(reverse("accounts:signup"), signup_data())
        user = User.objects.get(username="ali.raza")
        self.assertNotIn(STRONG, user.password)
        self.assertNotEqual(user.password, STRONG)
        self.assertTrue(user.check_password(STRONG))
        algorithm = identify_hasher(user.password).algorithm
        self.assertIn(algorithm, ("pbkdf2_sha256", "argon2", "scrypt", "bcrypt_sha256"))
        self.assertTrue(user.password.startswith(f"{algorithm}$"))

    def test_two_users_with_the_same_password_get_different_hashes(self):
        # Proves each hash is salted, so one cracked password does not reveal the others.
        one = User.objects.create_user("one", "one@example.com", STRONG)
        two = User.objects.create_user("two", "two@example.com", STRONG)
        self.assertNotEqual(one.password, two.password)


class GlassFormTests(TestCase):
    """Every form page sits on the glass backdrop; the login pages have no side panel."""

    def test_login_and_signup_are_a_single_glass_card_without_the_side_panel(self):
        for name in ("accounts:login", "accounts:signup"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('class="auth-wrap glass-page"', html)
            self.assertIn('class="orbs"', html)
            self.assertIn("auth-split", html)
            self.assertIn("Post. Match.", html)
            for gone in ("auth-card", "auth-single", "auth-aside", "auth-points", "mini-ecg", "One account, two ways to help"):
                self.assertNotIn(gone, html)

    def test_request_and_donor_forms_use_the_glass_backdrop(self):
        user = User.objects.create_user(username="glass", password=STRONG)
        self.client.force_login(user)
        for name in ("blood_requests:new", "donors:edit"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn("page-section glass-page", html, name)
            self.assertIn('class="orbs"', html, name)


@FAST_HASHER
class NothingLeftForTheNextPersonTests(TestCase):
    """After someone logs out, the next person on the same browser starts clean."""

    def setUp(self):
        User.objects.create_user("ali.raza", "ali@example.com", STRONG)

    def test_login_and_signup_forms_do_not_ask_the_browser_to_fill_in_old_details(self):
        for name in ("accounts:login", "accounts:signup"):
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertNotIn('autocomplete="username"', html)
                self.assertNotIn('autocomplete="current-password"', html)
                self.assertIn('autocomplete="off"', html)

    def test_login_and_signup_pages_are_never_cached(self):
        for name in ("accounts:login", "accounts:signup"):
            with self.subTest(page=name):
                self.assertIn("no-store", self.client.get(reverse(name))["Cache-Control"])

    def test_pages_made_for_a_signed_in_person_are_never_cached(self):
        self.client.login(username="ali.raza", password=STRONG)
        for name in ("core:dashboard", "blood_requests:mine", "core:home"):
            with self.subTest(page=name):
                self.assertIn("no-store", self.client.get(reverse(name))["Cache-Control"])

    def test_logout_ends_the_session_and_tells_the_browser_to_clear_its_cache(self):
        self.client.login(username="ali.raza", password=STRONG)
        response = self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response["Clear-Site-Data"], '"cache"')

    def test_the_forms_are_empty_for_the_next_visitor(self):
        self.client.login(username="ali.raza", password=STRONG)
        self.client.post(reverse("accounts:logout"))
        for name in ("accounts:login", "accounts:signup"):
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertNotIn('value="ali.raza"', html)
                self.assertNotIn("ali@example.com", html)
