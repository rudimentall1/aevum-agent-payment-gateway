import base64
import hashlib
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from cryptography.fernet import Fernet
from eth_abi import encode as abi_encode
from web3 import Web3

import gateway.app as gateway_app
from gateway.app import (
    canonical_agent_payload,
    encode_router_calldata,
    parse_amount,
    payment_typed_data,
    PaymentStore,
    PrepareRequest,
    verify_payer_signature,
    verify_payment_events,
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



def test_payment_receipt_requires_matching_transfer_and_router_events(monkeypatch):
    token = "0x0000000000000000000000000000000000000002"
    router = "0x0000000000000000000000000000000000000003"
    payer = "0x0000000000000000000000000000000000000001"
    recipient = "0x0000000000000000000000000000000000000004"
    request_id = "0x" + "22" * 32
    amount = 1_250_000
    monkeypatch.setattr(gateway_app, "TOKEN_ADDRESS", token)
    monkeypatch.setattr(gateway_app, "ROUTER_ADDRESS", router)

    def topic_address(address):
        return bytes(12) + bytes.fromhex(address[2:])

    logs = [
        {
            "address": token,
            "topics": [
                Web3.keccak(text="Transfer(address,address,uint256)"),
                topic_address(payer),
                topic_address(recipient),
            ],
            "data": abi_encode(["uint256"], [amount]),
        },
        {
            "address": router,
            "topics": [
                Web3.keccak(text="PaymentExecuted(address,address,address,uint256,bytes32)"),
                topic_address(payer),
                topic_address(token),
                topic_address(recipient),
            ],
            "data": abi_encode(["uint256", "bytes32"], [amount, bytes.fromhex(request_id[2:])]),
        },
    ]
    assert verify_payment_events(logs, payer, recipient, amount, request_id)
    assert not verify_payment_events(logs, payer, recipient, amount + 1, request_id)



def test_signed_transaction_is_durable_and_hidden_from_public_record(tmp_path):
    encryption_key = Fernet.generate_key()
    store = PaymentStore(str(tmp_path / "payments.sqlite"), encryption_key=encryption_key)
    req = PrepareRequest(
        payer="0x0000000000000000000000000000000000000001",
        recipient="0x0000000000000000000000000000000000000002",
        amount="1.25",
        request_id="0x" + "33" * 32,
        deadline=1_800_000_000,
        payer_signature="0x" + "11" * 65,
        agent_id="agent",
        identity_id="identity",
        capability_id="capability",
        intent_id="intent",
        timestamp=1_700_000_000.0,
    )
    store.reserve(req, 1_250_000)
    raw_tx = bytes.fromhex("02" + "ab" * 40)
    tx_hash = "0x" + "44" * 32
    store.set_signed_transaction(req.request_id, tx_hash, raw_tx)

    record = store.get(req.request_id)
    assert record["status"] == "SIGNED_AWAITING_CONSUME"
    assert record["tx_hash"] == tx_hash
    assert record["raw_transaction"] != raw_tx
    assert Fernet(encryption_key).decrypt(record["raw_transaction"]) == raw_tx

    store.update(req.request_id, "AUTHORIZED_CONSUMED")
    assert store.get(req.request_id)["authorization_consumed"] == 1
    assert Fernet(encryption_key).decrypt(store.get(req.request_id)["raw_transaction"]) == raw_tx
    store.clear_signed_transaction(req.request_id)
    assert store.get(req.request_id)["raw_transaction"] is None



def _signed_verigate_authorization(action):
    private_key = Ed25519PrivateKey.generate()
    payload = {
        "authorization_id": "auth-test",
        "identity_id": "identity",
        "capability_id": "capability",
        "agent_id": "agent",
        "intent_id": "intent",
        "action": action,
        "action_sha256": hashlib.sha256(
            json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }
    signature = private_key.sign(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    authorization = {
        "algorithm": "Ed25519",
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return authorization, private_key.public_key(), private_key


def test_execution_authorization_accepts_valid_pinned_ed25519_signature():
    action = {"action_type": "payment", "amount_exact": "1.250000", "metadata": {"chain_id": 44005}}
    authorization, public_key, _ = _signed_verigate_authorization(action)

    gateway_app.verify_execution_authorization(authorization, public_key, action)


def test_execution_authorization_rejects_action_substitution():
    action = {"action_type": "payment", "amount_exact": "1.250000"}
    authorization, public_key, _ = _signed_verigate_authorization(action)
    substituted_action = {"action_type": "payment", "amount_exact": "9.990000"}

    with pytest.raises(ValueError, match="invalid or mismatched"):
        gateway_app.verify_execution_authorization(authorization, public_key, substituted_action)


def test_execution_authorization_rejects_tampered_signature():
    action = {"action_type": "payment", "amount_exact": "1.250000"}
    authorization, public_key, _ = _signed_verigate_authorization(action)
    signature = bytearray(base64.b64decode(authorization["signature"]))
    signature[0] ^= 0x01
    authorization["signature"] = base64.b64encode(signature).decode("ascii")

    with pytest.raises(ValueError, match="invalid or mismatched"):
        gateway_app.verify_execution_authorization(authorization, public_key, action)


def test_execution_authorization_rejects_wrong_algorithm():
    action = {"action_type": "payment", "amount_exact": "1.250000"}
    authorization, public_key, _ = _signed_verigate_authorization(action)
    authorization["algorithm"] = "RSA"

    with pytest.raises(ValueError, match="invalid or mismatched"):
        gateway_app.verify_execution_authorization(authorization, public_key, action)


def test_execution_authorization_rejects_action_fingerprint_mismatch():
    action = {"action_type": "payment", "amount_exact": "1.250000"}
    authorization, public_key, private_key = _signed_verigate_authorization(action)
    authorization["payload"]["action_sha256"] = "00" * 32
    payload = authorization["payload"]
    authorization["signature"] = base64.b64encode(private_key.sign(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )).decode("ascii")
    with pytest.raises(ValueError, match="invalid or mismatched"):
        gateway_app.verify_execution_authorization(authorization, public_key, action)
