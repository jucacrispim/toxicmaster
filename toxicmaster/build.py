# -*- coding: utf-8 -*-

# Copyright 2015-2020, 2023 Juca Crispim <juca@poraodojuca.net>

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

import asyncio
from asyncio import ensure_future
from collections import defaultdict, deque
import copy
from datetime import timedelta
import json
import traceback
from uuid import uuid4, UUID

from bson.json_util import CANONICAL_JSON_OPTIONS
from mongoengine.queryset import queryset_manager
from mongomotor import Document, EmbeddedDocument
from mongomotor.fields import (StringField, ListField, EmbeddedDocumentField,
                               ReferenceField, DateTimeField, UUIDField,
                               IntField, EmbeddedDocumentListField)
from toxiccore.build_config import list_builders_from_config
from toxiccore.utils import (now, datetime2string, MatchKeysDict,
                             format_timedelta, LoggerMixin,
                             localtime2utc, set_tzinfo)
from toxiccommon.exchanges import (
    notifications,
    integrations_notifications
)
from .document import ExternalRevisionIinfo
from .exceptions import (DBError, ImpossibleCancellation)
from .signals import (build_added, build_cancelled,
                      buildset_started, buildset_finished,
                      buildset_added)
from .utils import (get_build_config_type,
                    get_build_config_filename)


# The statuses used in builds  ordered by priority.
ORDERED_STATUSES = ['running', 'cancelled', 'exception', 'fail',
                    'warning', 'success', 'preparing', 'pending']


class SerializeMixin:

    """Simple mixin to serialization relatad stuff."""

    def to_dict(self, id_as_str=True):
        """ Transforms a Document into a dictionary.

        :param id_as_str: If true, transforms the id field into a string.
        """

        objdict = json.loads(super().to_json(
            json_options=CANONICAL_JSON_OPTIONS))
        objdict['id'] = str(self.id) if id_as_str else self.id
        return objdict

    async def async_to_json(self):
        """Async version of to_json. Expects a to_dict coroutine."""

        objdict = await self.to_dict()
        return json.dumps(objdict)  # pragma no cover stupid coverage


