"""Small display helpers used only by the admin panel templates."""

from datetime import timedelta

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def blood_mark(value):
    """'AB-' -> AB<i>-</i>, with a real minus sign.

    The sign goes in its own element so CSS can raise and shrink it, which is
    what makes the mark read as a label on a blood bag rather than as text. The
    letters are escaped, so a stray value in the database cannot inject markup.
    """
    text = str(value or "")
    if not text:
        return ""
    letters, sign = text[:-1], text[-1]
    if sign not in "+-":
        return escape(text)
    return format_html("{}<i>{}</i>", letters, "−" if sign == "-" else "+")


@register.filter
def duration(value):
    """A timedelta as one coarse unit: '4 hours', '3 days', 'under a minute'.

    One unit only, because this is read at a glance to answer "is the backlog
    hours old or days old?" - "3 days, 4 hours, 11 minutes" answers it worse.
    """
    if value is None:
        return ""
    seconds = int(value.total_seconds())
    if seconds < 60:
        return "under a minute"
    for amount, name in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= amount:
            count = seconds // amount
            return f"{count} {name}{'s' if count != 1 else ''}"
    return "under a minute"


@register.filter
def age(value):
    """How long since a moment, with no "ago" on the end.

    core_extras.time_ago adds "ago", which reads wrong after a preposition:
    "live for 4 hours ago". This is the same one-unit span without it.
    """
    if value is None:
        return ""
    from django.utils import timezone
    from django.utils.timesince import timesince

    if timezone.now() - value < timedelta(minutes=1):
        return "under a minute"
    return timesince(value, depth=1)


@register.filter
def initials(user):
    """Two letters for the little circle at the foot of the side panel."""
    name = (getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "") or "?").strip()
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (parts[0][:2] if parts else "?").upper()


@register.simple_tag
def querystring_with(request, **kwargs):
    """The current query string with some keys replaced.

    Lets a filter tab keep the search box's text, and the search box keep the
    chosen tab, without either having to know about the other.
    """
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return mark_safe(f"?{encoded}" if encoded else "")
