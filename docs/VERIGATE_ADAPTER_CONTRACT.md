# Verigate Adapter Contract

This document records source-inspected integration requirements. No live endpoint or tenant has been configured; these are not integration-test results.

## Required flow
1. Construct a complete ActionIntent with stable intent ID, agent identity, action type, recipient target, exact amount, asset/network, purpose and EVM transaction metadata.
2. Call `POST /v1/actions/authorize`.
3. Validate the returned decision and execution authorization; verify its Ed25519 signature against the pinned issuer public key and expected payload.
4. Call `POST /v1/execution/consume` with the exact authorization envelope.
5. Proceed only if the response explicitly returns `execute=true`.
6. Submit the exact transaction described in the authorization. No field may be substituted after authorization.

Legacy `POST /v1/authorize` is not suitable for executable payment authority: source inspection found it returns a signed decision receipt but no `execution_authorization`.

## Intent fields
- `amount_exact`: decimal string. Never use float for amount.
- `target`: payment recipient, so capability can constrain recipient.
- `metadata.network_family`: `evm`.
- `metadata.evm_transaction.chain_id`: 44005.
- `metadata.evm_transaction.to`: deployed AevumPay router.
- `metadata.evm_transaction.value_wei`: `0`.
- `metadata.evm_transaction.data`: exact router calldata.
- Calldata binds token, recipient, integer base-unit amount, request ID and expiry.

## Important distinction
The consume endpoint consumes one-time authorization. It does not broadcast an EVM transaction. The gateway remains responsible for transaction submission and chain reconciliation.

## Network resolution
Verigate source inspection found a generic EVM fallback for unknown network names when EVM metadata includes a valid chain ID and transaction envelope. Aevum-specific compatibility still requires integration testing.

## Signing/canonicalization
- Identity is Ed25519 and signs canonical ActionIntent.
- Identity ID is the SHA-256 hex digest of the raw public key; it is not agent_id.
- Canonical payload is UTF-8 JSON with sorted keys, compact separators and ensure_ascii=false, over `{"identity_id": identity_id, "action": action.as_dict()}`.
- Python serializes integer-valued float timestamps differently from JavaScript JSON.stringify. Do not assume TS canonicalization is byte-identical. Prefer pinned Verigate Python signing helpers or checked-in cross-language fixtures.
- API schema does not expose input_provenance; API-created ActionIntent uses the default empty object.
- amount_exact normalization preserves decimal scale through Decimal formatting; do not trim trailing zeroes without matching server semantics.

## Provisioning
No public REST endpoint for identity/capability registration was found in inspected source. Provision through the actual self-hosted instance's IdentityRegistry and CapabilityRegistry using the exact tenant database used by the running API. Never guess the DB path or write to the default database in tenant mode.

## Fail-closed requirements
Reject if service unavailable, response malformed, decision not ALLOW, signature invalid, issuer key mismatch, transaction envelope mismatch, consume fails or execute is not true.
