# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
from datetime import datetime, timedelta
import random
import logging
from .db import Config, Caption
from .util import format_timedelta

LOG = logging.getLogger(__name__)

DURATION = timedelta(hours=8)

EMOJIS = [
    ("one", "1"),
    ("two", "2"),
    ("three", "3"),
    ("four", "4"),
    ("five", "5"),
    ("six", "6"),
    ("seven", "7"),
    ("eight", "8"),
    ("nine", "9"),
    ("keycap_ten", "10"),
    ("heart_eyes", "😍"),
    ("stuck_out_tongue", "😛"),
    ("money_mouth_face", "🤑"),
    ("zany_face", "🤪"),
    ("no_mouth", "😶"),
    ("fox_face", "🦊"),
    ("unicorn_face", "🦄"),
    ("monkey_face", "🐵"),
    ("heart", "❤"),
    ("clown_face", "🤡"),
]


def start_contest(request, channel, image):
    end_dt = datetime.utcnow() + DURATION
    if not Config.start_contest(
        request.db, channel, image["id"], image["url_private"], end_dt
    ):
        LOG.info("Blocking duplicate contest start %s %s", channel, image["id"])
        return
    LOG.info(
        "Detected file in message. Starting new caption contest in channel %s file %s uploaded at %s",
        channel,
        image["id"],
        datetime.fromtimestamp(image["timestamp"]).isoformat(),
    )

    request.slack.post(
        channel,
        "<!channel> New caption contest! Submit your captions using the `/caption` command. Polls will open in %s"
        % format_timedelta(DURATION),
        mrkdwn=True,
    )


def finish_contest(request, channel):
    captions = Caption.get_captions(request.db, channel)
    Caption.clear_captions(request.db, channel)
    data = Config.end_contest(request.db, channel)
    if not data:
        LOG.info("Trying to end contest in %s, but none ongoing", channel)
        return
    if not captions:
        LOG.info("Ending contest %s with no caption submissions", channel)
        return
    random.shuffle(captions)
    text = "\n".join(
        ["%s. %s" % (e[1], caption) for (e, caption) in zip(EMOJIS, captions)]
    )
    LOG.info("Ending contest %s:\n%s", channel, text)
    resp = request.slack.post(
        channel,
        text,
        mrkdwn=True,
        attachments=[{"text": data["file_id"], "image_url": data["image_url"]}],
    )
    ts = resp["message"]["ts"]
    for i in range(len(captions)):
        request.slack.add_reaction(channel, ts, EMOJIS[i][0])
