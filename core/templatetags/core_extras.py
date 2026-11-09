from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.html import json_script
from django.utils.translation import get_language, gettext, ngettext

register = template.Library()


# Django's message tags, mapped to the toast's look. A tag string can hold
# more than one word ("success dialog"), so the lookup walks the words and
# takes the first one it recognises rather than matching the whole string.
TOAST_KINDS = {
    "success": ("is-good", "bi-check-circle-fill"),
    "error": ("is-bad", "bi-exclamation-octagon-fill"),
    "warning": ("is-warn", "bi-exclamation-triangle-fill"),
    "info": ("is-info", "bi-info-circle-fill"),
    "debug": ("is-info", "bi-info-circle-fill"),
}
TOAST_DEFAULT = TOAST_KINDS["info"]


def _toast_style(tags):
    for word in (tags or "").split():
        if word in TOAST_KINDS:
            return TOAST_KINDS[word]
    return TOAST_DEFAULT


@register.filter
def toast_kind(tags):
    """'success' -> 'is-good'. Picks the toast's colour class from the tags."""
    return _toast_style(tags)[0]


@register.filter
def toast_icon(tags):
    """'success' -> 'bi-check-circle-fill'. Picks the toast's icon."""
    return _toast_style(tags)[1]


@register.filter
def initials(name):
    """'Ayesha Noor' -> 'AN'. Falls back to one letter, or '?' for a blank."""
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


@register.filter
def avatar_tint(value):
    """Spread avatars over the three tints so a list is not one block of pink.
    Driven by the record's id, so the same person keeps the same colour."""
    try:
        n = int(value) % 3
    except (TypeError, ValueError):
        n = 0
    return ("", "tint-2", "tint-3")[n]


@register.filter
def pretty_blood(value):
    """Display helper: 'O-' -> 'O−' (a real minus sign). Never used for storing data."""
    text = str(value)
    return text[:-1] + "\u2212" if text.endswith("-") else text


@register.filter
def tr(value):
    """Translate a word that arrives as a variable, e.g. {{ status|tr }}.

    Words reach here from code (core/vocab.py lists them for the catalogue). An
    empty or missing value stays empty; a word with no translation stays as it is.
    """
    if value is None or value == "":
        return ""
    return gettext(str(value))


# Unit names for the "2 hours ago" style spans. Django's own timesince gives
# English words, so the spans are built here from a number and a translated unit.
_UNITS = (
    (365 * 86400, lambda n: ngettext("%(n)d year", "%(n)d years", n)),
    (30 * 86400, lambda n: ngettext("%(n)d month", "%(n)d months", n)),
    (7 * 86400, lambda n: ngettext("%(n)d week", "%(n)d weeks", n)),
    (86400, lambda n: ngettext("%(n)d day", "%(n)d days", n)),
    (3600, lambda n: ngettext("%(n)d hour", "%(n)d hours", n)),
    (60, lambda n: ngettext("%(n)d minute", "%(n)d minutes", n)),
)


def _span(delta):
    """A timedelta as one translated unit: '2 hours', 'under a minute'."""
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return gettext("under a minute")
    for size, label in _UNITS:
        if seconds >= size:
            n = seconds // size
            return label(n) % {"n": n}
    return gettext("under a minute")


@register.filter
def time_ago(value):
    """'just now' or one unit only, e.g. '2 hours ago' (Django's default shows two units)."""
    if value is None:
        return ""
    delta = timezone.now() - value
    if delta < timedelta(minutes=1):
        return gettext("just now")
    return gettext("%(span)s ago") % {"span": _span(delta)}


@register.filter
def time_left(value):
    """Time until a deadline, one unit only, e.g. '23 hours'."""
    if value is None:
        return ""
    return _span(value - timezone.now())


@register.filter
def dialog_title(message):
    """The headline of a success_dialog() message: the part before the first newline."""
    return str(message).split("\n", 1)[0]


@register.filter
def dialog_text(message):
    """The body of a success_dialog() message: the part after the first newline, or '' if none."""
    parts = str(message).split("\n", 1)
    return parts[1] if len(parts) > 1 else ""


