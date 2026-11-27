-- Rollback for 0001. Drops tenant definitions, configurations and their audit trail (data loss: export first).
BEGIN;
DROP TABLE IF EXISTS definition_audit;
DROP FUNCTION IF EXISTS definition_audit_immutable();
DROP TABLE IF EXISTS source_configuration;
DROP TABLE IF EXISTS tenant_label_definition;
COMMIT;
