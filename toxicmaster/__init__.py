# -*- coding: utf-8 -*-

# pylint: disable-all

from asyncio import ensure_future
from mongomotor import connect
from toxiccore.conf import Settings

__version__ = '0.12.3'

settings = None
dbconn = None
scheduler = None

ENVVAR = 'TOXICMASTER_SETTINGS'
DEFAULT_SETTINGS = 'toxicmaster.conf'


def create_settings_and_connect():
    global settings, dbconn

    settings = Settings(ENVVAR, DEFAULT_SETTINGS)
    dbsettings = settings.DATABASE
    dbconn = connect(**dbsettings)


def ensure_indexes(*classes):
    for cls in classes:
        cls.ensure_indexes()


def create_scheduler():
    from .scheduler import TaskScheduler

    global scheduler

    scheduler = TaskScheduler()
    ensure_future(scheduler.start())
