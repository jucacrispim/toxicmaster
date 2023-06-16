# -*- coding: utf-8 -*-

import asyncio
import atexit
import os
from toxiccommon import common_setup, exchanges
from toxicmaster import create_settings_and_connect
from toxicmaster import create_scheduler

from toxiccommon.coordination import ToxicZKClient  # noqa: F402

from tests import MASTER_ROOT_DIR

os.environ['TOXICMASTER_SETTINGS'] = os.path.join(
    MASTER_ROOT_DIR, 'toxicmaster.conf')

create_settings_and_connect()
create_scheduler()

from toxicmaster import scheduler, settings  # noqa: E402
scheduler.stop()


loop = asyncio.get_event_loop()

loop.run_until_complete(common_setup(settings))


def clean():
    if ToxicZKClient._zk_client:
        try:
            loop.run_until_complete(ToxicZKClient._zk_client.close())
        except Exception:
            pass

    try:
        loop.run_until_complete(exchanges.conn.disconnect())
    except Exception:
        pass


atexit.register(clean)
