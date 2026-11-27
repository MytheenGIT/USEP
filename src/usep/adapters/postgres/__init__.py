"""PostgreSQL adapters (ADR-21). Imports the psycopg driver, so nothing outside `adapters/` imports this package."""
from usep.adapters.postgres.migrate import migrate
from usep.adapters.postgres.store import PostgresFabricStore

__all__ = ["PostgresFabricStore", "migrate"]
