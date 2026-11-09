"""One-line helpers for messages shown after a redirect."""
from django.contrib import messages

DIALOG_TAG = "dialog"


def success_dialog(request, title, text):
    """Queue a celebratory pop-up (animated check mark) for the next page.

    The title and text travel together as "title\\ntext"; the messages partial splits them.
    """
    messages.success(request, f"{title}\n{text}", extra_tags=DIALOG_TAG)
