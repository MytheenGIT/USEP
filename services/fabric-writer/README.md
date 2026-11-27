# C-04 fabric writer

Code lives in `src/usep/fabric/` (rules), `src/usep/ports/fabric_store.py` (port) and `src/usep/adapters/postgres/`
(PostgreSQL, migrations). Decision record: `docs/adr/ADR-21-fabric-writer-and-postgres-commit-point.md`.
Run with `scripts/fabric.py` (`migrate`, `write`, `relay`, `status`). Deployment (RDS, roles, schedule) is platform-iac work and
is not written yet.
