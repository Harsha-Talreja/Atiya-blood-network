"""Puts the unread count in every template so the bell is right on first paint."""
from django.utils.functional import SimpleLazyObject

from notifications.services import unread_count


def unread(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    # Lazy: the query only runs on pages whose template actually shows the bell.
    return {"unread_notifications": SimpleLazyObject(lambda: unread_count(user))}
