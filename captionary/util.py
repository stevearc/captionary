from __future__ import unicode_literals
from math import floor


def format_timedelta(dt):
    msg = ""
    remainder = dt.seconds
    days = floor(remainder / 3600 / 24)
    remainder -= days * 3600 * 24
    hours = floor(remainder / 3600)
    remainder -= hours * 3600
    minutes = floor(remainder / 60)
    if days > 0:
        msg += " %d day%s" % (days, "s" if days > 1 else "")
    if hours > 0:
        msg += " %d hour%s" % (hours, "s" if hours > 1 else "")
    if minutes > 0:
        msg += " %d minute%s" % (minutes, "s" if minutes > 1 else "")
    return msg.strip()
