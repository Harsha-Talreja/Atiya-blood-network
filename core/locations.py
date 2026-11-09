"""Helpers for showing areas grouped by city."""
from core.models import Location


def grouped_locations():
    """[(city, [Location, ...]), ...] with cities in A-Z order and 'Other' always last in each city."""
    groups = {}
    for location in Location.objects.order_by("city", "area"):
        groups.setdefault(location.city, []).append(location)
    for areas in groups.values():
        areas.sort(key=lambda loc: (loc.area == "Other", loc.area))
    return sorted(groups.items())


def city_names():
    return [city for city, _ in grouped_locations()]
