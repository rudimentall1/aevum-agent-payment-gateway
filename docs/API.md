# Gateway API (planned contract)

The HTTP interface below is the intended MVP contract. It is not implemented yet; request/response examples are design-level, not live API behavior.

## Create payment
`POST /v1/payments`

Request:
```json
{
  "agent_id": "agent-demo",
  "payer": "0x...",
  "token": "0x456569838f1d43009A91ebA4263147Afd7233483",
  "recipient": "0x...",
  "amount": "1.250000",
  "request_id": "client-generated-unique-id",
  "expires_at": 1790000000,
  "purpose": "invoice settlement"
}
```

Rules:
- `amount` is a decimal string, never a JSON number.
- Reject exponent notation, signs, whitespace, zero, negative values and precision beyond token decimals.
- The gateway derives the integer base-unit amount using decimal arithmetic.
- Request ID is unique and bounded in length.
- Payer and recipient must be valid nonzero EVM addresses.
- Token must be allowlisted.
- Expiry must be in the future and within a configured maximum horizon.

## Payment status
`GET /v1/payments/{request_id}`

Possible states: `RECEIVED`, `AUTHORIZING`, `AUTHORIZED`, `SUBMITTING`, `PENDING`, `CONFIRMED`, `REJECTED`, `UNKNOWN_REQUIRES_RECONCILIATION`.

Never label a timeout as a definitive failure without checking chain state.

## Security
- Authenticate callers.
- Bind idempotency to payer + request ID + immutable payment fields.
- Never accept arbitrary transaction calldata from the caller.
- Never expose Verigate secrets, signatures or internal errors.
- All external-service errors fail closed.
