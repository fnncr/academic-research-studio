"""Optional project storage; extraction must never depend on database readiness."""
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def project_engine(url: str):
    parsed = make_url(url)
    if parsed.drivername != 'postgresql+psycopg':
        raise ValueError('DATABASE_URL must use postgresql+psycopg')
    return create_engine(parsed, pool_pre_ping=True, pool_size=5, max_overflow=0,
                         pool_timeout=3, hide_parameters=True,
                         connect_args={'connect_timeout': 3,
                                       'options': parsed.query.get('options', '') + ' -c statement_timeout=5000 -c lock_timeout=3000'})
