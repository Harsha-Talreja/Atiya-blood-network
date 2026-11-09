"""Words that reach the screen through a variable, not straight from a template.

A template can translate its own text with {% trans %}. But a status such as
"Fulfilled", or a title handed to a shared component, arrives as a plain
string. The `tr` template filter (core/templatetags/core_extras.py) translates
those at the moment they are shown.

Nothing here changes what is stored: the database keeps the English words, and
the code keeps comparing against them. Only the text on the screen changes.

`N` marks a string for the translation catalogue without translating it yet
(Django calls this "noop"). The list is the catalogue's way of knowing these
words exist, since no template contains them literally.
"""
from django.utils.translation import gettext_noop as N

WORDS = (
    # urgency
    N("Normal"), N("Urgent"), N("Critical"),
    # request status
    N("Pending"), N("Fulfilled"), N("Expired"), N("Rejected"),
    # report reasons (the stored value is the English phrase)
    N("Fake or hoax"), N("Already fulfilled elsewhere"), N("Spam or advertising"),
    N("Inappropriate content"), N("Other"),
    # labels kept in core/constants.py
    N("Admin released \u2014 not hospital verified."),
    N("Admin approved \u2014 not hospital verified."),
    # strings passed into shared components
    N("Nothing waiting"),
    N("No matching requests"),
    N("Try a different blood type or city."),
    N("Post request"),
    N("Log in"),
    N("Create account"),
    N("No matching requests right now"),
    N("No donors found"),
    N("Search to see donors"),
    N("Choose a blood type, a city, or both, to see available donors."),
    N("No open requests right now"),
    N("No donors registered yet"),
    N("Become a donor"),
    N("When someone posts a request it appears here first."),
    N("Save"),
)
