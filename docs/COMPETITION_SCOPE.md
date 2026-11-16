# Competition Scope

## Challenge
QDay Aevum Builder Challenge #1.

## Schedule (organizer announcement / challenge materials)
- Build period: 2026-11-16 to 2026-12-11.
- Submission closes: 2026-12-11 08:00 UTC (16:00 HKT).
- Judging: 2026-12-12 to 2026-12-14.
- Demo Day: 2026-12-15 06:00 UTC.
- Prize pool: 1,500 USDT (1st: 800; 2nd: 500; 3rd: 200).

## Submission expectations
- Public GitHub repository.
- Working Aevum integration.
- Runnable MVP/prototype or Docker image.
- Documentation and a clear explanation of the product.
- Demo video and pitch.
- Smart contracts deployed to Aevum testnet.
- Test tokens only.

## Explicit scope boundary
Organizer Nicole Qiu confirmed that an existing Verigate authorization engine may be used through an API, but it is outside the new hackathon implementation scope. AevumPay's new contest work is the gateway, Aevum-specific policy router, integration, tests, demo and documentation. Do not present Verigate's pre-existing code as newly built for this challenge.

## Product claim
AevumPay demonstrates controlled agent payments: authorization is decided off-chain, while the on-chain router independently enforces the exact payment envelope. Do not claim the chain itself validates Verigate's Ed25519 signature.

## Positioning constraints
- Do not claim QDay mainnet builder funding or partnership is guaranteed.
- Do not claim ERC-4337/session-key support until an end-to-end Aevum testnet UserOperation is confirmed.
- Do not describe the prototype as production-ready or audited.
