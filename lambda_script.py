# -*- coding: utf-8 -*-
import json
import random
import boto3
from datetime import datetime, timedelta
import botocore
import os
import requests
import dynamo3
from urllib.parse import parse_qsl

# TODO:
# * debug info (ongoing contests, end times, current submission count, etc.)
# * configure the contest duration

TABLE_NAME = "CaptionarySubmissions"
OAUTH_TOKEN = os.environ["OAUTH_TOKEN"]
HELP = """Hello! I am a caption contest bot.
1. You can start a new caption contest by uploading a photo in a channel that I'm in
2. People can submit captions with `/caption`
3. I'll post everyone's submissions and you can vote on the best ones!"""

DURATION = timedelta(hours=8, minutes=0)

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


class Connections(object):
    def __init__(self):
        self._dynamo = None
        self._events = None
        self._lam = None
        self.context = None

    @property
    def dynamo(self):
        if self._dynamo is None:
            client = botocore.session.get_session().create_client("dynamodb")
            self._dynamo = dynamo3.DynamoDBConnection(client)
        return self._dynamo

    @property
    def events(self):
        if self._events is None:
            self._events = boto3.client("events")
        return self._events

    @property
    def lam(self):
        if self._lam is None:
            self._lam = boto3.client("lambda")
        return self._lam

    def add_submission(self, channel, text):
        item = {"channel": channel, "text": text}
        self.dynamo.put_item2(TABLE_NAME, item)

    def get_and_clear_submissions(self, channel):
        items = self.get_submissions(channel)
        with self.dynamo.batch_write(TABLE_NAME) as writer:
            for item in items:
                writer.delete(item)
        return items

    def get_submissions(self, channel):
        return list(
            self.dynamo.query2(TABLE_NAME, "channel = :channel", channel=channel)
        )

    def clear_callback(self, channel):
        name = self.get_callback_name(channel)

        # Clear targets of rule
        try:
            rule = self.events.describe_rule(Name=name)
            targets = self.events.list_targets_by_rule(Rule=name)
            if targets.get("Targets"):
                self.events.remove_targets(
                    Rule=name, Ids=[target["Id"] for target in targets["Targets"]]
                )
            self.events.delete_rule(Name=name)
        except self.events.exceptions.ResourceNotFoundException:
            pass

        # Clear lambda trigger
        try:
            self.lam.remove_permission(
                FunctionName=self.context.function_name, StatementId=name
            )
        except self.lam.exceptions.ResourceNotFoundException:
            pass

    def get_callback_name(self, channel):
        return "Captionary_End_Competition_" + channel

    def set_callback(self, channel):
        self.clear_callback(channel)

        expire = datetime.utcnow() + DURATION
        cron = "cron(%s %s %s %s ? %s)" % (
            expire.minute,
            expire.hour,
            expire.day,
            expire.month,
            expire.year,
        )
        print("Scheduling " + cron)
        name = self.get_callback_name(channel)

        rule = self.events.put_rule(
            Name=name,
            ScheduleExpression=cron,
            State="ENABLED",
            Description="Post all the caption submissions to the thread",
        )
        self.events.put_targets(
            Rule=name,
            Targets=[
                {
                    "Id": self.context.function_name,
                    "Arn": self.context.invoked_function_arn,
                    "Input": json.dumps(
                        {
                            "channel": channel,
                            "event_type": "cloudwatch",
                            "event": "post_captions",
                        }
                    ),
                }
            ],
        )

        self.lam.add_permission(
            FunctionName=self.context.function_name,
            StatementId=name,
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule["RuleArn"],
        )


db = Connections()


class SlackAPI(object):
    def post(self, channel, text, **kwargs):
        body = {"channel": channel, "text": text, **kwargs}
        return self.call("/chat.postMessage", body)

    def add_reaction(self, channel, timestamp, emoji, **kwargs):
        body = {"channel": channel, "timestamp": timestamp, "name": emoji, **kwargs}
        return self.call("/reactions.add", body)

    def call(self, path, body):
        headers = {"Authorization": "Bearer " + OAUTH_TOKEN}
        resp = requests.post(
            "https://slack.com/api/" + path, headers=headers, json=body
        )
        resp.raise_for_status()
        data = resp.json()
        if not data["ok"]:
            print("Error request path: %s body: %s" % (path, body))
            print("Error Response: " + json.dumps(data))
            raise Exception("API exception: " + data["error"])
        return data


slack = SlackAPI()


def lambda_handler(event, context):
    db.context = context
    if event.get("event_type") == "cloudwatch":
        return handle_cloudwatch_event(event)
    try:
        body = json.loads(event["body"])
    except ValueError:
        body = dict(parse_qsl(event["body"]))
    except KeyError:
        print(event)
    if "challenge" in body:
        return {"statusCode": 200, "body": body["challenge"]}
    elif "command" in body:
        return handle_command(body)
    elif "event" in body:
        handle_event(body["event"], context)

    return {"statusCode": 200}


def handle_event(event, context):
    if event["type"] == "message":
        if event["channel_type"] == "im":
            handle_im(event)
        elif event.get("files"):
            check_for_image(event, context)


def handle_cloudwatch_event(event):
    print("Handling Cloudwatch event " + event["event"])
    if event["event"] == "post_captions":
        channel = event["channel"]
        finish_contest(channel)


def finish_contest(channel):
    submissions = db.get_and_clear_submissions(channel)
    db.clear_callback(channel)
    if not submissions:
        print("No caption submissions")
        return
    random.shuffle(submissions)
    text = "\n".join(
        ["%s. %s" % (e[1], item["text"]) for (e, item) in zip(EMOJIS, submissions)]
    )
    print(text)
    resp = slack.post(channel, text, mrkdwn=True)
    ts = resp["message"]["ts"]
    for i in range(len(submissions)):
        slack.add_reaction(channel, ts, EMOJIS[i][0])


def handle_command(event):
    if event["command"] == "/caption":
        text = event["text"]
        channel = event["channel_id"]
        if text == "we done":
            finish_contest(channel)
            return {"statusCode": 200}
        elif text == "debug":
            captions = db.get_submissions(channel)
            return {"statusCode": 200, "body": "%d captions" % len(captions)}
        print("Adding a submission to channel %s: %s" % (channel, text))
        db.add_submission(channel, text)
        return {
            "statusCode": 200,
            "body": json.dumps({"text": "_" + text + "_", "mrkdwn": True}),
        }
    return {"statusCode": 404}


def handle_im(event):
    text = event["text"]
    if event.get("subtype") == "bot_message":
        return
    slack.post(event["channel"], HELP)


def check_for_image(event, context):
    image = None
    for file in event["files"]:
        if file["filetype"] in ("png", "jpg", "jpeg"):
            image = file
            break
    if image is None:
        return
    channel = event["channel"]
    print(
        "Detected file in message. Starting new caption contest in channel " + channel
    )
    db.get_and_clear_submissions(channel)
    db.set_callback(channel)

    slack.post(
        event["channel"],
        "<!channel> New caption contest! Submit your captions using the `/caption` command",
        mrkdwn=True,
    )
