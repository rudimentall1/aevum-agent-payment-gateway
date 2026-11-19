from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from eth_abi import decode as abi_decode, encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from web3 import Web3

from gateway.postgres_ledger import PostgresPaymentStore


CHAIN_ID = int(os.getenv("AEVUMPAY_CHAIN_ID", "44005"))
TOKEN_ADDRESS = os.getenv("AEVUMPAY_TOKEN", "0x456569838f1d43009A91ebA4263147Afd7233483")
TOKEN_DECIMALS = int(os.getenv("AEVUMPAY_TOKEN_DECIMALS", "6"))
RPC_URL = os.getenv("AEVUMPAY_RPC_URL", "https://rpc-test.qday.info")
ROUTER_ADDRESS = os.getenv("AEVUMPAY_ROUTER_ADDRESS", "")
EXECUTOR_PRIVATE_KEY = os.getenv("AEVUMPAY_EXECUTOR_PRIVATE_KEY", "")
VERIGATE_URL = os.getenv("VERIGATE_URL", "").rstrip("/")
VERIGATE_API_KEY = os.getenv("VERIGATE_API_KEY", "")
VERIGATE_TENANT = os.getenv("VERIGATE_TENANT", "")
VERIGATE_PUBLIC_KEY_PATH = os.getenv("VERIGATE_PUBLIC_KEY_PATH", "")
GATEWAY_API_KEY = os.getenv("AEVUMPAY_API_KEY", "")
TX_ENCRYPTION_KEY = os.getenv("AEVUMPAY_TX_ENCRYPTION_KEY", "")
DB_PATH = os.getenv("AEVUMPAY_DB", "data/aevumpay-gateway.db")
HTTP_TIMEOUT = float(os.getenv("AEVUMPAY_HTTP_TIMEOUT", "8"))
MAX_PAYMENT_TTL = 300

# The default deployment is one Uvicorn worker / one replica. Serialize the
# executor critical section so concurrent requests cannot sign the same
# pending account nonce before either transaction is broadcast.
EXECUTION_LOCK = threading.Lock()