class Builder(SerializeMixin, Document):

    """ The entity responsible for executing the build steps.
    """

    # you don't have 10000 builders, right? RIGHT?
    DEFAULT_POSITION = 10000

    name = StringField(required=True)
    """The name of the builder."""

    repository = ReferenceField('toxicmaster.Repository')
    """A referece to the :class:`~toxicmaster.repository.Repository` that
    owns the builder"""

    position = IntField(required=False, default=10000)
    """The position for the builder to be displayed in the waterfall.
    It is acording to the order of the definition in the build config
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # a attribute we don't save because we get it from the config
        # in a revision basis
        self.triggered_by = []

    @classmethod
    async def create(cls, **kwargs):
        """Creates a new Builder.

        :param kwargs: kwargs passed to the builder constructor"""
        builder = cls(**kwargs)
        await builder.save()
        return builder

    @classmethod
    async def get(cls, **kwargs):
        """Returns a builder instance."""
        builder = await cls.objects.get(**kwargs)
        return builder

    @classmethod
    async def get_or_create(cls, **kwargs):
        """Returns a builder instance. If it does not exist, creates it.

        :param kwargs: kwargs to match the builder."""
        no_order_kw = kwargs.copy()
        position = no_order_kw.pop('position', cls.DEFAULT_POSITION)
        try:
            builder = await cls.get(**no_order_kw)
        except cls.DoesNotExist:
            builder = await cls.create(**kwargs)
        else:
            if builder.position != position:
                builder.position = position
                await builder.save()

        return builder

    async def get_status(self):
        """Returns the builder status."""

        try:
            qs = BuildSet.objects(builds__builder=self).order_by('-created')
            last_buildset = await qs[0]
        except (IndexError, AttributeError):
            status = 'idle'
        else:
            statuses = []
            for build in last_buildset.builds:
                builder = await build.builder
                if builder == self:
                    statuses.append(build.status)

            ordered_statuses = sorted(statuses,
                                      key=lambda i: ORDERED_STATUSES.index(i))
            status = ordered_statuses[0]

        return status

    async def to_dict(self):
        """Returns a dictionary for this builder."""

        objdict = super().to_dict(id_as_str=True)
        objdict['status'] = await self.get_status()
        objdict['position'] = int(objdict['position']['$numberInt'])
        return objdict

    async def to_json(self):
        """Returns a json for this builder."""
        j = await self.async_to_json()
        return j  # pragma no cover stupid coverage


class BuildStep(EmbeddedDocument):

    """ A step for a build. This is the object that will store
    the step data. Who actually execute the steps is the slave.
    """

    DoesNotExist = Builder.DoesNotExist

    RUNNING = 'running'
    FAIL = 'fail'
    SUCCESS = 'success'
    EXCEPTION = 'exception'
    WARNING = 'warning'
    CANCELLED = 'cancelled'
    STATUSES = [RUNNING, FAIL, SUCCESS, EXCEPTION, WARNING, CANCELLED]

    repository = ReferenceField('toxicmaster.Repository', required=True)
    """A referece to :class:`~toxicmaster.repository.Repository`
    """

    uuid = UUIDField(required=True, default=lambda: uuid4())
    """The uuid that indentifies the build step"""

    name = StringField(required=True)
    """The name of the step. Will be displayed in the ui."""

    command = StringField(required=True)
    """The command that executes the step"""

    status = StringField(choices=STATUSES)
    """The current status of the step. May be one of the values in STATUSES`"""

    output = StringField()
    """The output of the step"""

    started = DateTimeField(default=None)
    """When the step stated. It msut be in UTC."""

    finished = DateTimeField(default=None)
    """When the step finished. It msut be in UTC."""

    index = IntField(requred=True)
    """The index of the step in the build."""

    total_time = IntField()
    """The total time spen in the step."""

    def to_dict(self, output=True):
        """Returns a dict representation of the BuildStep.

        :param output: Indicates if the output of the step should be included.
        """

        objdict = {'uuid': str(self.uuid), 'name': self.name,
                   'command': self.command, 'status': self.status,
                   'index': self.index}

        if output:
            objdict['output'] = self.output

        if not self.started:
            objdict['started'] = None
        else:
            objdict['started'] = datetime2string(self.started)

        if not self.finished:
            objdict['finished'] = None
        else:
            objdict['finished'] = datetime2string(self.finished)

        total = format_timedelta(timedelta(seconds=self.total_time)) \
            if self.total_time is not None else ''
        objdict['total_time'] = total

        return objdict

    async def notify(self, event_type, repo_id):
        msg = self.to_dict()
        msg.update({'repository_id': str(repo_id),
                    'event_type': event_type})
        await notifications.publish(msg)
        await integrations_notifications.publish(msg)

    def to_json(self):
        """Returns a json representation of the BuildStep."""

        return json.dumps(self.to_dict())

    @classmethod
    async def get(cls, uuid):
        """Returns a step based on a uuid.

        :param uuid: The uuid of the step."""

        if isinstance(uuid, str):
            uuid = UUID(uuid)

        pipeline = [
            {"$match": {"builds.steps.uuid": uuid}},
            {'$unwind': '$builds'},
            {"$match": {"builds.steps.uuid": uuid}},
            {"$project": {
                "steps": {
                    '$filter': {
                        'input': '$builds.steps',
                        'as': 'step',
                        'cond': {'$eq': ['$$step.uuid', uuid]}
                    }
                },
            }},
        ]

        r = await BuildSet.objects().aggregate(pipeline).to_list(1)

        try:
            step_doc = r[0]['steps'][0]
        except IndexError:
            raise cls.DoesNotExist
        else:
            build = cls(**step_doc)

        return build


class BuildTrigger(EmbeddedDocument):
    """A configuration for what triggers a build."""

    builder_name = StringField()
    """The name of a builder"""

    statuses = ListField(StringField())
    """A list of statuses that trigger a build."""


class Build(EmbeddedDocument, LoggerMixin):

    """ A set of steps for a repository. This is the object that stores
    the build data. The build is carried by the slave.
    """

    DoesNotExist = Builder.DoesNotExist

    PENDING = 'pending'
    PREPARING = 'preparing'
    STATUSES = BuildStep.STATUSES + [PENDING, PREPARING]
    CONFIG_TYPES = ['py', 'yaml']

    uuid = UUIDField(required=True, default=lambda: uuid4())
    """An uuid that identifies the build"""

    repository = ReferenceField('toxicmaster.Repository', required=True)
    """A referece to the :class:`~toxicmaster.repository.Repository` that
    owns the build"""

    slave = ReferenceField('toxicmaster.slave.Slave')
    """A reference to the :class:`~toxicmaster.slave.Slave` that will
    execute the build."""

    branch = StringField(required=True)
    """The branch of the code that will be tested."""

    named_tree = StringField(required=True)
    """A identifier of the commit, a sha, a tag name, etc..."""

    started = DateTimeField()
    """When the build was started. It must be in UTC."""

    finished = DateTimeField()
    """When the build was finished. It must be in UTC."""

    builder = ReferenceField(Builder, required=True)
    """A reference to an instance of
    :class:`~toxicmaster.build.Builder`.
    """

    status = StringField(default=PENDING, choices=STATUSES)
    """The current status of the build. May be on of the values in
    :attr:`~toxicmaster.build.Build.STATUSES`.
    """

    steps = ListField(EmbeddedDocumentField(BuildStep))
    """A list of :class:`~toxicmaster.build.BuildStep`"""

    total_time = IntField()
    """The total time of the build execution."""

    external = EmbeddedDocumentField(ExternalRevisionIinfo)
    """A reference to
      :class:`~toxicmaster.document.ExternalRevisionIinfo`"""

    builders_from = StringField()
    """Indicates the branch from which the builders for this build came from.
    This may not be the same as the build branch."""

    number = IntField(required=True, default=0)
    """A sequencial number for builds in the repository"""

    triggered_by = EmbeddedDocumentListField(BuildTrigger)
    """A list of configurations for build triggers"""

    def _get_builder_dict(self):
        builder = self._data.get('builder')
        d = {'id': str(builder.id)}
        builder_name = getattr(builder, 'name', None)
        if builder_name:
            d['name'] = builder_name

        return d

    def to_dict(self, output=True, steps_output=None):
        """Transforms the object into a dictionary.

        :param output: Should we include the build output?
        :param steps_output: Should we include the steps output? If None, the
          the value of ``output`` will be used.
        """

        objdict = {'uuid': str(self.uuid), 'named_tree': self.named_tree,
                   'branch': self.branch, 'status': self.status,
                   'number': self.number}

        steps_output = output if steps_output is None else steps_output
        steps = [s.to_dict(output=steps_output) for s in self.steps]
        objdict['builder'] = self._get_builder_dict()
        objdict['steps'] = steps
        objdict['started'] = datetime2string(
            self.started) if self.started else ''
        objdict['finished'] = datetime2string(
            self.finished) if self.finished else ''
        if self.total_time is not None:
            td = timedelta(seconds=self.total_time)
            objdict['total_time'] = format_timedelta(td)
        else:
            objdict['total_time'] = ''

        if self.external:
            objdict['external'] = self.external.to_dict()
        else:
            objdict['external'] = {}

        objdict['output'] = self.output if output else ''
        return objdict

    def to_json(self):
        """Returns a json representation of the buld."""

        objdict = self.to_dict()
        return json.dumps(objdict)

    async def update(self):
        """Does an atomic update in this embedded document."""

        qs = BuildSet.objects.no_cache().filter(builds__uuid=self.uuid)
        result = await qs.update(set__builds__S=self)

        if not result:
            msg = 'This Build was not saved to database.'
            msg += ' You can\'t update it.'
            raise DBError(msg)

        return result

    async def get_buildset(self):
        """Returns the buildset that 'owns' this build."""
        buildset = await BuildSet.objects.no_cache().get(
            builds__uuid=self.uuid)
        return buildset

    @property
    def output(self):
        """The build output. It is the commands + the output of the steps."""
        output = []
        for step in self.steps:
            output.append(step.command + '\n')
            output.append(step.output or '')
            output.append('\n\n')

        return ''.join(output)

    @classmethod
    async def get(cls, uuid):
        """Returns a build based on a uuid.

        :param uuid: The uuid of the build."""

        if isinstance(uuid, str):
            uuid = UUID(uuid)

        pipeline = [
            {"$match": {"builds.uuid": uuid}},
            {"$project": {
                "builds": {
                    "$filter": {
                        "input": "$builds", "as": "build",
                        "cond": {"$eq": ["$$build.uuid", uuid]}}}
            }}
        ]

        r = await BuildSet.objects().aggregate(pipeline).to_list(1)
        try:
            build_doc = r[0]['builds'][0]
        except IndexError:
            raise Build.DoesNotExist
        else:
            build = cls(**build_doc)

        return build

    async def notify(self, event_type):
        """Send a notification to the `build_notification` exchange
        informing about `event_type`

        :param event_type: The name of the event."""
        msg = self.to_dict()
        repo = await self.repository
        builder = await self.builder
        msg['repository'] = await repo.to_dict()
        msg['builder'] = await builder.to_dict()
        msg['status'] = self.status
        msg.update({'repository_id': str(repo.id),
                    'event_type': event_type})
        await notifications.publish(msg)
        await integrations_notifications.publish(msg)

    async def cancel(self):
        """Cancel the build (oh, really?)"""

        cancel_statuses = [type(self).PENDING, BuildStep.RUNNING]
        if self.status not in cancel_statuses:
            raise ImpossibleCancellation

        repo = await self.repository
        slave = await self.slave
        if self.status == BuildStep.RUNNING:
            try:
                await slave.cancel_build(self)
            except Exception:
                self.log('Error canceling running build', level='error')
                return False
        else:
            if slave:
                await slave.dequeue_build(self)

            self.status = 'cancelled'
            await self.update()
            build_cancelled.send(str(repo.id), build=self)

        return True

    async def set_slave(self, slave):
        """Sets the slave for this build and increments the slave queue.

        :param slave: An :class:`~toxicmaster.slave.Slave` instance.
        """
        self.log(
            'Adding slave {} to build {}'.format(slave.name, self.uuid),
            level='debug')
        self.slave = slave
        await self.update()
        await slave.enqueue_build(self)

    async def is_ready2run(self):
        """Checks if all trigger conditions are met. If not triggered_by
        the build is ready. If the return value is None it means that
        the build must be cancelled because trigger conditions can't be met.
        """
        try:
            b = await type(self).get(self.uuid)
        except type(self).DoesNotExist:
            self.log(f'build {self.uuid} does not exist. not ready2run',
                     level='warning')
            return False

        self.status = b.status
        if self.status != type(self).PENDING:
            return False

        if not self.triggered_by:
            return True

        ok = await self._check_build_rules()
        return ok

    async def set_unknown_exception(self, output):
        """Marks a build with exception status and appends a
        new step also with exception status with ``traceback``
        as its output.
        """
        self.status = 'exception'
        self.started = self.started or localtime2utc(now())
        self.finished = self.finished or localtime2utc(now())
        repo = await self.repository
        exception_step = BuildStep(repository=repo, output=output,
                                   started=localtime2utc(now()),
                                   finished=localtime2utc(now()),
                                   status='exception',
                                   command='', name='exception')
        self.steps.append(exception_step)
        await self.update()

    async def _check_build_rules(self):
        rules = MatchKeysDict()
        for doc in self.triggered_by:
            rules[doc.builder_name] = doc.statuses

        buildset = await self.get_buildset()
        ok = []
        triggered_count = len(self.triggered_by)
        for build in buildset.builds:
            if build.uuid == self.uuid:
                continue

            builder = await build.builder
            name = builder.name
            status = build.status

            if not rules.get(name) or status == build.PENDING:
                # If there's no rule for this builder or the build is
                # pending we don't take it into account.
                continue

            if status not in rules[name]:
                # The build finished with a status other than the ones that
                # trigger this build. This build must be cancelled.
                return None

            # if we got to this point means the rule for the build is ok
            ok.append(True)

        # So here if len(ok) == triggered_count means all rules are ok
        ready = True if len(ok) == triggered_count else False
        return ready


class BuildSet(SerializeMixin, LoggerMixin, Document):

    """A list of builds associated with a revision."""

    NO_BUILDS = 'no builds'
    NO_CONFIG = 'no config'
    PENDING = Build.PENDING
    STATUSES = [NO_BUILDS, NO_CONFIG] + Build.STATUSES

    repository = ReferenceField('toxicmaster.Repository',
                                required=True)
    """A referece to the :class:`~toxicmaster.repository.Repository` that
    owns the buildset"""

    revision = ReferenceField('toxicmaster.RepositoryRevision',
                              required=True)
    """A reference to the
    :class:`~toxicmaster.repository.RepositoryRevision` that generated
    this buildset."""

    commit = StringField(required=True)
    """The identifier of the commit that generated the buildset."""

    commit_date = DateTimeField(required=True)
    """The date of the commit"""

    commit_body = StringField()
    """The body of the commit."""

    branch = StringField(required=True)
    """The branch of the commit"""

    author = StringField()
    """Commit author's name."""

    title = StringField()
    """Commit title"""

    builds = ListField(EmbeddedDocumentField(Build))
    """A list of :class:`~toxicmaster.build.Build` intances."""

    created = DateTimeField(default=now)
    """When the BuildSet was first created. It must be in UTC."""

    started = DateTimeField()
    """When the BuildSet started to run. It must be in UTC."""

    finished = DateTimeField()
    """When the buildset finished. It must be in UTC."""

    total_time = IntField()
    """The total time spent in the buildset"""

    status = StringField(default=PENDING, choices=STATUSES)
    """The current status of the buildset. May be on of the values in
    :attr:`~toxicmaster.build.BuildSet.STATUSES`.
    """

    number = IntField(required=True)
    """A sequencial number for the buildsets in the repository"""

    meta = {
        'indexes': [
            'repository',
            'branch',
            'builds.uuid',
            'builds.steps.uuid',
        ]
    }

    _running_tasks = set()

    @queryset_manager
    def objects(doc_cls, queryset):  # pylint: disable=no-self-argument
        """The default querymanager for BuildSet"""
        return queryset.order_by('created')

    async def notify(self, event_type, status=None):
        """Notifies an event to the notifications exchange.

        :param event_type: The event type to notify about
        :param status: The status of the buildset. If None, the value of
          :attr:`~toxicmaster.build.Buildset.status` will be used."""

        self.log('notifying buildset {}'.format(event_type), level='debug')
        msg = self.to_dict()
        repo = await self.repository
        msg['repository'] = await repo.to_dict()
        msg['event_type'] = event_type
        msg['status'] = status or self.status
        msg['repository_id'] = str(repo.id)
        await notifications.publish(msg)
        await integrations_notifications.publish(msg)

    @classmethod
    async def _get_next_number(cls, repository):
        buildset = cls.objects.filter(repository=repository).order_by(
            '-number')
        buildset = await buildset.first()
        if buildset:
            n = buildset.number + 1
        else:
            n = 1
        return n

    @classmethod
    async def create(cls, repository, revision):
        """Creates a new buildset.

        :param repository: An instance of `toxicmaster.Repository`.
        :param revision: An instance of `toxicmaster.RepositoryRevision`.
        :param save: Indicates if the instance should be saved to database.
        """
        number = await cls._get_next_number(repository)
        buildset = cls(repository=repository, revision=revision,
                       commit=revision.commit,
                       commit_date=revision.commit_date,
                       branch=revision.branch, author=revision.author,
                       title=revision.title, number=number,
                       commit_body=revision.body)
        await buildset.save()
        t = ensure_future(buildset.notify('buildset-added'))
        cls._running_tasks.add(t)
        t.add_done_callback(lambda t: cls._running_tasks.remove(t))
        return buildset

    def to_dict(self, builds=True):
        """Returns a dict representation of the object

        :param builds: Should the builds be included in the dict?"""

        repo_id = str(self._data.get('repository').id)
        objdict = {'id': str(self.id), 'commit': self.commit,
                   'branch': self.branch, 'author': self.author,
                   'title': self.title, 'repository': {'id': repo_id},
                   'status': self.status, 'number': self.number}
        objdict['commit_date'] = datetime2string(self.commit_date)
        objdict['commit_body'] = self.commit_body
        objdict['created'] = datetime2string(self.created)
        objdict['started'] = datetime2string(self.started) if self.started \
            else ''
        objdict['finished'] = datetime2string(self.finished) if self.finished \
            else ''

        if self.total_time is not None:
            td = timedelta(seconds=self.total_time)
            objdict['total_time'] = format_timedelta(td)
        else:
            objdict['total_time'] = ''

        objdict['builds'] = []
        if builds:
            for b in self.builds:
                bdict = b.to_dict(output=False)
                objdict['builds'].append(bdict)
        return objdict

    def to_json(self):
        """Returns a json representation of the object."""
        objdict = self.to_dict()
        return json.dumps(objdict)

    async def update_status(self, status=None):
        """Updates the status of the buildset.

        :param status: Status to update the buildset. If None,
          ``self.get_status()`` will be used."""

        status = status or self.get_status()
        self.log('Updating status to {}'.format(status), level='debug')
        self.status = status
        await self.save()

    def get_status(self):
        """Returns the status of the BuildSet"""

        if not self.builds:
            return self.NO_BUILDS

        build_statuses = set([b.status for b in self.builds])
        ordered_statuses = sorted(build_statuses,
                                  key=lambda i: ORDERED_STATUSES.index(i))
        status = ordered_statuses[0]

        return status

    def get_pending_builds(self):
        """Returns the pending builds of the buildset."""

        return [b for b in self.builds if b.status == Build.PENDING]

    @classmethod
    def _from_aggregate(cls, doc):
        doc['id'] = doc['_id']
        del doc['_id']
        for build in doc['builds']:
            builder_doc = build['builder']
            builder_doc['id'] = builder_doc['_id']
            del builder_doc['_id']
            builder = Builder(**builder_doc)
            build['builder'] = builder
        buildset = cls(**doc)
        return buildset

    @classmethod
    async def aggregate_get(cls, **kwargs):
        """Returns information about a buildset Uses the aggregation
        framework to $lookup on builds' builder name and on repository.
        I does not returns steps information, only buildset and builds
        information.

        :param kwargs: Named arguments to match the buildset.
        """

        pipeline = [
            {'$unwind': '$builds'},
            {'$lookup': {'from': 'builder',
                         'localField': 'builds.builder',
                         'foreignField': '_id',
                         'as': 'builder_doc'}},

            {'$project':
             {'build': {"uuid": "$builds.uuid",
                        "status": "$builds.status",
                        "builder": {'$arrayElemAt': ["$builder_doc", 0]}},
              'doc': "$$ROOT"}},

            {'$group': {'_id': '$_id', 'builds': {'$push': "$build"},
                        'doc': {'$first': '$doc'}}},

            {"$project":
             {"builds": "$builds",
              "status": "$doc.status",
              'repository': '$doc.repository',
              'commit_date': '$doc.commit_date',
              'started': '$doc.started',
              'finished': '$doc.finished',
              'total_time': '$doc.total_time',
              "branch": "$doc.branch",
              "title": "$doc.title",
              "commit_body": "$doc.commit_body",
              "number": "$doc.number",
              'commit': '$doc.commit',
              'author': '$doc.author'}},

        ]
        buildset_doc = (await cls.objects(**kwargs).aggregate(
            pipeline).to_list(1))[0]
        buildset = cls._from_aggregate(buildset_doc)
        return buildset

    async def get_builds_for(self, builder=None, branch=None):
        """Returns the builds for a specific builder and/or branch.

        :param builder: An instance of
          :class:`~toxicmaster.build.Builder`.
        :param branch: The name of the branch."""

        async def match_builder(b):
            if not builder or (builder and (await b.builder).id == builder.id):
                return True
            return False

        def match_branch(b):
            if not branch or b.branch == branch:
                return True
            return False

        builds = []
        for build in self.builds:
            if await match_builder(build) and match_branch(build):
                builds.append(build)
        return builds

    async def add_build(self, build):
        self.builds.append(build)
        await self.save()
        repo = await self.repository
        build_added.send(str(repo.id), build=build)
        await build.notify('build-added')


class BuildExecuter(LoggerMixin):
    """Class responsible for executing builds taking care of wich builds
    can be executed in parallel, which ones are triggered and what are
    the repository's parallel builds limit.
    """

    def __init__(self, repository, builds):
        self.repository = repository
        self.builds = builds
        self._queue = copy.copy(self.builds)
        self._running = 0
        # keep references to avoid the tasks to be garbage colected
        self._tasks = set()

    async def _run_build(self, build):
        self._running += 1
        type(self.repository).add_running_build()
        try:
            slave = await build.slave
            envvars = self.repository.envvars
            if not build.external:
                try:
                    secrets = await self.repository.get_secrets()
                except Exception as e:
                    self.log(str(e), level='error')
                    self.log('secrets not available', level='error')
                    secrets = {}
                envvars.update(secrets)
            await slave.build(build, **envvars)
        except Exception:
            tb = traceback.format_exc()
            self.log(tb, level='debug')
            await build.set_unknown_exception(tb)

        finally:
            self._queue.remove(build)
            type(self.repository).remove_running_build()
            self._running -= 1

        t = asyncio.ensure_future(self._execute_builds())
        self._tasks.add(t)
        t.add_done_callback(lambda t: self._tasks.remove(t))

    async def _execute_builds(self):
        await self.repository.reload()
        for build in self.builds:
            ready = await build.is_ready2run()
            parallel = self.repository.parallel_builds
            limit_ok = self._running < parallel if parallel else True
            if ready and limit_ok:
                t = asyncio.ensure_future(self._run_build(build))
                self._tasks.add(t)
                t.add_done_callback(lambda t: self._tasks.remove(t))

            elif ready is None:
                await build.cancel()
                self._queue.remove(build)

        await self._handle_queue_changes()

    async def _handle_queue_changes(self):
        """Builds statuses may be changed from outside (i.e. a build was
        cancelled) so here we handle this.
        """
        queued_statuses = [Build.PENDING, Build.PREPARING, BuildStep.RUNNING]
        buildset = await self.builds[0].get_buildset()
        for build in buildset.builds:
            bad_status = build.status not in queued_statuses
            if bad_status and build in self._queue:
                self._queue.remove(build)

    async def execute(self):
        # Here the better solution would be something à la mongomotor
        # and its use of futures/set_result stuff. Maybe latter...
        self.log('Executing builds for {}'.format(self.repository.id),
                 level='debug')
        asyncio.ensure_future(self._execute_builds())
        while self._queue:
            await asyncio.sleep(0.5)

        self.log('Builds for {} done!'.format(self.repository.id),
                 level='debug')

        return True


class BuildManager(LoggerMixin):

    """ Controls which builds should be executed sequentially or
    in parallel.
    """
    # Note that this core reached its limit. It really needs a good
    # refactor, so we can implement builds that trigger other builds
    # in other slaves in a (almost) simple way.

    # each repository has its own queue
    _build_queues = defaultdict(deque)
    # to keep track of which repository is already working
    # on consume its queue
    _is_building = defaultdict(lambda: False)
    _running_tasks = set()

    def __init__(self, repository):
        """:param repository: An instance of
          :class:`~toxicmaster.repository.Repository.`"""
        self.repository = repository
        self._is_getting_builders = False
        self._is_connected_to_signals = False
        self.config_type = get_build_config_type()
        self.config_filename = get_build_config_filename()

    @property
    def build_queues(self):
        """Returns the build queues for a repository."""

        return self._build_queues[self.repository.id]

    @property
    def is_building(self):
        """Indicates if has some active build for a repository."""

        return self._is_building[self.repository.id]

    @is_building.setter
    def is_building(self, building):
        self._is_building[self.repository.id] = building

    async def add_builds(self, revisions):
        """ Adds the builds for a given revision in the build queue.

        :param revision: A list of
          :class:`toxicmaster.RepositoryRevision` instances for the
          build.
        """

        last_bs = None
        for revision in revisions:
            if not revision.create_builds():
                continue

            buildset = await BuildSet.create(repository=self.repository,
                                             revision=revision)
            if not revision.config:
                buildset.status = type(buildset).NO_CONFIG
                await buildset.save()
                buildset_added.send(str(self.repository.id), buildset=buildset)
                continue

            conf = self.repository.get_config_for(revision)

            last_bs = buildset
            builders_conf = revision.get_builders_conf()
            builders, builders_origin = await self.get_builders(
                revision, conf, include=builders_conf['include'],
                exclude=builders_conf['exclude'])
            await self.add_builds_for_buildset(
                buildset, conf, builders=builders,
                builders_origin=builders_origin)

        if last_bs and self.repository.notify_only_latest(buildset.branch):
            await self.cancel_previous_pending(buildset)

    async def _get_highest_build_number(self):
        buildset = await BuildSet.objects(
            repository=self.repository, builds__number__gt=0).order_by(
                '-builds__number').first()
        if not buildset:
            highest = 0
        else:
            highest = max([b.number for b in buildset.builds]) \
                if buildset.builds else 0
        return highest

    def _handle_build_triggered_by(self, build, builders):
        """So, when a buildset doesn't have all its builders we need
        to handle the triggered_by config here otherwise we may end with
        builds that can't start because of triggered_by rules.
        """

        rules = []
        builder_names = [b.name for b in builders]
        for rule in build.triggered_by:
            if rule.builder_name in builder_names:
                rules.append(rule)

        build.triggered_by = rules

    async def add_builds_for_buildset(self, buildset, conf, builders=None,
                                      builders_origin=None):
        """Adds builds for for a given buildset.

        :param buildset: An instance of :class:`toxicmaster.BuildSet`.
        :param builders: A list of :class:`toxicmaster.Builder`. If
          not builders all builders for this slave and revision will be used.
        """

        builders = builders or []
        revision = await buildset.revision
        if not builders:
            builders, builders_origin = await self.get_builders(revision,
                                                                conf)

        last_build = await self._get_highest_build_number()
        for builder in builders:
            last_build += 1
            build = Build(repository=self.repository, branch=revision.branch,
                          named_tree=revision.commit,
                          builder=builder, builders_from=builders_origin,
                          number=last_build,
                          triggered_by=builder.triggered_by)
            self._handle_build_triggered_by(build, builders)
            await buildset.add_build(build)

            self.log('build {} added for named_tree {} on branch {}'.format(
                last_build, revision.commit, revision.branch), level='debug')

        self.build_queues.append(buildset)
        # We send the buildset_added signal here so we already have all
        # information about builds.
        buildset_added.send(str(self.repository.id), buildset=buildset)
        if not self.is_building:  # pragma: no branch
            t = ensure_future(self._execute_builds())
            type(self)._running_tasks.add(t)
            t.add_done_callback(lambda t: type(self)._running_tasks.remove(t))

    def _filter_builders(self, builders_conf, include, exclude):
        if include:
            builders_conf = [b for b in builders_conf if b['name'] in include]
        elif exclude:
            builders_conf = [b for b in builders_conf if b['name']
                             not in exclude]

        return builders_conf

    async def get_builders(self, revision, conf, include=None, exclude=None):
        """ Get builders for a given revision.

        :param revision: A
          :class:`toxicmaster.repository.RepositoryRevision`.
        :param conf: The build configuration.
        :param include: A list of builder names to include. Builders not
          in this list will not be returned.
        :param exclude: A list of builder names to exclude. Builders in
          this list will not be returned.
        """

        self.log('Getting builders for {} on {}'.format(self.repository.id,
                                                        revision.commit),
                 level='debug')

        origin = revision.branch
        try:
            builders_conf = self._get_builders_conf(conf, revision.branch)

        except AttributeError:
            self.log('Bad config for {} on {}'.format(self.repository.id,
                                                      revision.commit),
                     level='error')
            return [], origin

        if not builders_conf and revision.builders_fallback:
            origin = revision.builders_fallback
            builders_conf = self._get_builders_conf(
                conf, revision.builders_fallback)

        builders = []
        builders_conf = self._filter_builders(builders_conf, include, exclude)
        for i, bconf in enumerate(builders_conf):
            name = bconf['name']
            triggered_by = bconf.get('triggered_by', [])
            builder = await Builder.get_or_create(
                name=name, repository=self.repository, position=i)
            builder.triggered_by = triggered_by
            builders.append(builder)

        return builders, origin

    def _get_builders_conf(self, conf, branch):
        builders = list_builders_from_config(
            conf, branch, config_type=self.config_type)
        return builders

    async def cancel_build(self, build_uuid):
        """Cancel a given build.

        :param build_uuid: The uuid that indentifies the build to be cancelled.
        """

        build = await Build.get(build_uuid)
        try:
            await build.cancel()
            await build.notify('build-cancelled')
            build_cancelled.send(str(self.repository.id), build=build)
        except ImpossibleCancellation:
            self.log('Could not cancel build {}'.format(build_uuid),
                     level='warning')

    async def cancel_previous_pending(self, buildset):
        """Cancels the builds previous to ``buildset``.

        :param buildset: An instance of
          :class:`~toxicmaster.build.BuildSet`.
        """

        repo = await buildset.repository
        cancel_statuses = [Build.PENDING, BuildStep.RUNNING]
        to_cancel = type(buildset).objects(
            repository=repo, branch=buildset.branch,
            builds__status__in=cancel_statuses, created__lt=buildset.created)

        async for buildset in to_cancel:  # pragma no branch stupid coverage
            for build in buildset.builds:
                try:
                    await build.cancel()
                except ImpossibleCancellation:
                    pass

    async def start_pending(self):
        """Starts all pending buildsets that are not already scheduled for
        ``self.repository``."""

        buildsets = BuildSet.objects(builds__status=BuildSet.PENDING,
                                     repository=self.repository)
        buildsets = await buildsets.to_list()
        for buildset in buildsets:
            # we schedule pending builds only if the repo is idle.
            if not self.build_queues and not self.is_building:

                self.log('scheduling penging builds for {}'.format(
                    self.repository.id), level='debug')
                self.log('schedule pending buildset {}'.format(str(
                    buildset.id)), level='debug')

                self.build_queues.append(buildset)
                t = ensure_future(self._execute_builds())
                type(self)._running_tasks.add(t)
                t.add_done_callback(
                    lambda t: type(self)._running_tasks.remove(t))

    async def _set_started_for_buildset(self, buildset):
        if not buildset.started:
            buildset.started = localtime2utc(now())
            buildset.status = 'running'
            buildset_started.send(str(self.repository.id), buildset=buildset)
            await buildset.save()
            await buildset.notify('buildset-started', status='running')
            await self.repository.set_latest_buildset(buildset)
            self.log('Buildset {} started'.format(buildset.id))

    async def _set_finished_for_buildset(self, buildset):
        # reload it so we get the right info about builds and status
        buildset = await type(buildset).objects.get(id=buildset.id)

        just_now = localtime2utc(now())
        if not buildset.finished or set_tzinfo(
                buildset.finished, 0) < just_now:
            buildset.finished = just_now
            buildset.total_time = int((
                buildset.finished - set_tzinfo(buildset.started, 0)).seconds)
            await buildset.save()
            await buildset.update_status()
            buildset_finished.send(str(self.repository.id), buildset=buildset)
            await buildset.notify('buildset-finished')
            await self.repository.set_latest_buildset(buildset)
            self.log('Buildset {} finished'.format(buildset.id))

    async def _set_slave(self, build):
        """Sets a slave for a build based on which slave has the
        smaller queue.
        """
        slaves = await self.repository.slaves
        slave_ids = [s.id for s in slaves]
        qs = type(slaves[0]).objects.filter(
            id__in=slave_ids).order_by('queue_count')
        slave = await qs.first()

        assert slave, "No slave found!"
        await build.set_slave(slave)

    async def _execute_builds(self):
        """ Execute the buildsets in the queue of a repository
        """

        repo = self.repository
        self.log('executing builds for {}'.format(repo.id),
                 level='debug')
        slaves = await repo.slaves
        if not slaves:
            self.log('No slaves. Can\'t execute builds.', level='debug')
            return False

        self.is_building = True
        try:
            # here we take the buildsets that are in queue and send
            # each one of them to a slave to execute the builds
            while True:
                try:
                    buildset = self.build_queues.popleft()
                except IndexError:
                    break

                builds = []
                for build in buildset.builds:
                    # we need to reload it here so we can get the
                    # updated status of the build (ie cancelled)
                    build = await type(build).get(build.uuid)
                    await self._set_slave(build)
                    if build.status == type(build).PENDING:
                        builds.append(build)

                if builds:
                    await self._set_started_for_buildset(buildset)
                    executer = BuildExecuter(self.repository, builds)
                    await executer.execute()
                    await self._set_finished_for_buildset(buildset)
                    self.log('builds for {} finished'.format(repo.id),
                             level='debug')
        finally:
            self.is_building = False
            for slave in slaves:
                await slave.stop_instance()

        return True
