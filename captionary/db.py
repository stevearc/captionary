import json
from datetime import datetime
import time
import calendar
import zope.sqlalchemy
from sqlalchemy import engine_from_config, Column, String, UnicodeText, Integer, and_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator, TEXT

Base = declarative_base()  # pylint: disable=C0103


class JSONEncodedDict(TypeDecorator):  # pylint: disable=W0223

    "Represents an immutable structure as a json-encoded string."

    impl = TEXT

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
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


MutableDict.associate_with(JSONEncodedDict)


class Config(Base):
    __tablename__ = "configs"
    key = Column(String(20), primary_key=True)
    channel = Column(String(20), primary_key=True)
    value = Column(JSONEncodedDict(), nullable=False)

    @classmethod
    def _get_contest(cls, db, channel):
        return db.query(cls).filter(and_(cls.key == "contest", cls.channel == channel))

    @classmethod
    def start_contest(cls, db, channel, file_id, end_dt):
        prev = (
            db.query(cls)
            .filter(and_(cls.key == "contest", cls.channel == channel))
            .first()
        )
        if prev is not None and prev.value.get("file_id") == file_id:
            return False
        config = cls(
            key="contest",
            channel=channel,
            value={"file_id": file_id, "end": calendar.timegm(end_dt.utctimetuple())},
        )
        db.merge(config)
        return True

    @classmethod
    def get_ended_configs(cls, db):
        configs = db.query(cls).filter(cls.key == "contest")
        now = time.time()
        return [c for c in configs if "end" in c.value and c["end"] < now]

    @classmethod
    def get_contest_end(cls, db, channel):
        config = cls._get_contest(db, channel).first()
        if config is None or "end" not in config.value:
            return None
        return datetime.utcfromtimestamp(config.value["end"])

    @classmethod
    def end_contest(cls, db, channel):
        config = cls._get_contest(db, channel).one()
        if "end" in config.value:
            del config.value["file_id"]
            del config.value["end"]
            db.merge(config)
            return True
        return False


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
        return [cap.caption for cap in db.query(cls)]

    @classmethod
    def clear_captions(cls, db, channel):
        db.query(cls).filter(cls.channel == channel).delete(synchronize_session=False)


def get_db(request):
    db = request.registry.dbmaker()
    zope.sqlalchemy.register(db, transaction_manager=request.tm)
    return db


def includeme(config):
    settings = config.get_settings()

    engine = engine_from_config(settings, prefix="db.")
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
