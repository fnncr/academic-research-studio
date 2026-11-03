import os

from alembic import context
from app.database import project_engine
from app.models import Base

url = os.environ.get('DATABASE_URL')
if not url:
    raise RuntimeError('Set DATABASE_URL before running migrations')
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = project_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
