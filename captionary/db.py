import json
import time
import zope.sqlalchemy
from pyramid.renderers import render
from sqlalchemy import (
    engine_from_config,
    Column,
    String,
    UnicodeText,
    Integer,
    ForeignKey,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.orm import sessionmaker, relationship, backref
from sqlalchemy.interfaces import PoolListener
from sqlalchemy.types import TypeDecorator, TEXT

Base = declarative_base()  # pylint: disable=C0103


class ForeignKeysListener(PoolListener):
    def connect(self, dbapi_con, con_record):
        db_cursor = dbapi_con.execute("pragma foreign_keys=ON")


class State(object):
    none = None
    captioning = "captioning"
    voting = "voting"


class JSONEncodedDict(TypeDecorator):  # pylint: disable=W0223

    "Represents an immutable structure as a json-encoded string."

    impl = TEXT

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = render("json", value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


class MutableDict(Mutable, dict):

    """ SQLAlchemy dict field that tracks changes """

    @classmethod
    def coerce(cls, key, value):
        "Convert plain dictionaries to MutableDict."

        if not isinstance(value, MutableDict):
            if isinstance(value, dict):
                return MutableDict(value)

            # this call will raise ValueError
            return Mutable.coerce(key, value)
        else:
            return value

    def __setitem__(self, key, value):
        "Detect dictionary set events and emit change events."
        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key):
        "Detect dictionary del events and emit change events."
        dict.__delitem__(self, key)
        self.changed()

    def pop(self, key, default=None):
        "Detect dictionary pop events and emit change events."
        dict.pop(self, key, default)
        self.changed()


MutableDict.associate_with(JSONEncodedDict)


class Config(Base):
    __tablename__ = "configs"
    key = Column(String(20), primary_key=True)
    channel = Column(String(20), primary_key=True)
    value = Column(JSONEncodedDict(), nullable=False)

    @classmethod
    def start_contest(cls, db, config, file_id, image_url, end_dt):
        config.value["file_id"] = file_id
        config.value["image_url"] = image_url
        config.value["end"] = end_dt
        config.value["state"] = State.captioning
        db.merge(config)

    @classmethod
    def start_voting(cls, db, config, message_ts, end_dt):
        config.value["message_ts"] = message_ts
        config.value["end"] = end_dt
        config.value["state"] = State.voting
        db.merge(config)

    @classmethod
    def get_ended_configs(cls, db):
        configs = db.query(cls).filter(cls.key == "contest")
        now = time.time()
        return [c for c in configs if "end" in c.value and c["end"] < now]

    @classmethod
    def get_config(cls, db, channel):
        return db.query(cls).get(("contest", channel))

    @classmethod
    def get_or_create(cls, db, channel):
        config = db.query(cls).get(("contest", channel))
        if config is None:
            config = cls(key="contest", channel=channel, value={})
            db.merge(config)
        return config

    @classmethod
    def get_contest_state(cls, db, channel):
        config = db.query(cls).get(("contest", channel))
        if config is not None:
            return config.value.get("state")

    @classmethod
    def end_contest(cls, db, config):
        config.value.pop("file_id")
        config.value.pop("image_url")
        config.value.pop("message_ts")
        config.value.pop("state")
        config.value.pop("end")
        db.merge(config)


class Caption(Base):
    __tablename__ = "captions"
    id = Column(Integer, autoincrement=True, primary_key=True)
    channel = Column(String(20), index=True, nullable=False)
    caption = Column(UnicodeText(), nullable=False)

    @classmethod
    def add_submission(cls, db, channel, text):
        db.add(cls(channel=channel, caption=text))

    @classmethod
    def get_captions(cls, db, channel):
        return list(db.query(cls).filter(cls.channel == channel))

    @classmethod
    def get_captions_and_votes(cls, db, channel):
        return list(
            db.query(func.count(Vote.user), cls.caption)
            .select_from(cls)
            .outerjoin(Vote)
            .filter(cls.channel == channel)
            .group_by(cls.id)
        )

    @classmethod
    def clear_captions(cls, db, channel):
        db.query(cls).filter(cls.channel == channel).delete(synchronize_session=False)

    @classmethod
    def get_votes(cls, db, user, channel):
        return (
            db.query(cls)
            .join(Vote.caption)
            .filter(cls.channel == channel)
            .filter(Vote.user == user)
        )


class Vote(Base):
    __tablename__ = "votes"
    user = Column(String(20), primary_key=True)
    caption_id = Column(
        Integer, ForeignKey(Caption.id, ondelete="CASCADE"), primary_key=True
    )

    caption = relationship(
        "Caption", backref=backref("votes", cascade="all, delete-orphan")
    )

    @classmethod
    def toggle_vote(cls, db, user, caption):
        vote = db.query(cls).get((user, caption))
        if vote is None:
            db.add(cls(user=user, caption_id=caption))
        else:
            db.delete(vote)


def get_db(request):
    db = request.registry.dbmaker()
    zope.sqlalchemy.register(db, transaction_manager=request.tm)
    return db


def includeme(config):
    settings = config.get_settings()

    engine = engine_from_config(
        settings, prefix="db.", listeners=[ForeignKeysListener()]
    )
    # Create SQL schema if not exists
    Base.metadata.create_all(bind=engine)
    config.registry.dbmaker = sessionmaker(bind=engine)

    config.add_request_method(get_db, name="db", reify=True)

    try:
        from uwsgidecorators import postfork
    except ImportError:
        pass
    else:

        @postfork
        def run_postfork_hooks():
            """ Run hooks after uWSGI forks """
            config.registry.dbmaker.kw["bind"].dispose()
