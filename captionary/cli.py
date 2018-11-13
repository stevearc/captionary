import logging
import argparse
from pyramid.paster import bootstrap
from .actions import finish_contest
from .db import Config


def process_queue():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="config file")

    args = parser.parse_args()
    logging.basicConfig()

    env = bootstrap(args.config)

    request = env["request"]
    configs = Config.get_ended_configs(request.db)
    for config in configs:
        finish_contest(request, config.channel)
