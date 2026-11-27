-- Fabric schema (ADR-21). Authoritative commit point: state, history, identity, edges, idempotency, outbox.
-- Every tenant table carries tenant_id and row-level security keyed on current_setting('app.tenant_id').
-- The outbox has no row-level security: the relay is cross-tenant. Give the relay role rights on fabric_outbox only.

CREATE TABLE fabric_entity (
    tenant_id   text        NOT NULL,
    entity_id   uuid        NOT NULL,
    type        text        NOT NULL,
    domain      text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, entity_id)
);

-- One entity per source identity until the resolver adds aliases and merges (ADR-21 decision 6).
CREATE TABLE fabric_source_identity (
    tenant_id     text NOT NULL,
    source_system text NOT NULL,
    source_id     text NOT NULL,
    entity_id     uuid NOT NULL,
    PRIMARY KEY (tenant_id, source_system, source_id),
    FOREIGN KEY (tenant_id, entity_id) REFERENCES fabric_entity (tenant_id, entity_id)
);
CREATE INDEX fabric_source_identity_entity ON fabric_source_identity (tenant_id, entity_id);

CREATE TABLE fabric_entity_state (
    tenant_id     text        NOT NULL,
    entity_id     uuid        NOT NULL,
    type          text        NOT NULL,
    domain        text        NOT NULL,
    attributes    jsonb       NOT NULL,
    labels        jsonb       NOT NULL,
    sensitivity   smallint    NOT NULL,
    source_version text       NOT NULL,
    valid_from    timestamptz NOT NULL,
    evidence_ref  text        NOT NULL,
    snapshot_ref  text        NOT NULL,
    ontology      text        NOT NULL,
    row_version   integer     NOT NULL,
    retracted_at  timestamptz,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, entity_id),
    FOREIGN KEY (tenant_id, entity_id) REFERENCES fabric_entity (tenant_id, entity_id)
);

CREATE TABLE fabric_edge (
    tenant_id      text        NOT NULL,
    edge_id        uuid        NOT NULL,
    edge_key       text        NOT NULL,
    type           text        NOT NULL,
    domain         text        NOT NULL,
    from_ref       jsonb       NOT NULL,
    to_ref         jsonb       NOT NULL,
    from_entity_id uuid,
    to_entity_id   uuid,
    attributes     jsonb       NOT NULL,
    labels         jsonb       NOT NULL,
    evidence_ref   text        NOT NULL,
    snapshot_ref   text        NOT NULL,
    ontology       text        NOT NULL,
    row_version    integer     NOT NULL,
    retracted      boolean     NOT NULL DEFAULT false,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, edge_id),
    UNIQUE (tenant_id, edge_key)
);
CREATE INDEX fabric_edge_pending_to ON fabric_edge (tenant_id) WHERE to_entity_id IS NULL AND NOT retracted;
CREATE INDEX fabric_edge_pending_from ON fabric_edge (tenant_id) WHERE from_entity_id IS NULL AND NOT retracted;

-- Append-only history. State rows are a projection of this table.
CREATE TABLE fabric_assertion (
    tenant_id       text        NOT NULL,
    assertion_id    uuid        NOT NULL,
    subject_kind    text        NOT NULL CHECK (subject_kind IN ('node', 'edge', 'retraction')),
    subject_id      uuid,
    type            text        NOT NULL,
    attributes      jsonb       NOT NULL,
    labels          jsonb       NOT NULL,
    evidence_ref    text        NOT NULL,
    snapshot_ref    text        NOT NULL,
    source_version  text        NOT NULL,
    valid_from      timestamptz,
    ontology        text        NOT NULL,
    idempotency_key text        NOT NULL,
    applied         boolean     NOT NULL,
    reason          text        NOT NULL DEFAULT '',
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, assertion_id)
);
CREATE INDEX fabric_assertion_subject ON fabric_assertion (tenant_id, subject_id, recorded_at);

-- (tenant_id, idempotency_key) claimed first inside the commit; a rollback releases it.
CREATE TABLE fabric_applied (
    tenant_id       text        NOT NULL,
    idempotency_key text        NOT NULL,
    outcome         text        NOT NULL,
    applied_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key)
);

-- Events that could not be committed (malformed, type conflict). Reason code and ids only, never event content.
CREATE TABLE fabric_rejected (
    tenant_id   text        NOT NULL,
    event_id    text        NOT NULL,
    topic       text        NOT NULL,
    code        text        NOT NULL,
    reason      text        NOT NULL,
    rejected_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, event_id)
);

CREATE TABLE fabric_outbox (
    outbox_id    bigserial   PRIMARY KEY,
    tenant_id    text        NOT NULL,
    topic        text        NOT NULL,
    key          text        NOT NULL,
    type         text        NOT NULL,
    payload      jsonb       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    dead_at      timestamptz,
    attempts     integer     NOT NULL DEFAULT 0,
    last_error   text
);
CREATE INDEX fabric_outbox_unpublished ON fabric_outbox (outbox_id) WHERE published_at IS NULL AND dead_at IS NULL;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['fabric_entity', 'fabric_source_identity', 'fabric_entity_state', 'fabric_edge',
                             'fabric_assertion', 'fabric_applied', 'fabric_rejected'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)) '
                       'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', t);
    END LOOP;
END $$;
