"""Alembic environment. Delve runs it in code, handing over an open connection (see `delve.storage`), in a transaction
it began with foreign keys off: a table a batch rebuilds is dropped and made again, and with them on the drop would
cascade into every table that names it."""

from alembic import context

from delve.storage.sqlite.tables import metadata

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
