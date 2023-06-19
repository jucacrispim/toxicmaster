:tocdepth: 1

Toxicmaster: Keeps the plates spinning
======================================

Toxicmaster does the coordination of the distinct parts of toxicbuild.

Install
-------

To install it use pip:

.. code-block:: sh

   $ pip install toxicmaster



Setup & config
--------------

Before running the program you must create an environment for toxicmaster.
To do so use:

.. code-block:: sh

   $ toxicmaster create ~/master-env

This is going to create a ``~/master-env`` directory with a ``toxicmaster.conf``
file in it. This file is used to configure toxicmaster.

Check the configuration instructions for details

.. toctree::
   :maxdepth: 1

   config


Run the server
--------------

When the configuration is done you can run the server with:

.. code-block:: sh

   $ toxicmaster start ~/master-env


For all options for the toxicmaster command execute

.. code-block:: sh

   $ toxicmaster --help


Master server API
==================

Check the api documentation for details

.. toctree::
   :maxdepth: 1

   master_api.rst


CHANGELOG
---------

.. toctree::
   :maxdepth: 1

   CHANGELOG
