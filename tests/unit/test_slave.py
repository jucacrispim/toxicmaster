# -*- coding: utf-8 -*-

# Copyright 2016-2019, 2023, 2024 Juca Crispim <juca@poraodojuca.dev>

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

import datetime
from unittest import TestCase
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from uuid import uuid4
from toxiccore.utils import datetime2string
from toxicmaster import slave, build, repository, users
from tests import async_test


@patch.object(slave, 'build_started', Mock())
@patch.object(slave, 'build_finished', Mock())
@patch.object(slave, 'step_started', Mock())
@patch.object(slave, 'step_finished', Mock())
@patch.object(slave, 'step_output_arrived', Mock())
class SlaveTest(TestCase):

    @async_test
    async def setUp(self):
        super().setUp()
        self.owner = users.User(email='a@a.com', password='adsf')
        await self.owner.save()
        self.slave = slave.Slave(name='slave', host='127.0.0.1', port=7777,
                                 token='asdf', owner=self.owner)

    @async_test
    async def tearDown(self):
        await slave.Slave.drop_collection()
        await build.BuildSet.drop_collection()
        await build.Builder.drop_collection()
        await repository.RepositoryRevision.drop_collection()
        await repository.Repository.drop_collection()
        await users.User.drop_collection()
        super().tearDown()

    @async_test
    async def test_create(self):
        slave_inst = await slave.Slave.create(name='name',
                                              host='somewhere.net',
                                              port=7777,
                                              token='asdf',
                                              owner=self.owner)
        self.assertTrue(slave_inst.id)

    @async_test
    async def test_to_dict(self):
        slave_inst = await slave.Slave.create(name='name',
                                              host='somewhere.net',
                                              port=7777,
                                              token='asdf',
                                              owner=self.owner)
        slave_dict = slave_inst.to_dict()
        self.assertTrue(slave_dict['id'])
        self.assertTrue(slave_dict['full_name'])

    @async_test
    async def test_to_dict_id_as_str(self):
        slave_inst = await slave.Slave.create(name='name',
                                              host='somewhere.net',
                                              port=7777,
                                              token='asdf',
                                              owner=self.owner)
        slave_dict = slave_inst.to_dict(id_as_str=True)
        self.assertIsInstance(slave_dict['id'], str)

    @async_test
    async def test_get(self):
        slave_inst = await slave.Slave.create(name='name',
                                              host='somewhere.net',
                                              port=7777,
                                              token='asdf',
                                              owner=self.owner)
        slave_id = slave_inst.id

        slave_inst = await slave.Slave.get(name='name',
                                           host='somewhere.net',
                                           port=7777)

        self.assertEqual(slave_id, slave_inst.id)

    @patch('toxicmaster.client.BuildClient.connect',
           AsyncMock(spec='toxicmaster.client.BuildClient.connect'))
    @async_test
    async def test_get_client(self, *a, **kw):

        client = await self.slave.get_client()
        self.assertTrue(client.connect.called)

    @async_test
    async def test_healthcheck(self):

        async def gc():
            client = MagicMock()

            async def hc():  # x no pé!
                return True

            client.__enter__.return_value.healthcheck = hc
            return client

        self.slave.get_client = gc

        r = await self.slave.healthcheck()

        self.assertTrue(r)

    @patch.object(slave.asyncio, 'sleep', AsyncMock())
    @patch.object(slave.Slave, 'healthcheck', AsyncMock(
        side_effect=ConnectionRefusedError))
    @async_test
    async def test_wait_service_start_timeout(self):
        with self.assertRaises(TimeoutError):
            await self.slave.wait_service_start()

    @patch.object(slave.Slave, 'healthcheck', AsyncMock())
    @async_test
    async def test_wait_service_start(self):
        r = await self.slave.wait_service_start()
        self.assertIs(r, True)

    @patch.object(slave.Slave, 'healthcheck',
                  AsyncMock(side_effect=slave.ToxicClientException))
    @async_test
    async def test_wait_service_client_exception(self):
        with self.assertRaises(slave.ToxicClientException):
            await self.slave.wait_service_start()

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @async_test
    async def test_list_builders(self):
        await self._create_test_data()

        async def gc():
            client = MagicMock()

            async def lb(repo_url, vcs_type, branch, named_tree):
                return ['builder-1', 'builder-2']

            client.__enter__.return_value.list_builders = lb
            return client

        self.slave.get_client = gc

        builders = await self.slave.list_builders(self.revision)

        self.assertEqual(builders, [self.builder, self.other_builder])

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @async_test
    async def test_finish_build_start_exception(self):
        await self._create_test_data()
        await self.slave._finish_build_start_exception(
            self.build, self.repo, '')
        self.assertEqual(self.build.status, 'exception')

    @patch.object(slave.Lock, 'acquire_write', AsyncMock(
        spec=slave.Lock.acquire_write, return_value=AsyncMock()))
    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @async_test
    async def test_build_bad_start(self):
        await self._create_test_data()
        self.slave.start_instance = AsyncMock(side_effect=Exception)
        r = await self.slave.build(self.build)

        self.assertIs(r, False)

    @patch.object(slave.Lock, 'acquire_write', AsyncMock(
        spec=slave.Lock.acquire_write, return_value=AsyncMock()))
    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @patch.object(slave.Slave, '_process_info', AsyncMock(
        spec=slave.Slave._process_info))
    @async_test
    async def test_build(self):
        await self._create_test_data()
        client = MagicMock()
        client.__enter__.return_value = client
        bmock = Mock()

        async def gc():

            async def b(build, envvars=None, unresponsive_timeout=None):
                bmock()
                yield {'some': 'info'}

            client.build = b
            return client

        self.slave.get_client = gc
        await self.slave.build(self.build)
        self.assertTrue(bmock.called)
        self.assertTrue(self.slave._process_info.called)

    @async_test
    async def test_cancel_build(self):
        client = MagicMock()
        client.__enter__.return_value = client
        bmock = Mock()

        async def gc():

            async def cb(build):
                bmock()
                return {'some': 'info'}

            client.cancel_build = cb
            return client

        self.slave.get_client = gc
        build = Mock(uuid='some-uuid')
        await self.slave.cancel_build(build)

        self.assertTrue(bmock.called)

    @patch.object(slave.Lock, 'acquire_write', AsyncMock(
        spec=slave.Lock.acquire_write, return_value=AsyncMock()))
    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @async_test
    async def test_build_with_exception(self):
        await self._create_test_data()
        client = MagicMock()
        client.__enter__.return_value = client
        client.build = MagicMock(side_effect=slave.ToxicClientException)

        async def gc():
            return client

        self.slave.get_client = gc
        await self.slave.build(self.build)
        self.assertEqual(self.build.status, 'exception')
        self.assertTrue(self.build.finished)
        self.assertEqual(len(self.build.steps), 1)

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @patch.object(slave, 'build_started', Mock())
    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_process_info_with_build_started(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime2string(datetime.datetime.now(tz=tz))

        build_info = {'status': 'running', 'steps': [],
                      'started': now, 'finished': None,
                      'info_type': 'build_info'}

        await self.slave._process_info(self.build, self.repo, build_info)
        self.assertTrue(slave.build_started.send.called)
        self.assertTrue(build.notifications.publish.called)

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @patch.object(slave, 'build_finished', Mock())
    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_process_info_with_build_finished(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        formate_now = datetime2string(now)
        future_now = now + datetime.timedelta(seconds=2)
        future_formated_now = datetime2string(future_now)

        self.build.steps = [
            build.BuildStep(repository=self.repo, command='ls', name='ls')]
        build_info = {
            'status': 'running', 'steps': [
                {'status': 'success',
                 'finished': future_formated_now}],
            'started': formate_now, 'finished': future_formated_now,
            'info_type': 'build_info',
            'total_time': 2}

        r = await self.slave._process_info(self.build, self.repo, build_info)
        self.assertEqual(self.build.total_time, 2)
        self.assertTrue(slave.build_finished.send.called)
        self.assertTrue(build.notifications.publish.called)
        self.assertTrue(r)

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @patch.object(slave, 'build_finished', Mock())
    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @patch.object(slave.Slave, 'log', Mock())
    @async_test
    async def test_process_info_with_build_update_error(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        formate_now = datetime2string(now)
        future_now = now + datetime.timedelta(seconds=2)
        future_formated_now = datetime2string(future_now)

        self.build.steps = [
            build.BuildStep(repository=self.repo, command='ls', name='ls')]
        build_info = {
            'status': 'running', 'steps': [
                {'status': 'success',
                 'finished': future_formated_now}],
            'started': formate_now, 'finished': future_formated_now,
            'info_type': 'build_info',
            'total_time': 2}

        self.build.update = AsyncMock(side_effect=slave.DBError)
        r = await self.slave._process_info(self.build, self.repo, build_info)
        self.assertFalse(r)

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @async_test
    async def test_process_info_with_step(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)

        build_info = {'status': 'running', 'cmd': 'ls', 'name': 'ls',
                      'started': now, 'finished': None, 'output': '',
                      'index': 0, 'info_type': 'step_info'}

        self.slave._process_step_info = AsyncMock(
            spec=self.slave._process_step_info)
        await self.slave._process_info(self.build, self.repo, build_info)
        self.assertTrue(self.slave._process_step_info.called)

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @async_test
    async def test_process_info_with_step_output(self):
        await self._create_test_data()
        info = {'info_type': 'step_output_info'}

        self.slave._process_step_output_info = AsyncMock(
            spec=self.slave._process_step_info)

        await self.slave._process_info(self.build, self.repo, info)
        self.assertTrue(self.slave._process_step_output_info.called)

    @patch.object(build.BuildSet, 'notify', AsyncMock(
        spec=build.BuildSet.notify))
    @patch.object(slave.Slave, 'log', Mock(spec=slave.Slave.log))
    @async_test
    async def test_process_info_with_step_output_error(self):
        await self._create_test_data()
        info = {'info_type': 'step_output_info'}

        self.slave._process_step_output_info = AsyncMock(
            spec=self.slave._process_step_output_info, side_effect=Exception)

        r = await self.slave._process_info(self.build, self.repo, info)
        self.assertTrue(self.slave._process_step_output_info.called)
        assert r is None

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_process_step_info_new(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        started = now.strftime('%w %m %d %H:%M:%S %Y %z')
        finished = None

        step_info = {'status': 'running', 'cmd': 'ls', 'name': 'run ls',
                     'output': '', 'started': started, 'finished': finished,
                     'index': 0, 'uuid': uuid4()}
        await self.slave._process_step_info(self.build, self.repo, step_info)
        self.assertEqual(len(self.build.steps), 1)
        self.assertTrue(build.notifications.publish.called)

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_process_step_info(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        started = now.strftime('%w %m %d %H:%M:%S %Y %z')
        finished = (now + datetime.timedelta(seconds=2)).strftime(
            '%w %m %d %H:%M:%S %Y %z')
        a_uuid = str(uuid4())
        other_uuid = str(uuid4())

        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'running',
                'output': '', 'started': started, 'finished': None,
                'index': 0, 'uuid': a_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        info = {'cmd': 'echo "oi"', 'name': 'echo', 'status': 'running',
                'output': '', 'started': started, 'finished': None,
                'index': 1, 'uuid': other_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        info = {'cmd': 'echo "oi"', 'name': 'echo', 'status': 'success',
                'output': '', 'started': started, 'finished': finished,
                'index': 1, 'uuid': other_uuid, 'total_time': 2}

        await self.slave._process_step_info(self.build, self.repo, info)

        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'success',
                'output': 'somefile.txt\n', 'started': started,
                'finished': finished, 'total_time': 2,
                'index': 0, 'uuid': a_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        b = await type(self.build).get(self.build.uuid)
        self.assertEqual(b.steps[1].status, 'success')
        self.assertEqual(len(b.steps), 2)
        self.assertTrue(b.steps[1].total_time)
        self.assertTrue(build.notifications.publish.called)

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @patch.object(slave.Slave, 'log', Mock())
    @async_test
    async def test_process_step_info_bad_requested_step(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        started = now.strftime('%w %m %d %H:%M:%S %Y %z')
        finished = (now + datetime.timedelta(seconds=2)).strftime(
            '%w %m %d %H:%M:%S %Y %z')
        a_uuid = str(uuid4())
        self.build.uuid = build.uuid4()
        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'running',
                'output': '', 'started': started, 'finished': finished,
                'index': 0, 'uuid': a_uuid}

        r = await self.slave._process_step_info(self.build, self.repo, info)
        self.assertFalse(r)

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @patch.object(slave.Slave, 'log', Mock())
    @async_test
    async def test_process_step_info_bad_build_new_step(self):
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        started = now.strftime('%w %m %d %H:%M:%S %Y %z')
        a_uuid = str(uuid4())

        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'running',
                'output': '', 'started': started, 'finished': None,
                'index': 0, 'uuid': a_uuid}

        build = Mock()
        build.update = AsyncMock(side_effect=slave.DBError)
        repo = Mock()
        r = await self.slave._process_step_info(build, repo, info)
        self.assertFalse(r)

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_process_step_info_exception(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        started = now.strftime('%w %m %d %H:%M:%S %Y %z')
        finished = (now + datetime.timedelta(seconds=2)).strftime(
            '%w %m %d %H:%M:%S %Y %z')
        a_uuid = str(uuid4())

        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'running',
                'output': 'some-output', 'started': started, 'finished': None,
                'index': 0, 'uuid': a_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'exception',
                'output': 'shit happens', 'started': started,
                'finished': finished, 'total_time': 2,
                'index': 0, 'uuid': a_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        build = await type(self.build).get(self.build.uuid)
        self.assertEqual(build.steps[0].status, 'exception')
        self.assertEqual(build.steps[0].output, 'some-outputshit happens')

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_process_step_info_exception_no_output(self):
        await self._create_test_data()
        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        started = now.strftime('%w %m %d %H:%M:%S %Y %z')
        finished = (now + datetime.timedelta(seconds=2)).strftime(
            '%w %m %d %H:%M:%S %Y %z')
        a_uuid = str(uuid4())

        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'running',
                'output': None, 'started': started, 'finished': None,
                'index': 0, 'uuid': a_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'exception',
                'output': 'shit happens', 'started': started,
                'finished': finished, 'total_time': 2,
                'index': 0, 'uuid': a_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        build = await type(self.build).get(self.build.uuid)
        self.assertEqual(build.steps[0].status, 'exception')
        self.assertEqual(build.steps[0].output, 'shit happens')

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_update_build_step_less_than_cache(self):
        build = Mock()
        step_info = {'uuid': 'some-uuid', 'output': 'bla'}
        r = await self.slave._update_build_step_info(build, step_info)

        self.assertFalse(r)

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_process_step_output_info(self):
        await self._create_test_data()

        tz = datetime.timezone(-datetime.timedelta(hours=3))
        now = datetime.datetime.now(tz=tz)
        started = now.strftime('%w %m %d %H:%M:%S %Y %z')
        a_uuid = str(uuid4())
        self.slave._step_output_cache_time[a_uuid] = 10
        info = {'cmd': 'ls', 'name': 'run ls', 'status': 'running',
                'output': '', 'started': started, 'finished': None,
                'index': 0, 'uuid': a_uuid}

        await self.slave._process_step_info(self.build, self.repo, info)

        info = {'uuid': a_uuid, 'output': 'somefile.txt\n'}
        await self.slave._process_step_output_info(self.build, self.repo, info)
        step = await self.slave._get_step(self.build, a_uuid)
        self.assertTrue(step.output)
        self.assertTrue(build.notifications.publish.called)

    @patch.object(build.notifications, 'publish', AsyncMock(
        spec=build.notifications.publish))
    @patch.object(build.integrations_notifications, 'publish',
                  AsyncMock(spec=build.integrations_notifications.publish))
    @async_test
    async def test_get_step_wait(self):
        await self._create_test_data()
        build = self.buildset.builds[0]
        step = await self.slave._get_step(build, 'dont-exist', wait=True)
        self.assertIsNone(step)

    @patch('toxicmaster.aws.settings')
    def test_instance(self, *a, **kw):
        self.slave.instance_type = 'ec2'
        self.slave.instance_confs = {'instance_id': 'some-id',
                                     'region': 'us-east-2'}

        self.assertIsInstance(self.slave.instance, slave.EC2Instance)

    @async_test
    async def test_start_instance_not_on_demand(self):
        self.slave.on_demand = False
        r = await self.slave.start_instance()
        self.assertFalse(r)

    @patch.object(slave.EC2Instance, 'start', AsyncMock())
    @patch.object(slave.EC2Instance, 'is_running', AsyncMock(
        return_value=True))
    @patch.object(slave.EC2Instance, 'get_ip', AsyncMock(
        return_value='192.168.0.1'))
    @patch.object(slave.Slave, 'wait_service_start', AsyncMock())
    @patch('toxicmaster.aws.settings')
    @async_test
    async def test_start_instance_already_running(self, *a, **kw):
        self.slave.on_demand = True
        self.slave.instance_type = 'ec2'
        self.slave.instance_confs = {'instance_id': 'some-id',
                                     'region': 'us-east-2'}
        r = await self.slave.start_instance()
        self.assertEqual(r, '192.168.0.1')
        self.assertFalse(slave.EC2Instance.start.called)

    @patch.object(slave.EC2Instance, 'is_running', AsyncMock(
        return_value=False))
    @patch.object(slave.EC2Instance, 'start', AsyncMock())
    @patch.object(slave.EC2Instance, 'get_ip', AsyncMock(
        return_value='192.168.0.1'))
    @patch.object(slave.Slave, 'wait_service_start', AsyncMock())
    @patch('toxicmaster.aws.settings')
    @async_test
    async def test_start_instance_ok(self, *a, **kw):
        self.slave.on_demand = True
        self.slave.host = slave.Slave.DYNAMIC_HOST
        self.slave.instance_type = 'ec2'
        self.slave.instance_confs = {'instance_id': 'some-id',
                                     'region': 'us-east-2'}
        await self.slave.start_instance()
        self.assertEqual(self.slave.host, '192.168.0.1')

    @async_test
    async def test_stop_instance_not_on_demand(self):
        self.slave.on_demand = False
        r = await self.slave.stop_instance()
        self.assertFalse(r)

    @patch.object(slave.EC2Instance, 'is_running', AsyncMock(
        return_value=False))
    @patch('toxicmaster.aws.settings')
    @async_test
    async def test_stop_instance_already_stopped(self, *a, **kw):
        self.slave.on_demand = True
        self.slave.instance_type = 'ec2'
        self.slave.instance_confs = {'instance_id': 'some-id',
                                     'region': 'us-east-2'}
        r = await self.slave.stop_instance()
        self.assertFalse(r)
        self.assertTrue(slave.EC2Instance.is_running.called)

    @async_test
    async def test_stop_instance_with_queue(self):
        self.slave.on_demand = True
        self.slave.queue_count = 1
        r = await self.slave.stop_instance()
        self.assertFalse(r)

    @async_test
    async def test_stop_instance_with_running(self):
        self.slave.on_demand = True
        self.slave.running_count = 1
        r = await self.slave.stop_instance()
        self.assertFalse(r)

    @patch.object(slave.EC2Instance, 'is_running', AsyncMock(
        return_value=True))
    @patch.object(slave.EC2Instance, 'stop', AsyncMock())
    @patch('toxicmaster.aws.settings')
    @async_test
    async def test_stop_instance_ok(self, *a, **kw):
        self.slave.on_demand = True
        self.slave.instance_type = 'ec2'
        self.slave.instance_confs = {'instance_id': 'some-id',
                                     'region': 'us-east-2'}
        r = await self.slave.stop_instance()
        self.assertTrue(r)

    @async_test
    async def test_save_dynamic_host(self):
        self.slave.on_demand = True
        self.slave.host = None
        await self.slave.save()

        self.assertEqual(self.slave.host, self.slave.DYNAMIC_HOST)

    @async_test
    async def test_add_running_repo(self):
        await self.slave.save()
        self.slave.host = 'a-host-that-shouldnt-be'
        await self.slave.add_running_repo('some-repo')
        await self.slave.reload()
        self.assertTrue(self.slave.running_repos)
        self.assertTrue(self.slave.running_count)
        self.assertFalse(self.slave.host == 'a-host-that-shouldnt-be')

    @async_test
    async def test_rm_running_repo(self):
        await self.slave.save()
        self.slave.host = 'a-host-that-shouldnt-be'
        await self.slave.add_running_repo('some-repo')
        await self.slave.rm_running_repo('some-repo')
        await self.slave.reload()
        self.assertFalse(self.slave.running_repos)
        self.assertFalse(self.slave.running_count)
        self.assertFalse(self.slave.host == 'a-host-that-shouldnt-be')

    @patch.object(slave.Lock, 'acquire_write', AsyncMock(
        spec=slave.Lock.acquire_write, return_value=AsyncMock()))
    @async_test
    async def test_enqueue_build(self):
        await self.slave.save()
        build = Mock(uuid='asdf')
        r = await self.slave.enqueue_build(build)
        await self.slave.reload()
        self.assertTrue(r)
        self.assertEqual(len(self.slave.enqueued_builds), 1)
        self.assertEqual(self.slave.queue_count, 1)

    @patch.object(slave.Lock, 'acquire_write', AsyncMock(
        spec=slave.Lock.acquire_write, return_value=AsyncMock()))
    @async_test
    async def test_enqueue_build_already_enqueued(self):
        await self.slave.save()
        build = Mock(uuid='asdf')
        await self.slave.enqueue_build(build)
        await self.slave.reload()
        r = await self.slave.enqueue_build(build)
        self.assertFalse(r)
        self.assertEqual(len(self.slave.enqueued_builds), 1)
        self.assertEqual(self.slave.queue_count, 1)

    @patch.object(slave.Lock, 'acquire_write', AsyncMock(
        spec=slave.Lock.acquire_write, return_value=AsyncMock()))
    @async_test
    async def test_dequeue_build(self):
        await self.slave.save()
        build = Mock(uuid='asdf')
        await self.slave.enqueue_build(build)
        r = await self.slave.dequeue_build(build)
        self.assertTrue(r)
        await self.slave.reload()
        self.assertEqual(len(self.slave.enqueued_builds), 0)
        self.assertEqual(self.slave.queue_count, 0)

    @patch.object(slave.Lock, 'acquire_write', AsyncMock(
        spec=slave.Lock.acquire_write, return_value=AsyncMock()))
    @async_test
    async def test_dequeue_build_not_enqueued(self):
        await self.slave.save()
        build = Mock(uuid='asdf')
        r = await self.slave.dequeue_build(build)
        self.assertFalse(r)
        self.assertEqual(len(self.slave.enqueued_builds), 0)
        self.assertEqual(self.slave.queue_count, 0)

    async def _create_test_data(self):
        await self.slave.save()
        self.repo = repository.Repository(
            name='reponame', url='git@somewhere', update_seconds=300,
            vcs_type='git', slaves=[self.slave], owner=self.owner)

        await self.repo.save()

        self.revision = repository.RepositoryRevision(
            repository=self.repo, branch='master', commit='bgcdf3123',
            commit_date=datetime.datetime.now(),
            author='tião', title='something'
        )

        await self.revision.save()

        self.buildset = await build.BuildSet.create(
            repository=self.repo, revision=self.revision)

        await self.buildset.save()

        self.builder = build.Builder(repository=self.repo, name='builder-1')
        await self.builder.save()
        self.other_builder = build.Builder(repository=self.repo,
                                           name='builder-2')
        await self.other_builder.save()
        await self.builder.save()

        self.build = build.Build(repository=self.repo, slave=self.slave,
                                 branch='master', named_tree='v0.1',
                                 builder=self.builder)

        self.buildset.builds.append(self.build)
        await self.buildset.save()
