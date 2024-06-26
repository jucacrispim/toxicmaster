# -*- coding: utf-8 -*-

# Copyright 2015, 2023 Juca Crispim <juca@poraodojuca.net>

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

from toxiccore import BaseToxicClient
from toxiccore.exceptions import ToxicClientException
from toxiccore.utils import LoggerMixin, datetime2string
from . import settings
from .utils import (get_build_config_type,
                    get_build_config_filename)


MAX_PROCESS_TASKS = 10


class BuildClient(BaseToxicClient, LoggerMixin):

    """ A client to :class:`toxicbuild.slave.server.BuildServer`
    """

    def __init__(self, slave, *args, **kwargs):
        self.slave = slave
        super().__init__(*args, **kwargs)
        self.config_type = get_build_config_type()
        self.config_filename = get_build_config_filename()

    async def healthcheck(self):
        """ Asks to know if the server is up and running
        """
        data = {'action': 'healthcheck'}
        try:
            await self.write(data)
            response = await self.get_response()
            r = True
        except Exception:
            response = None
            r = False

        # When we try to connect to a secure slave using a non-secure
        # connection we get an empty response
        if response == '':
            raise ToxicClientException(
                'Bad connection. Check the slave ssl settings.')
        return r

    async def list_builders(self, repo_url, vcs_type, branch, named_tree):
        """ Asks the server for the builders available for ``repo_url``,
        on ``branch`` and ``named_tree``.
        """

        data = {'action': 'list_builders',
                'body': {'repo_url': repo_url,
                         'vcs_type': vcs_type,
                         'branch': branch,
                         'named_tree': named_tree,
                         'config_type': self.config_type,
                         'config_filename': self.config_filename}}
        await self.write(data)
        response = await self.get_response()
        builders = response['body']['builders']
        return builders

    async def build(self, build, envvars=None, unresponsive_timeout=None):
        """Requests a build for the build server.

        :param build: The build that will be executed.
          param evvars: Environment variables to use in the build.
        :param process_coro: A coroutine to process the intermediate
          build information sent by the build server.
        :param unresponsive_timeout: Timeout for an unresponsive slave
          during the build
        """

        repository = await build.repository
        builder_name = (await build.builder).name
        slave = await build.slave
        self.log('Starting build {} on {}'.format(build.uuid, slave.name),
                 level='debug')
        data = {'action': 'build',
                'token': slave.token,
                'body': {'repo_url': repository.get_url(),
                         'build_uuid': str(build.uuid),
                         'envvars': envvars or {},
                         'repo_id': str(repository.id),
                         'vcs_type': repository.vcs_type,
                         'branch': build.branch,
                         'named_tree': build.named_tree,
                         'builder_name': builder_name,
                         'config_type': self.config_type,
                         'config_filename': self.config_filename,
                         'builders_from': build.builders_from}}
        if build.external:
            data['body']['external'] = build.external.to_dict()

        await self.write(data, timeout=unresponsive_timeout)
        while True:
            r = await self.get_response(timeout=unresponsive_timeout)
            if not r or r.get('body') is None:
                break

            build_info = r.get('body')
            yield build_info

    async def cancel_build(self, build):
        slave = await build.slave
        data = {'action': 'cancel_build',
                'token': slave.token,
                'body': {'build_uuid': str(build.uuid)}}

        await self.write(data)
        r = await self.get_response()
        return r


async def get_build_client(slave, addr, port, use_ssl=True,
                           validate_cert=True):
    """Instanciate :class:`toxicmaster.client.BuildClient` and
    connects it to a build server
    """

    client = BuildClient(slave, addr, port, use_ssl=use_ssl,
                         validate_cert=validate_cert)
    await client.connect()
    return client


class PollerClient(BaseToxicClient):
    """A client to :class:`~toxicbuild.poller.server.PollerServer`.
    """

    def __init__(self, repo, *args, **kwargs):
        """:param repo: A :class:`~toxicmaster.repository.Repository`
          instance.
        :param args: Arguments passed to
          :class:`toxicbuild.core.server.ToxicServer`
        :param args: Named arguments passed to
          :class:`toxicbuild.core.server.ToxicServer`
        """
        self.repo = repo
        super().__init__(*args, **kwargs)

    async def poll_repo(self, branches_conf=None, external=None):
        """Requests for the poller to poll the code of a repository.

        :param branches_conf: Branches config in the form:

          .. code-block:: python

             {'branch-name': {'notify_only_latest': True,
                              'builders_fallback': 'master'}}

          If branches_conf is None the default repo branches config will be
          used.
        """
        dbrevisions = await self.repo.get_latest_revisions()
        since = dict((branch, datetime2string(r.commit_date)) for branch, r
                     in dbrevisions.items() if r)

        branches_conf = branches_conf or {
            b.name: {'notify_only_latest': b.notify_only_latest}
            for b in self.repo.branches}

        body = {
            'repo_id': str(self.repo.id),
            'url': self.repo.get_url(),
            'vcs_type': self.repo.vcs_type,
            'known_branches': await self.repo.get_known_branches(),
            'since': since,
            'branches_conf': branches_conf,
            'external': external,
            'conffile': self.repo.config_filename,
        }
        url = self.repo.get_url()
        self.log('Updating code with url {}'.format(url),
                 level='debug')
        token = settings.POLLER_TOKEN
        r = await self.request2server('poll', body, token)
        self.log(f'Update for {url} finished with {r}', level='debug')
        return r


def get_poller_client(repo):
    """Returns an instance of :class:`~toxicmaster.client.PollerClient`.
    """

    host = settings.POLLER_HOST
    port = settings.POLLER_PORT
    use_ssl = settings.POLLER_USES_SSL
    validate_cert = settings.VALIDATE_CERT_POLLER
    client = PollerClient(repo, host, port, use_ssl=use_ssl,
                          validate_cert=validate_cert)
    return client


class SecretsClient(BaseToxicClient):
    """A client to :class:`~toxicbuild.sercrets.server.SecretsServer`.
    """

    async def add_or_update_secret(self, owner, key, value):
        """Adds a new secret. The owner can be a repo, a user or a
        organization.
        """

        action = 'add-or-update-secret'
        body = {'owner': str(owner.id),
                'key': key,
                'value': value}
        token = settings.SECRETS_TOKEN
        r = await self.request2server(action, body, token)
        return r

    async def remove_secret(self, owner, key):
        """Removes a secret.
        """

        action = 'remove-secret'
        body = {'owner': str(owner.id),
                'key': key}
        token = settings.SECRETS_TOKEN
        r = await self.request2server(action, body, token)
        return r

    async def get_secrets(self, owners):
        """Get the secrets of a list of owners
        """
        action = 'get-secrets'
        owner_ids = [str(o.id) for o in owners]
        body = {'owners': owner_ids}
        token = settings.SECRETS_TOKEN
        r = await self.request2server(action, body, token)
        secrets = {s['key']: s['value'] for s in r}
        return secrets

    async def remove_all(self, owner):
        """Removes all secrets from a owner
        """
        action = 'remove-all'
        body = {'owner': str(owner.id)}
        token = settings.SECRETS_TOKEN
        r = await self.request2server(action, body, token)
        return r


def get_secrets_client():
    """Returns an instance of :class:`~toxicmaster.client.SecretsClient`.
    """

    host = settings.SECRETS_HOST
    port = settings.SECRETS_PORT
    use_ssl = settings.SECRETS_USES_SSL
    validate_cert = settings.VALIDATE_CERT_SECRETS
    client = SecretsClient(host, port, use_ssl=use_ssl,
                           validate_cert=validate_cert)
    return client
