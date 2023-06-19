Master API
==========

The uses the `tpp <https://docs.poraodojuca.dev/toxiccore/tpp.html>`_.

The master api is quite extensive.

poll
----

The action ``poll`` fetches changes from a repository

The following body params are mandatory:

-  ``repo_id`` - Id of the repository being polled.
- ``url`` - A url to fetch the changes from.
- ``vcs_type`` - What kind of vcs are we using. Currently only git is supported.

The following are optional:

- ``known_branches`` - Branches that already have revisions registered
  in the master. Braches that are NOT know will return only the most
  recent changes.

- ``branches_conf`` - Config for the branches in the format {<branchname>: <config>}
- ``conffile`` - The name for the config file. Defaults to ``toxicbuild.yml``.
- ``external`` - Information about a pull from external repo. Params for external:
  - ``url``, ``name``, ``branch``, ``into``
