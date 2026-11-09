"""Urdu and Sindhi: the language switch, right-to-left pages, and the catalogues.

The site keeps English as its default. These tests protect the three promises of
the language feature: English pages pay nothing extra, Urdu and Sindhi pages are
complete and flipped right-to-left, and the admin panel stays English.
"""
import gettext as stdlib_gettext
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import engines
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from core.templatetags.core_extras import _js_strings, time_ago, time_left, tr
from core.vocab import WORDS

User = get_user_model()
BASE = Path(settings.BASE_DIR)


def page(url, lang=None, client=None):
    client = client or Client()
    if lang:
        client.cookies[settings.LANGUAGE_COOKIE_NAME] = lang
    return client.get(url)


class EveryTemplateStillCompilesTests(SimpleTestCase):
    def test_all_templates_compile(self):
        engine = engines["django"]
        names = sorted(str(p.relative_to(BASE / "templates")) for p in (BASE / "templates").rglob("*.html"))
        self.assertGreater(len(names), 50)
        for name in names:
            with self.subTest(template=name):
                engine.get_template(name)


class LanguageSwitchTests(TestCase):
    def test_english_is_the_default_and_left_to_right(self):
        html = page(reverse("core:about")).content.decode()
        self.assertIn('lang="en"', html)
        self.assertIn('dir="ltr"', html)

    def test_english_pages_load_no_right_to_left_files_and_no_script_table(self):
        html = page(reverse("core:home")).content.decode()
        self.assertNotIn("theme.rtl.css", html)
        self.assertNotIn("lang-rtl.css", html)
        self.assertNotIn("bootstrap.rtl.min.css", html)
        self.assertNotIn('id="bn-i18n"', html)

    def test_urdu_and_sindhi_pages_are_right_to_left_with_their_own_files(self):
        for lang in ("ur", "sd"):
            with self.subTest(lang=lang):
                html = page(reverse("core:home"), lang).content.decode()
                self.assertIn(f'lang="{lang}"', html)
                self.assertIn('dir="rtl"', html)
                self.assertIn("theme.rtl.css", html)
                self.assertIn("lang-rtl.css", html)
                self.assertIn("bootstrap.rtl.min.css", html)
                self.assertIn('id="bn-i18n"', html)
                # The left-to-right sheets are not loaded as well.
                self.assertNotIn("bootstrap.min.css", html)
                self.assertNotIn("css/theme.css", html)

    def test_the_switcher_posts_to_django_and_remembers_the_choice(self):
        client = Client()
        reply = client.post(reverse("set_language"), {"language": "ur", "next": reverse("core:about")})
        self.assertRedirects(reply, reverse("core:about"), fetch_redirect_response=False)
        self.assertEqual(client.cookies[settings.LANGUAGE_COOKIE_NAME].value, "ur")
        html = client.get(reverse("core:about")).content.decode()
        self.assertIn('dir="rtl"', html)
        client.post(reverse("set_language"), {"language": "en", "next": reverse("core:about")})
        self.assertIn('dir="ltr"', client.get(reverse("core:about")).content.decode())

    def test_an_unknown_language_is_ignored(self):
        html = page(reverse("core:about"), "fr").content.decode()
        self.assertIn('lang="en"', html)

    def test_browser_language_header_does_not_change_the_site(self):
        html = Client(HTTP_ACCEPT_LANGUAGE="ur").get(reverse("core:about")).content.decode()
        self.assertIn('lang="en"', html)

    def test_the_switcher_lists_all_three_languages(self):
        html = page(reverse("core:home")).content.decode()
        for name in ("English", "اردو", "سنڌي"):
            self.assertIn(name, html)
        self.assertIn('data-lang-select', html)

    def test_responses_vary_on_the_cookie_so_caches_cannot_mix_languages(self):
        reply = page(reverse("core:home"), "ur")
        self.assertIn("Cookie", reply.get("Vary", ""))
        self.assertEqual(reply["Content-Language"], "ur")

    def test_the_admin_panel_stays_in_english(self):
        staff = User.objects.create_user("tmp_staff_i18n", password="pw12345", is_staff=True)
        client = Client()
        client.force_login(staff)
        client.cookies[settings.LANGUAGE_COOKIE_NAME] = "ur"
        reply = client.get(reverse("siteadmin:overview"))
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply["Content-Language"], "en")
        self.assertNotIn('dir="rtl"', reply.content.decode())


class PagesRenderInEveryLanguageTests(TestCase):
    def test_public_pages_render_in_each_language(self):
        urls = [reverse(n) for n in ("core:home", "core:about", "accounts:login", "accounts:signup", "blood_requests:list")]
        for lang in ("en", "ur", "sd"):
            for url in urls:
                with self.subTest(lang=lang, url=url):
                    self.assertEqual(page(url, lang).status_code, 200)

    def test_a_missing_page_is_translated_too(self):
        html = page("/no-such-page/", "ur").content.decode()
        self.assertIn("صفحہ نہیں ملا", html)

    def test_translated_pages_show_translated_words(self):
        self.assertIn("لاگ اِن", page(reverse("accounts:login"), "ur").content.decode())
        self.assertIn("لاگ ان", page(reverse("accounts:login"), "sd").content.decode())

    def test_signed_in_pages_render_in_each_language(self):
        user = User.objects.create_user("tmp_reader_i18n", password="pw12345")
        for lang in ("ur", "sd"):
            client = Client()
            client.force_login(user)
            client.cookies[settings.LANGUAGE_COOKIE_NAME] = lang
            for name in ("core:dashboard", "donors:edit", "donors:profile", "blood_requests:new", "blood_requests:mine", "donors:search"):
                with self.subTest(lang=lang, url=name):
                    reply = client.get(reverse(name))
                    self.assertIn(reply.status_code, (200, 302))


