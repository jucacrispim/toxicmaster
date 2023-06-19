Toxicmaster config
==================

The configuration of toxicmaster is done using the a configuration file. The configuration
file can be passed using the  ``-c`` flag to the ``toxicmaster`` command
or settings the environment variable ``TOXICMASTER_SETTINGS``.

This file is a python file, so do what ever you want with it.

Config values
-------------

.. note::

   Although the config is done using a config file, the default
   configuration file created by ``toxicmaster create`` can use
   environment variables instead.


* ``PORT`` - The port for the server to listen. Defaults to `1111`.
  Environment variable: ``MASTER_PORT``

* ``USE_SSL`` - Defaults to False.
  Environment variable: ``MASTER_USE_SSL``. Possible values are `0` or `1`.

* ``CERTIFILE`` - Path for a certificate file.
  Environment variable: ``MASTER_CERTIFILE``

* ``KEYFILE`` - Path for a key file.
  Environment variable: ``MASTER_KEYFILE``

* ``ACCESS_TOKEN`` - An sha512 encrypted string used to authenticate an
  incomming request.
  Environment variable: ``MASTER_ENCRYPTED_TOKEN``.

.. note::

   You can create a new access token using the ``toxicmaster create_token``
   command. For more information use:

   .. code-block:: sh

       $ toxicmaster create_token --help

* ``ZK_SERVERS`` - A list of zookeeper servers.
  Environment variable: ``ZK_SERVERS``. Servers must be comma separated.

* ``ZK_KWARGS`` - Arguments passed to zookeeper client. Check the
  `aiozk docs <https://aiozk.readthedocs.io/en/latest/api.html#zkclient>`_.


* ``DBHOST`` - Host for the database connection.
  Environment variable: ``SECRETS_DBHOST``.

* ``DBPORT`` - Port for the database connection. Defaults to `27017`.
  Environment variable: ``SECRETS_DBPORT``.

* ``DBNAME`` - The database name. Defaults to `toxicsecrets`.
  Environment variable: ``SECRETS_DBNAME``

* ``DBUSER`` - User name for authenticated access to the database
  Environment variable: ``SECRETS_DBUSER``

* ``DBPASS`` - Password for authenticated access to the database
  Environment variable: ``SECRETS_DBPASS``


* ``AMQP_HOST`` - host for the rabbitmq broker.
  Environment variable: ``AMQPHOST``

* ``AMQP_PORT`` - port for the rabbitmq broker.
  Environment variable: ``AMQPPORT``

* ``AMQP_LOGIN`` - login for the rabbitmq broker.
  Environment variable: ``AMQPLOGIN``

* ``AMQP_VIRTUALHOST`` - virtualhost for the rabbitmq broker.
  Environment variable: ``AMQPVIRTUALHOST``

* ``AMQP_PASSWORD`` - password for the rabbitmq broker.
  Environment variable: ``AMQPPASSWORD``


* ``POLLER_HOST`` - toxicpoller's host
  Environment variable: ``POLLER_HOST``

* ``POLLER_PORT`` - toxicpoller's port
  Environment variable: ``POLLER_PORT``

* ``POLLER_TOKEN`` - toxicpoller's auth token
  Environment variable: ``POLLER_TOKEN``

* ``POLLER_USES_SSL`` - Does toxicpoller use ssl connections?
  Environment variable: ``POLLER_USES_SSL``

* ``VALIDATE_CERT_POLLER`` - Should the poller certificate be validated?
  Environment variable: ``VALIDATE_CERT_POLLER``


* ``SECRETS_HOST`` - toxicsecrets's host
  Environment variable: ``SECRETS_HOST``

* ``SECRETS_PORT`` - toxicsecrets's port
  Environment variable: ``SECRETS_PORT``

* ``SECRETS_TOKEN`` - toxicsecrets's auth token
  Environment variable: ``SECRETS_TOKEN``

* ``SECRETS_USES_SSL`` - Does toxicsecrets use ssl connections?
  Environment variable: ``SECRETS_USES_SSL``

* ``VALIDATE_CERT_SECRETS`` - Should the secrets certificate be validated?
  Environment variable: ``VALIDATE_CERT_SECRETS``
