import base64

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from gateway.app import (
    canonical_agent_payload,
    encode_router_calldata,
    parse_amount,
    payment_typed_data,
    verify_payer_signature,
)


def test_amount_parser_is_exact_and_rejects_float_like_inputs():
    assert parse_amount("1.250000", 6) == 1_250_000
    assert parse_amount("0.000001", 6) == 1
    for value in (1.25, "1e-6", "+1", "-1", " 1", "1.0000001", "0", "NaN"):
        with pytest.raises(ValueError):
            parse_amount(value, 6)


def test_eip712_signature_recovers_exact_payer():
    account = Account.create()
    payer = account.address
    token = "0x456569838f1d43009A91ebA4263147Afd7233483"
    recipient = "0x000000000000000000000000000000000000bEEF"
    router = "0x0000000000000000000000000000000000001234"
    request_id = "0x" + "11" * 32
    typed = payment_typed_data(payer, token, recipient, 1_250_000, request_id, 1_800_000_000, router)
    signature = Account.sign_message(encode_typed_data(full_message=typed), account.key).signature.hex()
    verify_payer_signature(typed, signature, payer)
    with pytest.raises(ValueError):
        verify_payer_signature(typed, signature, recipient)


def test_calldata_binds_exact_payment_fields():
    signature = "0x" + "11" * 65
    data = encode_router_calldata(
        "0x0000000000000000000000000000000000000001",
        "0x0000000000000000000000000000000000000002",
        "0x0000000000000000000000000000000000000003",
        1_250_000,
        "0x" + "22" * 32,
        1_800_000_000,
        signature,
    )
    assert data.startswith("0x")
    assert len(data) > 10 + 7 * 64


def test_agent_payload_is_deterministic_utf8_json():
    action = {"amount_exact": "1.250000", "target": "merchant", "metadata": {"x": 1}}
    one = canonical_agent_payload("identity", action)
    two = canonical_agent_payload("identity", action)
    assert one == two
    assert base64.b64encode(one).decode("ascii")
