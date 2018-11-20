from __future__ import print_function, unicode_literals
from datetime import datetime, timedelta
import random
import logging
from .db import Config, Caption, State
from .util import format_timedelta
from .slack import SlackException

LOG = logging.getLogger(__name__)

CAPTION_DURATION = timedelta(hours=8)
VOTE_DURATION = timedelta(hours=24)


def start_contest(request, channel, image):
    end_dt = datetime.utcnow() + CAPTION_DURATION
    config = Config.get_or_create(request.db, channel)

    file_id = image["id"]
    image_url = image["url_private"]
    if config.value.get("file_id") == file_id:
        LOG.info("Blocking duplicate contest start %s %s", channel, file_id)
        return

    LOG.info(
        "Detected image in message. Starting new caption contest in channel %s file %s uploaded at %s",
        channel,
        file_id,
        datetime.fromtimestamp(image["timestamp"]).isoformat(),
    )

    state = config.value.get("state")
    if state == State.voting:
        LOG.info("Ending previous vote before starting new contest")
        _end_voting(request, config)

    Config.start_contest(request.db, config, file_id, image_url, end_dt)
    Caption.clear_captions(request.db, channel)

    request.slack.post(
        channel,
        "<!channel> New caption contest! Submissions close in %s, and then voting begins! Polls will be open for %s (or until next contest start)"
        % (format_timedelta(CAPTION_DURATION), format_timedelta(VOTE_DURATION)),
        mrkdwn=True,
    )


def proceed_contest(request, channel):
    config = Config.get_config(request.db, channel)
    if config is None:
        LOG.warning("Cannot move contest forward on %s: empty config", channel)
        return
    state = config.value.get("state")
    if state == State.none:
        LOG.warning("Cannot move contest forward on %s: config state None", channel)
    elif state == State.captioning:
        _start_voting(request, config)
    elif state == State.voting:
        _end_voting(request, config)
    else:
        LOG.error("Config %s in bad state: %r. Clearing state...", channel, state)
        request.db.delete(config)


def _start_voting(request, config):
    captions = Caption.get_captions(request.db, config.channel)
    if not captions:
        LOG.info("Ending contest %s with no caption submissions", config.channel)
        Config.end_contest(request.db, config)
        return
    random.shuffle(captions)

    file_id = config.value["file_id"]
    image_url = config.value["image_url"]
    attachments = [{"text": file_id, "image_url": image_url}]
    for i, caption in enumerate(captions):
        attachments.append(
            {
                "text": caption.caption,
                "callback_id": file_id,
                "actions": [
                    {
                        "name": "vote",
                        "text": "Vote",
                        "type": "button",
                        "value": str(caption.id),
                        "mrkdwn_in": ["text"],
                    }
                ],
            }
        )

    resp = request.slack.post(
        config.channel,
        "Get out the vote! Polls are open for %s (or until next contest start)"
        % format_timedelta(VOTE_DURATION),
        attachments=attachments,
    )
    ts = resp["message"]["ts"]
    end_dt = datetime.utcnow() + VOTE_DURATION
    Config.start_voting(request.db, config, ts, end_dt)


def _end_voting(request, config):
    captions = Caption.get_captions_and_votes(request.db, config.channel)
    captions.sort(reverse=True)

    file_id = config.value["file_id"]
    image_url = config.value["image_url"]
    message = "*Caption results:*"
    for votes, caption in captions:
        if votes > 0:
            message += "\n%d - %s" % (votes, caption)
        else:
            message += "\n%s" % caption
    request.slack.post(
        config.channel,
        message,
        attachments=[{"text": file_id, "image_url": image_url}],
        mrkdwn=True,
    )

    message_ts = config.value["message_ts"]

    Caption.clear_captions(request.db, config.channel)
    Config.end_contest(request.db, config)

    try:
        request.slack.delete(config.channel, message_ts)
    except SlackException:
        pass
