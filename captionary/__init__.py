import calendar
import os
import zope.sqlalchemy
import datetime
import logging
from pyramid.config import Configurator
from pyramid.renderers import JSON, render
from pyramid.settings import asbool
from sqlalchemy import engine_from_config, distinct, and_, or_, Column, DateTime, String
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator, TEXT


__version__ = "0.0.1"
LOG = logging.getLogger(__name__)


def add_routes(config):
    config.add_route("event", "/event")
    config.add_route("command", "/command")


def includeme(config):
    settings = config.get_settings()
    config.include("pyramid_tm")
    config.include("pyramid_duh")
    config.include("pyramid_duh.auth")
    config.include("captionary.db")
    config.include("captionary.slack")

    config.registry.oauth_token = (
        settings.get("slack.oauth_token") or os.environ["OAUTH_TOKEN"]
    )

    # If we're reloading templates, we should also pretty-print json
    reload_templates = asbool(settings.get("pyramid.reload_templates"))
    indent = 4 if reload_templates else None
    json_renderer = JSON(indent=indent)
    json_renderer.add_adapter(
        datetime.datetime, lambda obj, r: calendar.timegm(obj.utctimetuple())
    )
    config.add_renderer("json", json_renderer)

    add_routes(config)


def main(config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(settings=settings)
    config.include("captionary")
    config.scan("captionary.views")
    return config.make_wsgi_app()
