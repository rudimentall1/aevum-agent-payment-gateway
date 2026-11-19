import base64
import hashlib
import json
import httpx
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



def test_definitive_verigate_rejection_discards_persisted_signed_transaction(monkeypatch, tmp_path):
    encryption_key = Fernet.generate_key()
    payment_store = PaymentStore(str(tmp_path / "rejected.sqlite"), encryption_key=encryption_key)
    monkeypatch.setattr(gateway_app, "store", payment_store)

    req = gateway_app.ExecuteRequest(
        payer="0x0000000000000000000000000000000000000001",
        recipient="0x0000000000000000000000000000000000000002",
        amount="1.25",
        request_id="0x" + "55" * 32,
        deadline=1_800_000_000,
        payer_signature="0x" + "11" * 65,
        agent_id="agent",
        identity_id="identity",
        capability_id="capability",
        intent_id="intent",
        timestamp=1_700_000_000.0,
        agent_signature="agent-signature",
    )
    action = _verigate_test_action()
    monkeypatch.setattr(
        gateway_app, "prepare_payment",
        lambda _req: ({}, action, 1_250_000, "0x1234", req.request_id),
    )
    monkeypatch.setattr(
        gateway_app, "preflight_transaction",
        lambda *_args: {
            "web3": object(),
            "raw_transaction": b"signed-transaction",
            "transaction_hash": "0x" + "66" * 32,
        },
    )

    def reject_after_preflight(_req, _action, preflight=None):
        preflight()
        raise gateway_app.HTTPException(status_code=403, detail="Verigate denied")

    monkeypatch.setattr(gateway_app, "authorize_and_consume", reject_after_preflight)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.execute(req)

    assert exc.value.status_code == 403
    record = payment_store.get(req.request_id)
    assert record["status"] == "REJECTED"
    assert record["authorization_consumed"] == 0
    assert record["raw_transaction"] is None



def test_ambiguous_verigate_failure_preserves_signed_transaction_for_reconciliation(monkeypatch, tmp_path):
    encryption_key = Fernet.generate_key()
    payment_store = PaymentStore(str(tmp_path / "ambiguous.sqlite"), encryption_key=encryption_key)
    monkeypatch.setattr(gateway_app, "store", payment_store)

    req = gateway_app.ExecuteRequest(
        payer="0x0000000000000000000000000000000000000001",
        recipient="0x0000000000000000000000000000000000000002",
        amount="1.25",
        request_id="0x" + "77" * 32,
        deadline=1_800_000_000,
        payer_signature="0x" + "11" * 65,
        agent_id="agent",
        identity_id="identity",
        capability_id="capability",
        intent_id="intent",
        timestamp=1_700_000_000.0,
        agent_signature="agent-signature",
    )
    monkeypatch.setattr(
        gateway_app, "prepare_payment",
        lambda _req: ({}, {"action_type": "payment"}, 1_250_000, "0x1234", req.request_id),
    )
    monkeypatch.setattr(
        gateway_app, "preflight_transaction",
        lambda *_args: {
            "web3": object(),
            "raw_transaction": b"signed-transaction",
            "transaction_hash": "0x" + "88" * 32,
        },
    )

    def timeout_after_consume_request(_req, _action, preflight=None):
        preflight()
        raise gateway_app.HTTPException(status_code=502, detail="consume outcome unknown")

    monkeypatch.setattr(gateway_app, "authorize_and_consume", timeout_after_consume_request)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.execute(req)

    assert exc.value.status_code == 502
    record = payment_store.get(req.request_id)
    assert record["status"] == "UNKNOWN_REQUIRES_RECONCILIATION"
    assert record["authorization_consumed"] == 0
    assert Fernet(encryption_key).decrypt(record["raw_transaction"]) == b"signed-transaction"


class _FakeVerigateResponse:
    def __init__(self, body=None, error=None):
        self.body = body
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class _FakeVerigateClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected Verigate HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _verigate_test_request():
    return gateway_app.ExecuteRequest(
        payer="0x0000000000000000000000000000000000000001",
        recipient="0x0000000000000000000000000000000000000002",
        amount="1.25",
        request_id="0x" + "99" * 32,
        deadline=1_800_000_000,
        payer_signature="0x" + "11" * 65,
        agent_id="agent",
        identity_id="identity",
        capability_id="capability",
        intent_id="intent",
        timestamp=1_700_000_000.0,
        agent_signature="agent-signature",
    )


def _verigate_test_action():
    return {
        "action_type": "payment",
        "target": "0x0000000000000000000000000000000000000002",
        "resource": "tUSD8",
        "amount_exact": "1.250000",
        "asset": "tUSD8",
        "network": "aevum-testnet",
        "purpose": "agent payment",
        "declared_context": {},
        "requested_capability": None,
        "constraints": {},
        "metadata": {"network_family": "evm"},
    }


