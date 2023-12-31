# -*- coding: utf-8 -*-

# Copyright 2017 Juca Crispim <juca@poraodojuca.net>

# This file is part of toxicbuild.

# toxicbuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# toxicbuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with toxicbuild. If not, see <http://www.gnu.org/licenses/>.

import json

from toxiccore import requests

from . import settings


def get_build_config_type():
    """Returns the build config type."""

    return getattr(settings, 'BUILD_CONFIG_TYPE', 'yaml')


def get_build_config_filename():
    """Returns the build config filename."""

    return getattr(settings, 'BUILD_CONFIG_FILENAME', 'toxicbuild.yml')


async def send_email(recipients, subject, message):
    """Sends an email using the output's web api

    :param recipients: A list of email addresses.
    :param subject: The email's subject.
    :param message: The email's body.
    """

    url = settings.NOTIFICATIONS_API_URL + 'send-email'
    token = settings.NOTIFICATIONS_API_TOKEN
    data = {'recipients': recipients,
            'subject': subject,
            'message': message}

    headers = {'Authorization': 'token: {}'.format(token)}

    await requests.post(url, headers=headers, data=json.dumps(data))
    return True