@register.filter
def as_input(field):
    """Render a form field with the right Bootstrap classes, invalid state and ARIA links.

    Usage in a template:  {{ field|as_input }}
    Keeps any attributes already set on the widget (placeholder, pattern, data-*, ...).
    """
    widget = field.field.widget
    kind = widget.__class__.__name__
    if kind in ("Select", "SelectMultiple"):
        css = "form-select"
    elif kind == "CheckboxInput":
        css = "form-check-input"
    else:
        css = "form-control"

    attrs = {}
    described_by = []
    if field.help_text:
        described_by.append(f"{field.id_for_label}-hint")
    if field.errors:
        css += " is-invalid"
        attrs["aria-invalid"] = "true"
        described_by.append(f"{field.id_for_label}-error")
    attrs["class"] = css
    if described_by:
        attrs["aria-describedby"] = " ".join(described_by)
    return field.as_widget(attrs=attrs)


@register.simple_tag
def live_request_count():
    """How many requests donors can see right now, for the navbar badge.

    The same queryset the home page and the public board use, so the number in
    the navbar always matches the list it links to. Imported here, not at the
    top, so loading the template library never pulls in the requests app first.
    """
    from django.core.cache import caches

    from blood_requests.selectors import open_requests

    # Every page shows this number, so it is remembered for 20 seconds instead of
    # being counted again on each click.
    return caches["snap"].get_or_set("bn:open-count", lambda: open_requests().count(), 20)


def _js_strings():
    """The sentences main.js and notifications.js put on the screen, in the
    reader's language. Each key is the English text the script already holds, so
    a missing key simply leaves English in place."""
    return {
        "Dismiss this message": gettext("Dismiss this message"),
        "Switch to light mode": gettext("Switch to light mode"),
        "Switch to dark mode": gettext("Switch to dark mode"),
        "Closes in ": gettext("Closes in "),
        "Closed": gettext("Closed"),
        "Done": gettext("Done"),
        "Hide password": gettext("Hide password"),
        "Show password": gettext("Show password"),
        "Steps": gettext("Steps"),
        "Back": gettext("Back"),
        "Next": gettext("Next"),
        "Please wait...": gettext("Please wait..."),
        "(required)": gettext("(required)"),
        "(optional)": gettext("(optional)"),
        "Open the side panel": gettext("Open the side panel"),
        "Fold the side panel": gettext("Fold the side panel"),
        "Please confirm": gettext("Please confirm"),
        "Close": gettext("Close"),
        "Cancel": gettext("Cancel"),
        "Yes, continue": gettext("Yes, continue"),
        "Notifications": gettext("Notifications"),
        "Notifications, %(n)s unread": gettext("Notifications, %(n)s unread"),
        "%(d)sd %(h)sh": gettext("%(d)sd %(h)sh"),
        "%(h)sh %(m)sm": gettext("%(h)sh %(m)sm"),
        "%(m)sm %(s)ss": gettext("%(m)sm %(s)ss"),
        "%(units)s units is more than %(limit)s. An admin has to approve this request before donors can see it, so please explain why this much blood is needed.":
            gettext("%(units)s units is more than %(limit)s. An admin has to approve this request before donors can see it, so please explain why this much blood is needed."),
        "A patient with %(type)s blood can receive red blood cells from: %(list)s.":
            gettext("A patient with %(type)s blood can receive red blood cells from: %(list)s."),
        " (%(n)s of %(total)s types)": gettext(" (%(n)s of %(total)s types)"),
        " O\u2212 patients can only receive O\u2212.": gettext(" O\u2212 patients can only receive O\u2212."),
        " AB+ is the universal recipient.": gettext(" AB+ is the universal recipient."),
    }


@register.simple_tag
def js_i18n():
    """A JSON block the scripts read their wording from.

    English pages get nothing at all: the scripts already hold the English
    text, so the default language pays no extra bytes.
    """
    if (get_language() or "en").startswith("en"):
        return ""
    return json_script(_js_strings(), "bn-i18n")