ROUTER_ABI = [
    {"type": "function", "name": "executor", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "supportedTokens", "stateMutability": "view", "inputs": [{"name": "", "type": "address"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "paused", "stateMutability": "view", "inputs": [], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "executePayment", "stateMutability": "nonpayable", "inputs": [
        {"name": "payer", "type": "address"}, {"name": "token", "type": "address"},
        {"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"},
        {"name": "requestId", "type": "bytes32"}, {"name": "deadline", "type": "uint256"},
        {"name": "signature", "type": "bytes"}
    ], "outputs": []},
]
ERC20_ABI = [
    {"type": "function", "name": "decimals", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view", "inputs": [{"name": "", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view", "inputs": [
        {"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}
    ], "outputs": [{"type": "uint256"}]},
]

AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
REQUEST_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class PaymentFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    payer: str = Field(min_length=42, max_length=42)
    recipient: str = Field(min_length=42, max_length=42)
    amount: str = Field(min_length=1, max_length=80)
    request_id: str = Field(min_length=66, max_length=66)
    deadline: int = Field(gt=0, strict=True)
    payer_signature: str = Field(min_length=132, max_length=132)
    agent_id: str = Field(min_length=1, max_length=200)
    identity_id: str = Field(min_length=1, max_length=200)
    capability_id: str = Field(min_length=1, max_length=200)
    intent_id: str = Field(min_length=1, max_length=200)
    timestamp: float = Field(gt=0, strict=True)
    purpose: str = Field(default="agent payment", max_length=256)


class TypedDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    payer: str = Field(min_length=42, max_length=42)
    recipient: str = Field(min_length=42, max_length=42)
    amount: str = Field(min_length=1, max_length=80)
    request_id: str = Field(min_length=66, max_length=66)
    deadline: int = Field(gt=0, strict=True)


class PrepareRequest(PaymentFields):
    pass


class ExecuteRequest(PaymentFields):
    agent_signature: str = Field(min_length=1)


def parse_amount(value: str, decimals: int = TOKEN_DECIMALS) -> int:
    if not isinstance(value, str) or not AMOUNT_RE.fullmatch(value):
        raise ValueError("amount must be a positive plain decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be finite and positive")
    scale = Decimal(10) ** decimals
    scaled = amount * scale
    if scaled != scaled.to_integral_value():
        raise ValueError(f"amount exceeds token precision ({decimals} decimals)")
    return int(scaled)


def validate_addresses(payer: str, recipient: str, token: str, router: str) -> tuple[str, str, str, str]:
    values = []
    for label, value in (("payer", payer), ("recipient", recipient), ("token", token), ("router", router)):
        if not Web3.is_address(value):
            raise ValueError(f"invalid {label} address")
        checksum = Web3.to_checksum_address(value)
        if int(checksum, 16) == 0:
            raise ValueError(f"{label} must not be zero")
        values.append(checksum)
    if values[0] == values[1]:
        raise ValueError("payer and recipient must differ")
    if values[3] == values[2] or values[1] == values[3]:
        raise ValueError("invalid router/token/recipient relationship")
    return tuple(values)  # type: ignore[return-value]


def normalize_request_id(value: str) -> str:
    if not REQUEST_ID_RE.fullmatch(value):
        raise ValueError("request_id must be a 32-byte 0x-prefixed hex value")
    if int(value, 16) == 0:
        raise ValueError("request_id must not be zero")
    return value.lower()


def payment_typed_data(
    payer: str, token: str, recipient: str, amount: int, request_id: str,
    deadline: int, router: str, chain_id: int = CHAIN_ID,
) -> dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Payment": [
                {"name": "payer", "type": "address"},
                {"name": "token", "type": "address"},
                {"name": "recipient", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "requestId", "type": "bytes32"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "Payment",
        "domain": {
            "name": "AevumPayPolicyRouter",
            "version": "1",
            "chainId": chain_id,
            "verifyingContract": router,
        },
        "message": {
            "payer": payer,
            "token": token,
            "recipient": recipient,
            "amount": amount,
            "requestId": request_id,
            "deadline": deadline,
        },
    }


def verify_payer_signature(typed_data: dict[str, Any], signature: str, expected_payer: str) -> None:
    try:
        signable = encode_typed_data(full_message=typed_data)
        recovered = Account.recover_message(signable, signature=signature)
    except Exception as exc:
        raise ValueError("invalid payer EIP-712 signature") from exc
    if recovered.lower() != expected_payer.lower():
        raise ValueError("payer signature does not match payer address")


def encode_router_calldata(
    payer: str, token: str, recipient: str, amount: int,
    request_id: str, deadline: int, signature: str,
) -> str:
    if not signature.startswith("0x") or len(signature[2:]) != 130:
        raise ValueError("payer signature must be a 65-byte 0x-prefixed signature")
    try:
        sig_bytes = bytes.fromhex(signature[2:])
    except ValueError as exc:
        raise ValueError("payer signature is not hex") from exc
    selector = Web3.keccak(text="executePayment(address,address,address,uint256,bytes32,uint256,bytes)")[:4]
    encoded = abi_encode(
        ["address", "address", "address", "uint256", "bytes32", "uint256", "bytes"],
        [payer, token, recipient, amount, bytes.fromhex(request_id[2:]), deadline, sig_bytes],
    )
    return "0x" + (selector + encoded).hex()


def build_action(
    req: PaymentFields, *, token: str, router: str, amount_units: int,
    calldata: str, chain_id: int = CHAIN_ID,
) -> dict[str, Any]:
    # This mirrors ActionIntent.as_dict() in Verigate. Keep timestamp as float:
    # JSON 1700000000.0 is not byte-identical to JSON 1700000000.
    amount_decimal = format(Decimal(req.amount), "f")
    return {
        "intent_id": req.intent_id,
        "agent_id": req.agent_id,
        "action_type": "payment",
        "target": Web3.to_checksum_address(req.recipient),
        "resource": f"payment:{req.request_id.lower()}",
        "amount": amount_decimal,
        "amount_exact": amount_decimal,
        "asset": "tUSD8",
        "network": "aevum-testnet",
        "purpose": req.purpose,
        "declared_context": {
            "payer": Web3.to_checksum_address(req.payer),
            "request_id": req.request_id.lower(),
        },
        "input_provenance": {},
        "parent_intent_id": None,
        "requested_capability": None,
        "constraints": {},
        "metadata": {
            "network_family": "evm",
            "evm_transaction": {
                "chain_id": chain_id,
                "to": router,
                "value_wei": 0,
                "data": calldata,
            },
            "payment": {
                "payer": Web3.to_checksum_address(req.payer),
                "token": token,
                "recipient": Web3.to_checksum_address(req.recipient),
                "amount_base_units": str(amount_units),
                "request_id": req.request_id.lower(),
                "deadline": req.deadline,
            },
        },
        "timestamp": float(req.timestamp),
    }


def canonical_agent_payload(identity_id: str, action: dict[str, Any]) -> bytes:
    payload = {"identity_id": identity_id, "action": action}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_execution_authorization(
    authorization: dict[str, Any], public_key: Ed25519PublicKey, expected_action: dict[str, Any]
) -> None:
    try:
        if authorization.get("algorithm") != "Ed25519":
            raise ValueError("unsupported Verigate signature algorithm")
        payload = authorization["payload"]
        if payload.get("action") != expected_action:
            raise ValueError("Verigate authorized a different action or transaction")
        expected_action_sha256 = hashlib.sha256(json.dumps(
            expected_action, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        if payload.get("action_sha256") != expected_action_sha256:
            raise ValueError("Verigate action fingerprint does not match payment envelope")
        signature = base64.b64decode(authorization["signature"], validate=True)
        public_key.verify(signature, json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8"))
    except (KeyError, TypeError, ValueError, InvalidSignature) as exc:
        raise ValueError("Verigate execution authorization is invalid or mismatched") from exc


class PaymentStore:
    def __init__(self, path: str = DB_PATH, encryption_key: str | bytes | None = None):
        self.path = path
        key = encryption_key if encryption_key is not None else TX_ENCRYPTION_KEY
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key) if key else None
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    request_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL,
                    payer TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    amount_base_units TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tx_hash TEXT,
                    raw_transaction BLOB,
                    authorization_consumed INTEGER NOT NULL DEFAULT 0,
                    detail TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(payments)")}
            if "raw_transaction" not in columns:
                db.execute("ALTER TABLE payments ADD COLUMN raw_transaction BLOB")
            if "authorization_consumed" not in columns:
                db.execute("ALTER TABLE payments ADD COLUMN authorization_consumed INTEGER NOT NULL DEFAULT 0")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def reserve(self, req: PaymentFields, amount_units: int) -> None:
        now = int(time.time())
        try:
            with self._connect() as db:
                db.execute(
                    """INSERT INTO payments
                       (request_id, intent_id, payer, recipient, amount_base_units,
                        status, tx_hash, raw_transaction, detail, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)""",
                    (req.request_id.lower(), req.intent_id, req.payer.lower(), req.recipient.lower(),
                     str(amount_units), "AUTHORIZING", now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="request_id already exists; inspect payment status") from exc

    def update(self, request_id: str, status: str, tx_hash: str | None = None, detail: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE payments SET status=?, tx_hash=COALESCE(?, tx_hash), detail=?,
                   authorization_consumed=CASE WHEN ?='AUTHORIZED_CONSUMED' THEN 1 ELSE authorization_consumed END,
                   updated_at=? WHERE request_id=?""",
                (status, tx_hash, detail, status, int(time.time()), request_id.lower()),
            )

    def set_signed_transaction(
        self, request_id: str, tx_hash: str, raw_transaction: bytes,
        chain_id: int | None = None, executor_address: str | None = None, nonce: int | None = None,
    ) -> None:
        if self.cipher is None:
            raise RuntimeError("AEVUMPAY_TX_ENCRYPTION_KEY is required to persist signed transactions")
        encrypted_transaction = self.cipher.encrypt(raw_transaction)
        with self._connect() as db:
            db.execute(
                """UPDATE payments SET status='SIGNED_AWAITING_CONSUME',
                   tx_hash=?, raw_transaction=?, updated_at=? WHERE request_id=?""",
                (tx_hash, encrypted_transaction, int(time.time()), request_id.lower()),
            )

    def clear_signed_transaction(self, request_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE payments SET raw_transaction=NULL, updated_at=? WHERE request_id=?",
                (int(time.time()), request_id.lower()),
            )

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM payments WHERE request_id=?", (request_id.lower(),)).fetchone()
            return dict(row) if row else None

def create_payment_store():
    """Select the shared PostgreSQL ledger only when explicitly configured.

    SQLite remains the default for existing single-worker deployments.
    """
    database_url = os.getenv("AEVUMPAY_DATABASE_URL", "").strip()
    if database_url:
        if not TX_ENCRYPTION_KEY:
            raise RuntimeError("AEVUMPAY_TX_ENCRYPTION_KEY is required with PostgreSQL")
        return PostgresPaymentStore(database_url, TX_ENCRYPTION_KEY)
    return PaymentStore()


def verify_payment_events(logs: list[Any], payer: str, recipient: str, amount: int, request_id: str) -> bool:
    transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)")
    payment_topic = Web3.keccak(text="PaymentExecuted(address,address,address,uint256,bytes32)")
    payer_bytes = bytes.fromhex(Web3.to_checksum_address(payer)[2:].lower())
    recipient_bytes = bytes.fromhex(Web3.to_checksum_address(recipient)[2:].lower())
    router_bytes = bytes.fromhex(Web3.to_checksum_address(ROUTER_ADDRESS)[2:].lower())
    token_bytes = bytes.fromhex(Web3.to_checksum_address(TOKEN_ADDRESS)[2:].lower())
    request_bytes = bytes.fromhex(request_id[2:])
    transfer_ok = False
    payment_ok = False
    for log in logs:
        topics = [bytes(item) for item in log.get("topics", [])]
        address_bytes = bytes.fromhex(Web3.to_checksum_address(log["address"])[2:].lower())
        if address_bytes == token_bytes and len(topics) == 3 and topics[0] == transfer_topic:
            from_bytes = topics[1][-20:]
            to_bytes = topics[2][-20:]
            value = abi_decode(["uint256"], bytes(log["data"]))[0]
            if from_bytes == payer_bytes and to_bytes == recipient_bytes and value == amount:
                transfer_ok = True
        if address_bytes == router_bytes and len(topics) == 4 and topics[0] == payment_topic:
            event_payer, event_token, event_recipient = topics[1][-20:], topics[2][-20:], topics[3][-20:]
            event_amount, event_request = abi_decode(["uint256", "bytes32"], bytes(log["data"]))
            if event_payer == payer_bytes and event_token == token_bytes and event_recipient == recipient_bytes and event_amount == amount and event_request == request_bytes:
                payment_ok = True
    return transfer_ok and payment_ok

def load_issuer_key() -> Ed25519PublicKey:
    if not VERIGATE_PUBLIC_KEY_PATH:
        raise RuntimeError("VERIGATE_PUBLIC_KEY_PATH is required; pin the issuer public key")
    key = serialization.load_pem_public_key(Path(VERIGATE_PUBLIC_KEY_PATH).read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise RuntimeError("Verigate issuer key is not Ed25519")
    return key


def validate_configuration() -> None:
    missing = [name for name, value in (
        ("AEVUMPAY_ROUTER_ADDRESS", ROUTER_ADDRESS),
        ("AEVUMPAY_EXECUTOR_PRIVATE_KEY", EXECUTOR_PRIVATE_KEY),
        ("VERIGATE_URL", VERIGATE_URL),
        ("VERIGATE_API_KEY", VERIGATE_API_KEY),
        ("VERIGATE_PUBLIC_KEY_PATH", VERIGATE_PUBLIC_KEY_PATH),
        ("AEVUMPAY_API_KEY", GATEWAY_API_KEY),
        ("AEVUMPAY_TX_ENCRYPTION_KEY", TX_ENCRYPTION_KEY),
    ) if not value]
    if missing:
        raise RuntimeError("missing required configuration: " + ", ".join(missing))


def require_gateway_key(x_api_key: str = Header(default="")) -> None:
    if not GATEWAY_API_KEY or not hmac.compare_digest(x_api_key, GATEWAY_API_KEY):
        raise HTTPException(status_code=401, detail="invalid gateway API key")


def prepare_payment(req: PaymentFields) -> tuple[dict[str, Any], dict[str, Any], int, str, str]:
    validate_configuration()
    try:
        payer, recipient, token, router = validate_addresses(
            req.payer, req.recipient, TOKEN_ADDRESS, ROUTER_ADDRESS
        )
        request_id = normalize_request_id(req.request_id)
        amount_units = parse_amount(req.amount, TOKEN_DECIMALS)
        now = int(time.time())
        if req.deadline <= now or req.deadline > now + MAX_PAYMENT_TTL:
            raise ValueError("deadline must be in the next 300 seconds")
        if not req.intent_id or not req.agent_id or not req.identity_id or not req.capability_id:
            raise ValueError("agent, identity, capability and intent IDs are required")
        if not isinstance(req.timestamp, (int, float)) or req.timestamp <= 0:
            raise ValueError("invalid agent intent timestamp")
        typed_data = payment_typed_data(
            payer, token, recipient, amount_units, request_id, req.deadline, router
        )
        verify_payer_signature(typed_data, req.payer_signature, payer)
        calldata = encode_router_calldata(
            payer, token, recipient, amount_units, request_id, req.deadline, req.payer_signature
        )
        action = build_action(
            req, token=token, router=router, amount_units=amount_units,
            calldata=calldata,
        )
        return typed_data, action, amount_units, calldata, request_id
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def reserve_transaction_nonce(w3: Web3, executor_address: str, request_id: str, payment_store=None) -> int:
    """Use a durable shared reservation when the selected store supports it."""
    pending_nonce = w3.eth.get_transaction_count(executor_address, "pending")
    reserve = getattr(payment_store, "reserve_nonce", None)
    if callable(reserve):
        return reserve(CHAIN_ID, executor_address, pending_nonce, request_id)
    return pending_nonce


def preflight_transaction(
    req: ExecuteRequest, amount_units: int, request_id: str, payment_store=None
) -> dict[str, Any]:
    # Validate and sign the exact transaction before consuming one-time Verigate
    # authority. The signed bytes and deterministic hash are persisted before
    # consume, so a process restart does not lose the only broadcastable tx.
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": HTTP_TIMEOUT}))
        if not w3.is_connected() or w3.eth.chain_id != CHAIN_ID:
            raise ValueError("Aevum RPC unavailable or wrong chain")
        account = Account.from_key(EXECUTOR_PRIVATE_KEY)
        router_address = Web3.to_checksum_address(ROUTER_ADDRESS)
        token_address = Web3.to_checksum_address(TOKEN_ADDRESS)
        router = w3.eth.contract(address=router_address, abi=ROUTER_ABI)
        token = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        if router.functions.executor().call().lower() != account.address.lower():
            raise ValueError("configured signer is not the router executor")
        if router.functions.paused().call():
            raise ValueError("payment router is paused")
        if not router.functions.supportedTokens(token_address).call():
            raise ValueError("tUSD8 is not enabled on the router")
        if token.functions.decimals().call() != TOKEN_DECIMALS:
            raise ValueError("configured token decimals do not match on-chain decimals")
        payer = Web3.to_checksum_address(req.payer)
        if token.functions.balanceOf(payer).call() < amount_units:
            raise ValueError("payer token balance is insufficient")
        if token.functions.allowance(payer, router_address).call() < amount_units:
            raise ValueError("payer allowance is insufficient")
        data = encode_router_calldata(
            payer, token_address, Web3.to_checksum_address(req.recipient),
            amount_units, request_id, req.deadline, req.payer_signature,
        )
        nonce = reserve_transaction_nonce(w3, account.address, request_id, payment_store)
        tx = {
            "from": account.address,
            "to": router_address,
            "value": 0,
            "data": data,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "gasPrice": w3.eth.gas_price,
        }
        gas_estimate = w3.eth.estimate_gas(tx)
        tx["gas"] = int(gas_estimate * 1.2)
        if w3.eth.get_balance(account.address) < tx["gas"] * tx["gasPrice"]:
            raise ValueError("executor native gas balance is insufficient")
        signed = account.sign_transaction(tx)
        raw_transaction = bytes(signed.raw_transaction)
        tx_hash = Web3.keccak(raw_transaction).hex()
        return {
            "web3": w3,
            "raw_transaction": raw_transaction,
            "transaction_hash": tx_hash,
            "executor_address": account.address,
            "nonce": nonce,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=f"on-chain preflight/signing failed before Verigate consume: {type(exc).__name__}",
        ) from exc



def authorize_and_consume(req: ExecuteRequest, action: dict[str, Any], preflight=None) -> dict[str, Any]:
    consume_started = False
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(
                f"{VERIGATE_URL}/v1/actions/authorize",
                headers={
                    "Authorization": f"Bearer {VERIGATE_API_KEY}",
                    **({"X-Verigate-Tenant": VERIGATE_TENANT} if VERIGATE_TENANT else {}),
                },
                json={
                    "identity_id": req.identity_id,
                    "capability_id": req.capability_id,
                    "agent_id": req.agent_id,
                    "agent_signature": req.agent_signature,
                    "intent_id": req.intent_id,
                    "timestamp": float(req.timestamp),
                    "action_type": action["action_type"],
                    "target": action["target"],
                    "resource": action["resource"],
                    "amount_exact": action["amount_exact"],
                    "asset": action["asset"],
                    "network": action["network"],
                    "purpose": action["purpose"],
                    "declared_context": action["declared_context"],
                    "requested_capability": action["requested_capability"],
                    "constraints": action["constraints"],
                    "metadata": action["metadata"],
                },
            )
            response.raise_for_status()
            body = response.json()
            receipt = body.get("decision_receipt") or {}
            decision = (receipt.get("payload") or {}).get("decision") or {}
            authorization = body.get("execution_authorization")
            if decision.get("decision") != "ALLOW" or not isinstance(authorization, dict):
                raise HTTPException(status_code=403, detail="Verigate did not issue executable ALLOW authority")
            auth_payload = authorization.get("payload") or {}
            if (
                auth_payload.get("identity_id") != req.identity_id
                or auth_payload.get("capability_id") != req.capability_id
                or auth_payload.get("agent_id") != req.agent_id
                or auth_payload.get("intent_id") != req.intent_id
            ):
                raise HTTPException(status_code=403, detail="Verigate authority identity binding mismatch")
            verify_execution_authorization(authorization, load_issuer_key(), action)
            if preflight is not None:
                preflight()
            # From this point onward the consume request may have reached Verigate,
            # even if the client times out before receiving its response.
            consume_started = True
            consume = client.post(
                f"{VERIGATE_URL}/v1/execution/consume",
                headers={
                    "Authorization": f"Bearer {VERIGATE_API_KEY}",
                    **({"X-Verigate-Tenant": VERIGATE_TENANT} if VERIGATE_TENANT else {}),
                },
                json={"authorization": authorization},
            )
            consume.raise_for_status()
            result = consume.json()
            if result.get("execute") is not True:
                raise HTTPException(status_code=403, detail="Verigate execution authorization was not consumed")
            return authorization
    except HTTPException:
        raise
    except Exception as exc:
        # Before consume starts, no execution authority can have been consumed;
        # the caller may safely discard the persisted signed transaction.
        # Once consume starts, preserve it for reconciliation because the outcome
        # may be ambiguous after a timeout or lost response.
        status_code = 502 if consume_started else 424
        detail = "Verigate consume outcome unknown" if consume_started else "Verigate authorization failed before consume"
        raise HTTPException(status_code=status_code, detail=detail) from exc


def submit_transaction(
    req: ExecuteRequest, amount_units: int, request_id: str,
    prepared: dict[str, Any], on_broadcast=None,
) -> dict[str, Any]:
    # Broadcast the exact bytes that were signed and persisted before Verigate
    # consume. Do not rebuild the transaction or fetch a new nonce/gas price.
    w3 = prepared["web3"]
    raw_transaction = prepared["raw_transaction"]
    expected_hash = prepared["transaction_hash"]
    if on_broadcast:
        on_broadcast(expected_hash, "SUBMITTING")
    try:
        tx_hash = w3.eth.send_raw_transaction(raw_transaction)
    except Exception as exc:
        if on_broadcast:
            on_broadcast(expected_hash, "UNKNOWN_REQUIRES_RECONCILIATION")
        return {
            "transaction_hash": expected_hash,
            "status": "UNKNOWN_REQUIRES_RECONCILIATION",
            "detail": type(exc).__name__,
        }

    tx_hash_hex = tx_hash.hex()
    if on_broadcast:
        on_broadcast(tx_hash_hex, "PENDING")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=max(60, HTTP_TIMEOUT))
    except Exception as exc:
        return {
            "transaction_hash": tx_hash_hex,
            "status": "PENDING",
            "detail": type(exc).__name__,
        }
    if receipt.status != 1:
        return {
            "transaction_hash": tx_hash_hex,
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "status": "REVERTED",
        }
    if not verify_payment_events(receipt.logs, req.payer, req.recipient, amount_units, request_id):
        return {
            "transaction_hash": tx_hash_hex,
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "status": "UNKNOWN_REQUIRES_RECONCILIATION",
            "detail": "expected ERC-20 Transfer and PaymentExecuted logs were not both found",
        }
    return {
        "transaction_hash": tx_hash_hex,
        "block_number": receipt.blockNumber,
        "gas_used": receipt.gasUsed,
        "status": "CONFIRMED",
        "events_verified": True,
    }


app = FastAPI(title="AevumPay Gateway", version="0.1.0")
store = create_payment_store()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/payments/typed-data", dependencies=[Depends(require_gateway_key)])
def typed_data_endpoint(req: TypedDataRequest) -> dict[str, Any]:
    if not ROUTER_ADDRESS:
        raise HTTPException(status_code=503, detail="router address is not configured")
    try:
        payer, recipient, token, router = validate_addresses(
            req.payer, req.recipient, TOKEN_ADDRESS, ROUTER_ADDRESS
        )
        request_id = normalize_request_id(req.request_id)
        amount_units = parse_amount(req.amount, TOKEN_DECIMALS)
        now = int(time.time())
        if req.deadline <= now or req.deadline > now + MAX_PAYMENT_TTL:
            raise ValueError("deadline must be in the next 300 seconds")
        typed = payment_typed_data(
            payer, token, recipient, amount_units, request_id, req.deadline, router
        )
        return {
            "request_id": request_id,
            "amount_base_units": str(amount_units),
            "eip712_typed_data": typed,
        }
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/payments/prepare", dependencies=[Depends(require_gateway_key)])
def prepare(req: PrepareRequest) -> dict[str, Any]:
    typed_data, action, amount_units, calldata, request_id = prepare_payment(req)
    payload = canonical_agent_payload(req.identity_id, action)
    return {
        "request_id": request_id,
        "amount_base_units": str(amount_units),
        "eip712_typed_data": typed_data,
        "agent_signing_payload": {"identity_id": req.identity_id, "action": action},
        "agent_signing_payload_base64": base64.b64encode(payload).decode("ascii"),
        "calldata": calldata,
        "warning": "The agent must sign these exact canonical bytes. Do not alter any action field.",
    }


@app.post("/v1/payments/execute", dependencies=[Depends(require_gateway_key)])
def execute(req: ExecuteRequest) -> dict[str, Any]:
    typed_data, action, amount_units, calldata, request_id = prepare_payment(req)
    store.reserve(req, amount_units)
    store.update(request_id, "AUTHORIZING")
    # Hold the lock from nonce lookup/signing through Verigate consume and
    # broadcast. Locking only preflight would still allow two requests to sign
    # the same pending nonce while the first waits on Verigate.
    with EXECUTION_LOCK:
        prepared = None
        def prepare_and_persist():
            nonlocal prepared
            prepared = preflight_transaction(req, amount_units, request_id, store)
            if callable(getattr(store, "reserve_nonce", None)):
                store.set_signed_transaction(
                    request_id,
                    prepared["transaction_hash"],
                    prepared["raw_transaction"],
                    CHAIN_ID,
                    prepared["executor_address"],
                    prepared["nonce"],
                )
            else:
                store.set_signed_transaction(
                    request_id, prepared["transaction_hash"], prepared["raw_transaction"]
                )
        try:
            authorization = authorize_and_consume(
                req, action, preflight=prepare_and_persist,
            )
            store.update(request_id, "AUTHORIZED_CONSUMED")
            result = submit_transaction(
                req, amount_units, request_id, prepared,
                on_broadcast=lambda tx_hash, status: store.update(request_id, status, tx_hash),
            )
            store.update(request_id, result["status"], result.get("transaction_hash"), result.get("detail"))
            if result["status"] in ("CONFIRMED", "REVERTED"):
                store.clear_signed_transaction(request_id)
            return {
                "request_id": request_id,
                "intent_id": req.intent_id,
                "authorization_id": authorization["payload"]["authorization_id"],
                **result,
            }
        except HTTPException as exc:
            status = "UNKNOWN_REQUIRES_RECONCILIATION" if exc.status_code >= 500 else "REJECTED"
            store.update(request_id, status, detail=str(exc.detail))
            if status == "REJECTED":
                # A deterministic pre-consume failure or explicit Verigate denial
                # cannot authorize broadcasting this signed transaction. Discard it.
                store.clear_signed_transaction(request_id)
            raise
        except Exception as exc:
            store.update(request_id, "UNKNOWN_REQUIRES_RECONCILIATION", detail=type(exc).__name__)
            raise HTTPException(status_code=500, detail="payment execution interrupted; reconcile before retry") from exc


@app.post("/v1/payments/{request_id}/reconcile", dependencies=[Depends(require_gateway_key)])
def reconcile_payment(request_id: str) -> dict[str, Any]:
    try:
        request_id = normalize_request_id(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = store.get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="payment not found")
    if record["status"] in ("CONFIRMED", "REVERTED", "REJECTED") and not record.get("raw_transaction"):
        record.pop("raw_transaction", None)
        return record
    if not record.get("authorization_consumed"):
        raise HTTPException(
            status_code=409,
            detail="Verigate consume is not confirmed in the ledger; manual authorization reconciliation required",
        )
    if not record.get("raw_transaction") or store.cipher is None:
        raise HTTPException(status_code=409, detail="no encrypted signed transaction is available for reconciliation")
    try:
        raw_transaction = store.cipher.decrypt(record["raw_transaction"])
        expected_hash = Web3.keccak(raw_transaction).hex()
        w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": HTTP_TIMEOUT}))
        if not w3.is_connected() or w3.eth.chain_id != CHAIN_ID:
            raise RuntimeError("Aevum RPC unavailable or wrong chain")
        # Re-broadcasting the identical signed bytes is idempotent at the tx-hash
        # level. Nodes may report already-known/nonce-too-low if it was accepted;
        # in either case, receipt lookup below remains authoritative.
        try:
            returned_hash = w3.eth.send_raw_transaction(raw_transaction).hex()
            if returned_hash.lower() != expected_hash.lower():
                raise RuntimeError("RPC returned a transaction hash mismatch")
        except RuntimeError:
            raise
        except Exception:
            pass
        receipt = w3.eth.wait_for_transaction_receipt(
            Web3.to_bytes(hexstr=expected_hash), timeout=max(60, HTTP_TIMEOUT)
        )
        if receipt.status != 1:
            store.update(request_id, "REVERTED", expected_hash, "transaction receipt status is 0")
            store.clear_signed_transaction(request_id)
        elif verify_payment_events(
            receipt.logs, record["payer"], record["recipient"],
            int(record["amount_base_units"]), request_id,
        ):
            store.update(request_id, "CONFIRMED", expected_hash, None)
            store.clear_signed_transaction(request_id)
        else:
            store.update(
                request_id, "UNKNOWN_REQUIRES_RECONCILIATION", expected_hash,
                "receipt succeeded but expected payment events were not both found",
            )
    except Exception as exc:
        store.update(
            request_id, "PENDING", record.get("tx_hash") or None,
            f"reconciliation incomplete: {type(exc).__name__}",
        )
    result = store.get(request_id) or {}
    result.pop("raw_transaction", None)
    return result


@app.get("/v1/payments/{request_id}", dependencies=[Depends(require_gateway_key)])
def payment_status(request_id: str) -> dict[str, Any]:
    try:
        request_id = normalize_request_id(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = store.get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="payment not found")
    record.pop("raw_transaction", None)
    return record