class WordsFromCodeTests(SimpleTestCase):
    def test_time_spans_are_translated(self):
        with translation.override("ur"):
            self.assertEqual(time_ago(timezone.now() - timedelta(hours=2, minutes=30)), "2 گھنٹے پہلے")
            self.assertEqual(time_ago(timezone.now() - timedelta(seconds=5)), "ابھی ابھی")
            self.assertEqual(time_left(timezone.now() + timedelta(days=3, hours=1)), "3 دن")
        with translation.override("sd"):
            self.assertEqual(time_ago(timezone.now() - timedelta(hours=2, minutes=30)), "2 ڪلاڪ اڳ")

    def test_stored_words_stay_english_but_show_translated(self):
        self.assertEqual(tr("Critical"), "Critical")
        with translation.override("ur"):
            self.assertEqual(tr("Critical"), "ہنگامی")
            self.assertEqual(tr(""), "")
            self.assertEqual(tr(None), "")
            self.assertEqual(tr("Some word nobody translated"), "Some word nobody translated")

    def test_every_listed_word_has_an_urdu_and_a_sindhi_translation(self):
        for lang in ("ur", "sd"):
            with translation.override(lang):
                for word in WORDS:
                    with self.subTest(lang=lang, word=word):
                        self.assertNotEqual(translation.gettext(word), word)


class CatalogueTests(SimpleTestCase):
    """The compiled files are what the site reads, so these test them directly."""

    PLACEHOLDER = re.compile(r"%\((\w+)\)[sd]")

    def catalogue(self, lang):
        path = BASE / "locale" / lang / "LC_MESSAGES" / "django.mo"
        self.assertTrue(path.exists(), f"missing {path}; compile the catalogue")
        with open(path, "rb") as handle:
            return stdlib_gettext.GNUTranslations(handle)._catalog

    def test_every_message_keeps_its_placeholders(self):
        for lang in ("ur", "sd"):
            for key, text in self.catalogue(lang).items():
                if not key:
                    continue
                msgid = key[0] if isinstance(key, tuple) else key
                if not isinstance(msgid, str) or not text:
                    continue
                with self.subTest(lang=lang, msgid=msgid[:60]):
                    want = set(self.PLACEHOLDER.findall(msgid))
                    got = set(self.PLACEHOLDER.findall(text))
                    # A plural form may drop the number in a language that does not need it.
                    self.assertTrue(got <= want, f"unknown placeholder in {text!r}")
                    if not isinstance(key, tuple):
                        self.assertEqual(got, want, f"placeholders differ in {text!r}")

    def test_the_two_catalogues_cover_the_same_messages(self):
        self.assertEqual(set(self.catalogue("ur")), set(self.catalogue("sd")))

    def test_catalogues_are_large_enough_to_be_real(self):
        for lang in ("ur", "sd"):
            self.assertGreater(len(self.catalogue(lang)), 600)

    def test_script_wording_table_is_translated_and_complete(self):
        script = (BASE / "static" / "js" / "main.js").read_text(encoding="utf-8")
        notes = (BASE / "static" / "js" / "notifications.js").read_text(encoding="utf-8")
        used = set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"\)', script)) | set(re.findall(r'\bsay\("((?:[^"\\]|\\.)*)"', notes))
        # Strings written with \u escapes in the script appear as real characters in the table.
        used = {u.encode().decode("unicode_escape") if "\\u" in u else u for u in used}
        used.discard("English text")   # the example in the comment that explains t()
        with translation.override("sd"):
            table = _js_strings()
        for text in used:
            with self.subTest(text=text[:50]):
                self.assertIn(text, table)
                self.assertNotEqual(table[text], text)


class RightToLeftStyleSheetTests(SimpleTestCase):
    def test_the_flipped_sheet_was_regenerated_after_the_last_theme_edit(self):
        css = BASE / "static" / "css"
        original = (css / "theme.css").read_text(encoding="utf-8")
        flipped = (css / "theme.rtl.css").read_text(encoding="utf-8")
        # rtlcss only swaps left and right, so the number of rules never changes.
        # If this fails, theme.css was edited without regenerating theme.rtl.css
        # (npx rtlcss static/css/theme.css static/css/theme.rtl.css).
        self.assertEqual(original.count("{"), flipped.count("{"))
        self.assertEqual(original.count("}"), flipped.count("}"))
        self.assertIn(".lang-select", flipped)

    def test_the_arabic_script_font_is_bundled_not_fetched(self):
        css = (BASE / "static" / "css" / "lang-rtl.css").read_text(encoding="utf-8")
        self.assertNotIn("http", css)
        for name in re.findall(r'url\("\.\./vendor/([^"]+)"\)', css):
            self.assertTrue((BASE / "static" / "vendor" / name).exists(), name)
