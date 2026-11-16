# Verigate Bootstrap Runbook

## Deployment assumption
Verigate's README describes the generic API as a protocol implementation/demo, not a hosted multi-tenant SaaS endpoint. AevumPay must use a deliberately deployed self-hosted instance or another endpoint explicitly confirmed by its operator. A local Docker port is not proof of public reachability.

## Before provisioning
Record securely (outside Git):
- Base URL and TLS/reachability.
- Single-tenant or tenant mode.
- API authentication mechanism.
- Tenant identifier, if applicable.
- Exact SQLite/database path used by the running API process.
- Issuer public key and trusted key fingerprint.
- Identity ID and capability ID after registration.

Do not paste secrets into chat, commit them, or put them in logs.

## API auth modes observed in source
- Single tenant: `VERIGATE_API_KEYS` with `VERIGATE_REQUIRE_AUTH=1`.
- Tenant mode: `VERIGATE_TENANT_KEY_DIR`, `VERIGATE_TENANT_API_KEYS` and `X-Verigate-Tenant`; storage is tenant-isolated.
- In tenant mode even `/v1/public-key` requires tenant authentication.

These names are source-inspected; confirm against the exact deployed version.

## Identity and capability
- IdentityRegistry.register validates Base64 raw Ed25519 public key and requires key_id = SHA-256(raw public key).hexdigest().
- API identity_id is key_id, not agent_id.
- CapabilityRegistry.register checks that linked identity exists and matches agent_id; direct registration path rejects delegated capabilities.
- Provision with the same storage/tenant context as the live API. Never let an API and bootstrap script silently point to different databases.

## Operational gate
Do not start integration until the operator confirms the reachable endpoint, auth/tenant mode, database path and issuer key fingerprint. A connected server session is required to inspect processes/config safely. Never print secret values; inspect variable names and redact values.
