""" Views """
from __future__ import print_function, unicode_literals
import logging
import traceback
import json
from datetime import datetime
from pyramid_duh import argify
from pyramid.httpexceptions import HTTPException, HTTPNotFound
from pyramid.settings import asbool
from pyramid.view import view_config
from .actions import start_contest, proceed_contest
from .db import Config, Caption, Vote, State
from .util import format_timedelta


LOG = logging.getLogger(__name__)
HELP = """Hello! I am a caption contest bot.
1. You can start a new caption contest by uploading a photo in a channel that I'm in
2. People can submit captions with `/caption`
3. I'll post everyone's submissions and you can vote on the best ones!"""


@view_config(route_name="event", renderer="json")
def handle_event(request):
    if "challenge" in request.json_body:
        request.response.text = request.json_body["challenge"]
        return request.response
    if "event" in request.json_body:
        return handle_slack_event(request, request.json_body["event"])
    return {}


def handle_slack_event(request, event):
    if event["type"] == "message":
        if event["channel_type"] == "im":
            handle_im(request, event)
        elif event.get("files"):
            check_for_image(request, event)


def handle_im(request, event):
    text = event["text"]
    if event.get("subtype") == "bot_message":
        return
    request.slack.post(event["channel"], HELP)


def check_for_image(request, event):
    image = None
    for file in event["files"]:
        if file["filetype"] in ("png", "jpg", "jpeg"):
            image = file
            break
    if image is None:
        return
    channel = event["channel"]
    start_contest(request, channel, image)


@view_config(route_name="command", renderer="json")
@argify
def handle_command(request, command, text, channel_id):
    channel = channel_id
    if command == "/caption":
        response = debug_command(request, channel, text)
        if response is not None:
            request.response.text = response
            return request.response
        state = Config.get_contest_state(request.db, channel)
        if state != State.captioning:
            request.response.text = "Not accepting captions right now, thx"
            return request.response
        LOG.info("Adding a submission to channel %s: %s", channel, text)
        Caption.add_submission(request.db, channel, text)
        return {"text": "_" + text + "_", "mrkdwn": True}
    return HTTPNotFound("Unrecognized command %s" % command)


def debug_command(request, channel, text):
    if text == "we done":
        proceed_contest(request, channel)
        return ""
    elif text in ("debug", "status"):
        config = Config.get_config(request.db, channel)
        if config is None:
            return "Not much going on atm"
        state = config.value.get("state")
        now = datetime.utcnow()
        message = "State: %s" % state
        if "end" in config.value:
            end_dt = datetime.utcfromtimestamp(config.value.get("end"))
        if state == State.captioning:
            message += "\nVoting starts in " + format_timedelta(end_dt - now)
            captions = Caption.get_captions(request.db, channel)
            message += "\n%d captions submitted" % len(captions)
        elif state == State.voting:
            message += "\nVoting closes in " + format_timedelta(end_dt - now)
            captions = Caption.get_captions_and_votes(request.db, channel)
            captions.sort(reverse=True)
            for count, caption in captions:
                message += "\n%s - %s" % (count, caption)

        return message


@view_config(route_name="vote", renderer="json")
@argify
def handle_vote(request, payload):
    payload = json.loads(payload)
    file_id = payload["callback_id"]
    channel = payload["channel"]["id"]
    user = payload["user"]["id"]
    vote = payload["actions"][0]["value"]
    Vote.toggle_vote(request.db, user, int(vote))
    votes = Caption.get_votes(request.db, user, channel)
    text = "*Your votes:*\n" + "\n".join([vote.caption for vote in votes])
    request.slack.post_ephemeral(channel, user, text, mrkdwn=True)
    return request.response


@view_config(context=Exception, renderer="json")
@view_config(context=HTTPException, renderer="json")
def format_exception(context, request):
    """
    Catch all app exceptions and render them nicely

    This will keep the status code, but will always return parseable json

    Returns
    -------
    error : str
        Identifying error key
    message : str
        Human-readable error message
    stacktrace : str, optional
        If pyramid.debug = true, also return the stacktrace to the client

    """
    message = context.message if hasattr(context, "message") else str(context)
    LOG.exception(message)
    error = {"error": getattr(context, "error", "unknown"), "message": message}
    if asbool(request.registry.settings.get("pyramid.debug", False)):
        error["stacktrace"] = traceback.format_exc()
    request.response.status_code = getattr(context, "status_code", 500)
    return error
