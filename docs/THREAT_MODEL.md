# Threat Model (initial)

## Assets
- Payer ERC-20 balances and allowances.
- Payment intent integrity (payer, token, recipient, amount, request ID, deadline).
- Gateway executor credential and Verigate issuer trust anchor.
- Availability and correctness of payment status.

## Trust assumptions
- Payer private key remains secure and signs only intended EIP-712 envelopes.
- Owner securely controls token allowlist and executor rotation.
- Gateway executor acts only after successful Verigate authorization verification and one-time consume.
- Allowlisted token behaves as a conventional ERC-20. Fee-on-transfer/rebasing tokens are not supported by the initial design.
- QDay EVM execution and chain ID are correct.

## Threats and controls
- Recipient/amount substitution: payer EIP-712 signature binds exact fields.
- Cross-chain replay: EIP-712 domain includes chain ID and verifying contract; constructor pins expected chain.
- Request replay: used request ID mapping per payer.
- Unauthorized relayer: executor role.
- Malicious token reentrancy: nonReentrant guard; token allowlist is owner-controlled.
- Signature malleability: low-s enforcement and v validation.
- Expired authorization: deadline check.
- Gateway/Verigate outage: fail closed; no direct fallback execution.
- RPC timeout: reconcile request ID and chain state before retry.
- Owner compromise: can add malicious token or executor. Use a dedicated deployer/multisig or timelock for production; MVP uses testnet owner.
- Allowance exposure: payer should approve only the router and preferably a bounded amount. Router cannot force allowance to be revoked.

## Known limitations
- This is an MVP contract, not an audit.
- Verigate's Ed25519 signature is not verified on-chain. Gateway verifies and consumes it off-chain; contract separately verifies payer EIP-712 consent.
- Owner and executor are privileged roles.
- Fee-on-transfer tokens, rebasing tokens, ERC-777 hooks and arbitrary token behavior are outside supported scope.
