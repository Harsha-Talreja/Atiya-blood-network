"""A small line chart, worked out in Python rather than in the template.

The template only drops finished strings into an <svg>. Doing the arithmetic
here means the shape can be tested, and a day with no requests cannot quietly
disappear from the line: every day in the window is produced, including zeros.

The chart is drawn in its own coordinate space (VIEW_W x VIEW_H) and scaled by
CSS, so it stays sharp at any size and needs no JavaScript.
"""

from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

VIEW_W, VIEW_H = 300, 92
PAD_X, TOP, BASE = 10, 12, 70   # the plotting area inside the view box


def requests_per_day(queryset, days=7):
    """Count rows per day over the last `days`, and the geometry to draw them.

    `queryset` is any BloodRequest queryset; it is filtered by created_at here
    so the caller does not have to repeat the window.
    """
    days = max(2, int(days))
    today = timezone.localdate()
    first = today - timedelta(days=days - 1)

    counted = (
        queryset.filter(created_at__date__gte=first)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"))
    )
    by_day = {row["day"]: row["total"] for row in counted}

    series = [
        {"date": first + timedelta(days=i),
         "count": by_day.get(first + timedelta(days=i), 0)}
        for i in range(days)
    ]

    biggest = max((d["count"] for d in series), default=0)
    span = VIEW_W - 2 * PAD_X
    step = span / (days - 1)

    for i, day in enumerate(series):
        day["x"] = round(PAD_X + i * step, 2)
        # An all-zero week would divide by zero; it draws as a flat baseline.
        share = (day["count"] / biggest) if biggest else 0
        day["y"] = round(BASE - share * (BASE - TOP), 2)
        day["label"] = day["date"].strftime("%a")

    line = " ".join(
        ("M" if i == 0 else "L") + f"{d['x']} {d['y']}" for i, d in enumerate(series)
    )
    area = f"{line} L{series[-1]['x']} {BASE} L{series[0]['x']} {BASE} Z"

    return {
        "days": series,
        "max": biggest,
        "total": sum(d["count"] for d in series),
        "line": line,
        "area": area,
        "baseline": BASE,
        "width": VIEW_W,
        "height": VIEW_H,
        # Used to animate the line drawing itself in: a generous upper bound on
        # the path length is fine, since the dash offset only has to start off
        # the end of the line.
        "length": int(span * 2),
    }
