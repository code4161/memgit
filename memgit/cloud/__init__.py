"""memgit cloud — E2E-encrypted team sync (app.memgit.dev).

Nothing here runs until a store is logged in and linked. The rest of memgit
imports only `auto`, lazily, to start a background sync after a commit, at
session start, and from a read when the last sync is old. pynacl and httpx are
ordinary dependencies of the package.
"""