def _verigate_allow_body(action):
    authorization, public_key, _ = _signed_verigate_authorization(action)
    return {
        "decision_receipt": {"payload": {"decision": {"decision": "ALLOW"}}},
        "execution_authorization": authorization,
    }, public_key


def test_authorize_and_consume_accepts_valid_allow_and_consumed_authority(monkeypatch):
    req = _verigate_test_request()
    action = _verigate_test_action()
    body, public_key = _verigate_allow_body(action)
    client = _FakeVerigateClient([
        _FakeVerigateResponse(body),
        _FakeVerigateResponse({"execute": True}),
    ])
    monkeypatch.setattr(gateway_app.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(gateway_app, "load_issuer_key", lambda: public_key)
    preflight_calls = []

    result = gateway_app.authorize_and_consume(
        req, action, preflight=lambda: preflight_calls.append(True)
    )

    assert result == body["execution_authorization"]
    assert preflight_calls == [True]
    assert len(client.posts) == 2
    assert client.posts[1][0].endswith("/v1/execution/consume")



@pytest.mark.parametrize("authorize_failure", [
    httpx.TimeoutException("authorize timed out"),
    RuntimeError("authorize returned HTTP 503"),
    ValueError("malformed authorize JSON"),
])
def test_authorize_stage_failures_are_definitive_before_consume(monkeypatch, authorize_failure):
    req = _verigate_test_request()
    action = _verigate_test_action()
    if isinstance(authorize_failure, ValueError):
        response = _FakeVerigateResponse(authorize_failure)
    elif isinstance(authorize_failure, RuntimeError):
        response = _FakeVerigateResponse(error=authorize_failure)
    else:
        response = authorize_failure
    client = _FakeVerigateClient([response])
    monkeypatch.setattr(gateway_app.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.authorize_and_consume(req, action)

    assert exc.value.status_code == 424
    assert len(client.posts) == 1


def test_authorize_and_consume_rejects_deny_without_consuming(monkeypatch):
    req = _verigate_test_request()
    client = _FakeVerigateClient([
        _FakeVerigateResponse({
            "decision_receipt": {"payload": {"decision": {"decision": "DENY"}}},
        }),
    ])
    monkeypatch.setattr(gateway_app.httpx, "Client", lambda **_kwargs: client)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.authorize_and_consume(req, _verigate_test_action())

    assert exc.value.status_code == 403
    assert len(client.posts) == 1


@pytest.mark.parametrize("field", ["identity_id", "capability_id", "agent_id", "intent_id"])
def test_authorize_and_consume_rejects_mismatched_authority_binding(monkeypatch, field):
    req = _verigate_test_request()
    action = _verigate_test_action()
    authorization, public_key, private_key = _signed_verigate_authorization(action)
    authorization["payload"][field] = "attacker-controlled-value"
    payload_bytes = json.dumps(
        authorization["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    authorization["signature"] = base64.b64encode(private_key.sign(payload_bytes)).decode("ascii")
    body = {
        "decision_receipt": {"payload": {"decision": {"decision": "ALLOW"}}},
        "execution_authorization": authorization,
    }
    # The binding check must reject before signature verification or consume.
    client = _FakeVerigateClient([_FakeVerigateResponse(body)])
    monkeypatch.setattr(gateway_app.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(gateway_app, "load_issuer_key", lambda: public_key)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.authorize_and_consume(req, action)

    assert exc.value.status_code == 403
    assert len(client.posts) == 1


def test_authorize_and_consume_rejects_invalid_issuer_signature_before_consume(monkeypatch):
    req = _verigate_test_request()
    action = _verigate_test_action()
    body, public_key = _verigate_allow_body(action)
    body["execution_authorization"]["signature"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    client = _FakeVerigateClient([_FakeVerigateResponse(body)])
    monkeypatch.setattr(gateway_app.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(gateway_app, "load_issuer_key", lambda: public_key)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.authorize_and_consume(req, action)

    assert exc.value.status_code == 424
    assert len(client.posts) == 1


def test_authorize_and_consume_rejects_consume_false(monkeypatch):
    req = _verigate_test_request()
    action = _verigate_test_action()
    body, public_key = _verigate_allow_body(action)
    client = _FakeVerigateClient([
        _FakeVerigateResponse(body),
        _FakeVerigateResponse({"execute": False}),
    ])
    monkeypatch.setattr(gateway_app.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(gateway_app, "load_issuer_key", lambda: public_key)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.authorize_and_consume(req, action)

    assert exc.value.status_code == 403
    assert len(client.posts) == 2


@pytest.mark.parametrize("failure", [
    RuntimeError("upstream HTTP failure"),
    httpx.TimeoutException("upstream timeout"),
])
def test_authorize_and_consume_fails_closed_on_consume_transport_error(monkeypatch, failure):
    req = _verigate_test_request()
    action = _verigate_test_action()
    body, public_key = _verigate_allow_body(action)
    client = _FakeVerigateClient([
        _FakeVerigateResponse(body),
        failure,
    ])
    monkeypatch.setattr(gateway_app.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(gateway_app, "load_issuer_key", lambda: public_key)

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.authorize_and_consume(req, action)

    assert exc.value.status_code == 502
    assert len(client.posts) == 2


def test_payment_execution_serializes_nonce_preflight_across_requests(monkeypatch, tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    encryption_key = Fernet.generate_key()
    payment_store = PaymentStore(str(tmp_path / "serialized.sqlite"), encryption_key=encryption_key)
    monkeypatch.setattr(gateway_app, "store", payment_store)

    first_preflight_started = threading.Event()
    release_first_preflight = threading.Event()
    second_preflight_started = threading.Event()
    call_lock = threading.Lock()
    preflight_calls = 0

    def fake_prepare_payment(req):
        return ({}, {"action_type": "payment"}, 100, "0x1234", req.request_id)

    def fake_preflight(req, amount_units, request_id, payment_store=None):
        nonlocal preflight_calls
        with call_lock:
            preflight_calls += 1
            call_number = preflight_calls
        if call_number == 1:
            first_preflight_started.set()
            assert release_first_preflight.wait(timeout=3)
        else:
            second_preflight_started.set()
        return {
            "web3": object(),
            "raw_transaction": b"signed-" + request_id.encode(),
            "transaction_hash": "0x" + ("ab" if call_number == 1 else "cd") * 32,
        }

    authorization = {"payload": {"authorization_id": "auth-test"}}

    def fake_authorize(_req, _action, preflight=None):
        preflight()
        return authorization

    def fake_submit(_req, _amount, _request_id, _prepared, on_broadcast=None):
        return {"status": "CONFIRMED", "transaction_hash": "0x" + "ef" * 32}

    monkeypatch.setattr(gateway_app, "prepare_payment", fake_prepare_payment)
    monkeypatch.setattr(gateway_app, "preflight_transaction", fake_preflight)
    monkeypatch.setattr(gateway_app, "authorize_and_consume", fake_authorize)
    monkeypatch.setattr(gateway_app, "submit_transaction", fake_submit)

    first = _verigate_test_request()
    second = first.model_copy(update={"request_id": "0x" + "aa" * 32})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(gateway_app.execute, first)
        assert first_preflight_started.wait(timeout=2)
        second_future = pool.submit(gateway_app.execute, second)
        try:
            assert not second_preflight_started.wait(timeout=0.2), (
                "a second payment entered nonce preflight while the first was unresolved"
            )
        finally:
            release_first_preflight.set()
        first_future.result(timeout=3)
        second_future.result(timeout=3)

    assert preflight_calls == 2


def _crash_recovery_store(tmp_path, request_id, encryption_key):
    store = PaymentStore(str(tmp_path / "crash-recovery.sqlite"), encryption_key=encryption_key)
    req = _verigate_test_request().model_copy(update={"request_id": request_id})
    store.reserve(req, 1_250_000)
    raw_tx = bytes.fromhex("02" + "ab" * 40)
    tx_hash = Web3.keccak(raw_tx).hex()
    store.set_signed_transaction(request_id, tx_hash, raw_tx)
    return store, raw_tx, tx_hash


def test_reconcile_refuses_automatic_rebroadcast_after_consume_before_ledger_marker(monkeypatch, tmp_path):
    encryption_key = Fernet.generate_key()
    request_id = "0x" + "b1" * 32
    payment_store, raw_tx, _tx_hash = _crash_recovery_store(tmp_path, request_id, encryption_key)
    # Simulate process death after Verigate may have consumed authority but
    # before SQLite durably records authorization_consumed=1.
    monkeypatch.setattr(gateway_app, "store", payment_store)
    rpc_attempts = []
    monkeypatch.setattr(gateway_app, "Web3", lambda *_args, **_kwargs: rpc_attempts.append(True))

    with pytest.raises(gateway_app.HTTPException) as exc:
        gateway_app.reconcile_payment(request_id)

    assert exc.value.status_code == 409
    assert "manual authorization reconciliation" in exc.value.detail
    assert rpc_attempts == []
    record = PaymentStore(payment_store.path, encryption_key=encryption_key).get(request_id)
    assert Fernet(encryption_key).decrypt(record["raw_transaction"]) == raw_tx
    assert record["authorization_consumed"] == 0


def test_reconcile_after_restart_rebroadcasts_identical_bytes_and_confirms(monkeypatch, tmp_path):
    encryption_key = Fernet.generate_key()
    request_id = "0x" + "b2" * 32
    original_store, raw_tx, tx_hash = _crash_recovery_store(tmp_path, request_id, encryption_key)
    original_store.update(request_id, "AUTHORIZED_CONSUMED")

    # A new PaymentStore instance represents a fresh process after a crash.
    restarted_store = PaymentStore(original_store.path, encryption_key=encryption_key)
    monkeypatch.setattr(gateway_app, "store", restarted_store)

    class FakeEth:
        chain_id = gateway_app.CHAIN_ID

        def __init__(self):
            self.broadcasts = []

        def send_raw_transaction(self, transaction):
            self.broadcasts.append(bytes(transaction))
            class TxHash:
                def hex(self):
                    return tx_hash

            return TxHash()

        def wait_for_transaction_receipt(self, _tx_hash, timeout):
            assert timeout >= 60
            return type("Receipt", (), {"status": 1, "logs": []})()

    fake_eth = FakeEth()

    class FakeWeb3:
        def __init__(self, *_args, **_kwargs):
            self.eth = fake_eth

        def is_connected(self):
            return True

        @staticmethod
        def HTTPProvider(*_args, **_kwargs):
            return object()

        @staticmethod
        def keccak(value):
            return Web3.keccak(value)

        @staticmethod
        def to_bytes(hexstr):
            return bytes.fromhex(hexstr[2:])

    monkeypatch.setattr(gateway_app, "Web3", FakeWeb3)
    monkeypatch.setattr(gateway_app, "verify_payment_events", lambda *_args: True)

    result = gateway_app.reconcile_payment(request_id)

    assert fake_eth.broadcasts == [raw_tx]
    assert result["status"] == "CONFIRMED"
    assert result["tx_hash"] == tx_hash
    record = restarted_store.get(request_id)
    assert record["authorization_consumed"] == 1
    assert record["raw_transaction"] is None


def test_postgres_nonce_reservation_uses_shared_ledger_allocation():
    class FakeEth:
        def get_transaction_count(self, address, block):
            assert address == "0x000000000000000000000000000000000000aE01"
            assert block == "pending"
            return 5

    class FakeWeb3:
        eth = FakeEth()

    class FakeStore:
        def __init__(self):
            self.calls = []

        def reserve_nonce(self, chain_id, executor_address, pending_nonce, request_id):
            self.calls.append((chain_id, executor_address, pending_nonce, request_id))
            return 9

    store = FakeStore()
    nonce = gateway_app.reserve_transaction_nonce(
        FakeWeb3(),
        "0x000000000000000000000000000000000000aE01",
        "0x" + "ab" * 32,
        store,
    )

    assert nonce == 9
    assert store.calls == [(
        gateway_app.CHAIN_ID,
        "0x000000000000000000000000000000000000aE01",
        5,
        "0x" + "ab" * 32,
    )]


def test_sqlite_nonce_path_keeps_pending_rpc_nonce():
    class FakeEth:
        def get_transaction_count(self, _address, block):
            assert block == "pending"
            return 12

    class FakeWeb3:
        eth = FakeEth()

    store = PaymentStore(":memory:", encryption_key=Fernet.generate_key())
    nonce = gateway_app.reserve_transaction_nonce(
        FakeWeb3(),
        "0x000000000000000000000000000000000000aE01",
        "0x" + "cd" * 32,
        store,
    )

    assert nonce == 12


def test_create_payment_store_selects_postgres_only_when_explicitly_configured(monkeypatch, tmp_path):
    sentinel = object()
    calls = []

    def fake_postgres_store(database_url, encryption_key):
        calls.append((database_url, encryption_key))
        return sentinel

    monkeypatch.setenv("AEVUMPAY_DATABASE_URL", "postgresql://gateway/db")
    monkeypatch.setattr(gateway_app, "TX_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setattr(gateway_app, "PostgresPaymentStore", fake_postgres_store)

    assert gateway_app.create_payment_store() is sentinel
    assert calls == [("postgresql://gateway/db", "test-fernet-key")]

    monkeypatch.delenv("AEVUMPAY_DATABASE_URL")
    monkeypatch.setattr(gateway_app, "DB_PATH", str(tmp_path / "default.sqlite"))
    assert isinstance(gateway_app.create_payment_store(), PaymentStore)
