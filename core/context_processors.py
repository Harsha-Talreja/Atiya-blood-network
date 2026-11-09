from django.conf import settings


def site(request):
    """Make SITE_NAME available in every template as {{ SITE_NAME }}."""
    return {"SITE_NAME": settings.SITE_NAME}


def desk_only(request):
    """True for an admin or a hospital account: they only use their own desk.

    Templates use this to leave out the "Request blood" and "Become a donor"
    buttons, which are for ordinary accounts.
    """
    user = getattr(request, "user", None)
    on_desk = bool(
        user is not None
        and user.is_authenticated
        and (user.is_staff or getattr(user, "hospital_account", None) is not None)
    )
    return {"desk_only": on_desk}
