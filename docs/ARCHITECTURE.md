# Architecture

## Components
- **Agent/client:** requests a bounded payment.
- **Gateway:** validates input, constructs a canonical intent, calls Verigate, verifies the execution authorization, consumes it once, and submits the matching router call.
- **Verigate:** external off-chain identity/capability and action authorization service. It is not copied into this repository.
- **AevumPay PolicyRouter:** deterministic on-chain enforcement for payment constraints.
- **tUSD8:** ERC-20 test token on QDay Aevum.

## Trust boundaries
Verigate's Ed25519 authorization is verified/consumed by the gateway. The EVM router does not verify that signature. The router independently checks the transaction arguments against its on-chain policy and replay state. This separation must be explicit in documentation and demo narration.

## Payment model
Non-custodial pull payment:
1. Payer holds tUSD8.
2. Payer approves the router.
3. Router receives a payment call containing token, recipient, exact base-unit amount, request ID and expiry.
4. Router validates all constraints and calls `transferFrom(payer, recipient, amount)`.
5. Router marks the request consumed and emits a payment event.

No funds are held in a project-controlled escrow. The router should update replay state before the external token call; a failed transfer reverts the entire transaction and state update atomically.

## Required on-chain invariants
- Only supported/explicitly configured ERC-20 tokens may be used.
- Recipient must be nonzero and must match the authorized request.
- Amount must be nonzero and exact in token base units.
- Request ID/nonce can be executed at most once per payer (or globally, if the final authorization model requires global uniqueness).
- Deadline must not have expired.
- Chain ID must be the intended chain (domain separation / explicit check).
- Reentrancy must not permit duplicate execution.
- ERC-20 calls must handle false-return and no-return tokens safely; use a vetted SafeERC20 implementation or equivalent.
- No arbitrary call target, arbitrary calldata, native-value transfer or allowance-setting function.

## EOA-first decision
Aevum's public materials conflict on whether ERC-4337/session-key infrastructure is live. EOA is the reliable MVP route. AA is an optional extension only after official EntryPoint/factory/bundler/session-key details are confirmed and an end-to-end UserOperation is mined. A session key, if later used, must be scoped to this router and payment selector; the router remains responsible for recipient and amount checks.

## Transaction sequence and failure behavior
- Gateway must fail closed if Verigate is unavailable, authorization is missing/invalid, signature verification fails, or consume does not return `execute=true`.
- A consumed authorization followed by an RPC failure is not automatically safe to retry. Gateway must reconcile chain state by request ID before retrying; otherwise it risks duplicate submission or ambiguous payment status.
- Router reverts on every policy violation. It emits a definitive event only after successful token transfer.
- RPC timeout handling distinguishes unknown/pending from confirmed failure; never report a payment as failed solely because the client timed out.

## Data representation
- API amounts are decimal strings.
- Contract amounts are uint256 base units.
- tUSD8 has 6 decimals according to the Starter Kit; convert using decimal arithmetic, never binary floating point.
- Canonical intent serialization must be byte-compatible with the pinned Verigate signer. Python/JavaScript timestamp serialization differs for integer-valued floats; use fixtures and do not improvise canonical JSON.
