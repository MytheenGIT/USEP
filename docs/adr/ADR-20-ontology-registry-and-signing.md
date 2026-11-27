# ADR-20: Ontology registry (C-06) and pack signing (C-07)

Status: Proposed. Needs ARB acceptance and a security-architect review of `platform-iac/registry/template.yaml`
(written without AWS access, not deployed, not run through cfn-lint).

## Context
Git holds the ontology definitions and pack CI (`ontology/tools/check_ontology.py`) decides whether a pack may exist.
Nothing turned a reviewed version into something a running service could trust: packs carried `signed: false`, services
read a checkout, and a tenant's ontology version was whatever was on disk. The diagram's panel A needs
PR → review → validate → versioned release → cached config.

## Decision
1. **Git stays the source of definitions.** The registry holds releases, never edits.
2. **A release is immutable and signed.** One release is one core version or one pack version: a bundle (stored zip, sorted
   files, fixed timestamps, so equal content gives equal bytes) and a signed manifest (schema, kind, id, version,
   `requires_core`, level, `reference_only`, sha256 of every file, content digest, bundle sha256). The signed body has no
   timestamps. `src/usep/registry/release.py`.
3. **Publishing is gated.** `scripts/registry.py publish` runs pack CI and the golden-set check first and has no flag to skip
   them. In CI it runs only on an `ontology-v*` tag, in the `ontology-release` GitHub environment (two required reviewers),
   through OIDC into a role that trusts only that environment (`.github/workflows/ontology-ci.yml`).
4. **Signing key.** Production: an AWS KMS asymmetric key (ECC_NIST_P256). The publisher role can sign and read the public
   key; the key administrator cannot sign; nobody else can (`platform-iac/registry/template.yaml`). Development and tests:
   Ed25519 files, never trusted in production.
5. **Trust store** (`config/registry/trusted_keys.yaml`): public keys in Git, changed by reviewed PR. A key can be
   `revoked` or carry `not_after`. Every verification failure returns one message, so the error is not an oracle.
6. **Version numbers are promises.** Republishing identical content is a no-op. Publishing different content under an existing
   version is refused.
7. **Pins.** A tenant's pins are an append-only history (one record per change). A pin can only point at a set of releases
   that verifies, fits one core, and loads cleanly. A reference-only pack can be pinned only where the caller allows
   placeholder content (development stacks). Setting a pin can announce an `ontology.release` event.
8. **Services fail closed.** `RegistryClient.load` / `load_for_tenant` verify signature, trust, revocation, file hashes and
   bundle hash, rebuild the ontology tree in a local cache, and load it with the existing loader. Anything unsigned, altered,
   revoked or unpinned is refused. The digest of a registry-loaded ontology equals the digest of the same files in Git, so
   context packages keep citing the same ontology pin.
9. **Storage.** S3 with versioning, Object Lock (governance, 365 days), TLS-only, no delete or retention-bypass for anyone,
   KMS encryption. Reads are a separate managed policy for services.

## Consequences
- Kept: Git review is still the authority; a release adds proof of who published what and that it was checked.
- Lost: a service can no longer load ontology from a bare checkout once `allow_unsigned` is set to false; development stacks
  keep `allow_unsigned=true` until a key is trusted. With an empty trust store nothing signed can load.
- Key rotation is manual (asymmetric KMS keys do not auto-rotate): create a key, add its trust entry, re-sign, revoke the old.
- Governance-mode Object Lock can be bypassed by an account root user; compliance mode is a stricter choice for the owners.

## Open
- The production KMS key does not exist yet, so `trusted_keys.yaml` has `keys: []`.
- The CI workflow and IaC template have not been executed. Review the first run.
- Whether one signature is enough or releases need two (publisher plus a steward) is not decided.
- Registry reads are not yet the default in every service; `pipeline_handler.py` can use it, other services still read a checkout.
