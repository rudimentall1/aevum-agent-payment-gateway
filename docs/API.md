# Gateway API

The first FastAPI gateway slice is implemented in `gateway/app.py`. It exposes a prepare/execute flow so the payer signature and agent identity signature can be produced over the exact same immutable payment envelope.

## Authentication

All payment routes require `X-API-Key: <AEVUMPAY_API_KEY>`. `GET /health` is public.

## Build payer typed data

`POST /v1/payments/typed-data`

Send payer, recipient, decimal-string amount, request ID and deadline. The gateway returns the exact EIP-712 domain and Payment struct. The payer signs this typed data with the wallet that owns the tUSD8 balance.

## Prepare the agent authorization payload

`POST /v1/payments/prepare`

Example request:

```json
{
  "payer": "0xPayerAddress",
  "recipient": "0xMerchantAddress",
  "amount": "1.250000",
  "request_id": "0x1111111111111111111111111111111111111111111111111111111111111111",
  "deadline": 1800000000,
  "payer_signature": "0x...",
  "agent_id": "agent-demo",
  "identity_id": "<sha256-of-agent-ed25519-public-key>",
  "capability_id": "cap-demo-payment",
  "intent_id": "payment-intent-001",
  "timestamp": 1799999900.0,
  "purpose": "invoice settlement"
}
```

The amount is a decimal string. Floats, exponent notation, signs, whitespace, zero, negative values and precision beyond the configured token decimals are rejected. The gateway derives base units and constructs router calldata itself. Caller-supplied calldata is never accepted.

The payer signature must be an EIP-712 signature for the domain and Payment struct returned by `/v1/payments/typed-data`. The prepare response includes:
- `eip712_typed_data` for the payer signature.
- `agent_signing_payload` and `agent_signing_payload_base64` for the Ed25519 identity signature.
- Derived router calldata for inspection.

The agent must sign the exact canonical bytes represented by `agent_signing_payload_base64`. Do not change any field between prepare and execute.

## Execute a payment

`POST /v1/payments/execute`

Send the same request fields plus `agent_signature`. The gateway:
1. Revalidates the payer EIP-712 signature and exact amount.
2. Reconstructs the same ActionIntent and transaction envelope.
3. Calls Verigate `POST /v1/actions/authorize`.
4. Requires ALLOW and a valid Ed25519 execution authorization signed by the pinned issuer key.
5. Checks the authorization identity, capability, agent, intent and action hash.
6. Calls Verigate `POST /v1/execution/consume` and proceeds only on `execute=true`.
7. Checks chain ID, router executor, pause state, token allowlist, token decimals, payer balance and allowance.
8. Signs and broadcasts the exact router transaction, then waits for a receipt.

Verigate consumption is not a transaction broadcast. The gateway is responsible for the EVM transaction and reconciliation.

## Payment status

`GET /v1/payments/{request_id}`

The SQLite store records request ID, immutable payment fields, status and transaction hash. Duplicate request IDs return HTTP 409 and are never blindly re-executed.

Possible states include `AUTHORIZING`, `AUTHORIZED_CONSUMED`, `PENDING`, `CONFIRMED`, `REVERTED`, `REJECTED` and `UNKNOWN_REQUIRES_RECONCILIATION`. A payment is marked `CONFIRMED` only after the receipt succeeds and both the exact ERC-20 `Transfer` and router `PaymentExecuted` events are found. The transaction hash is recorded before waiting for the receipt. If the gateway crashes around Verigate consumption or an RPC timeout, inspect status and chain state before any manual recovery. The one-time Verigate authorization is not automatically retried.

## Configuration

See [Gateway setup](../gateway/README.md). No keys or live endpoints are committed. The issuer Ed25519 public key must be pinned locally; the gateway does not trust a key fetched dynamically from an unauthenticated source.
