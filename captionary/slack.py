import requests
import logging


LOG = logging.getLogger(__name__)


class SlackAPI(object):
    def __init__(self, request):
        self.request = request

    def post(self, channel, text, **kwargs):
        body = {"channel": channel, "text": text}
        body.update(kwargs)
        return self.call("/chat.postMessage", body)

    def add_reaction(self, channel, timestamp, emoji, **kwargs):
        body = {"channel": channel, "timestamp": timestamp, "name": emoji}
        body.update(kwargs)
        return self.call("/reactions.add", body)

    def call(self, path, body):
        headers = {"Authorization": "Bearer " + self.request.registry.oauth_token}
        resp = requests.post(
            "https://slack.com/api/" + path, headers=headers, json=body
        )
        resp.raise_for_status()
        data = resp.json()
        if not data["ok"]:
            LOG.error(
                "Slack API error. path: %s body: %s response: %s", path, body, data
            )
            raise Exception("Slack API exception: " + data["error"])
        return data


def includeme(config):
    config.add_request_method(SlackAPI, name="slack", reify=True)
