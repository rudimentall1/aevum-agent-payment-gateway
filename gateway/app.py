from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from web3 import Web3


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
DB_PATH = os.getenv("AEVUMPAY_DB", "data/aevumpay-gateway.db")
HTTP_TIMEOUT = float(os.getenv("AEVUMPAY_HTTP_TIMEOUT", "8"))
MAX_PAYMENT_TTL = 300

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
    def __init__(self, path: str = DB_PATH):
        self.path = path
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
                    detail TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def reserve(self, req: PaymentFields, amount_units: int) -> None:
        now = int(time.time())
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                    (req.request_id.lower(), req.intent_id, req.payer.lower(), req.recipient.lower(),
                     str(amount_units), "AUTHORIZING", now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="request_id already exists; inspect payment status") from exc

    def update(self, request_id: str, status: str, tx_hash: str | None = None, detail: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE payments SET status=?, tx_hash=COALESCE(?, tx_hash), detail=?, updated_at=? WHERE request_id=?",
                (status, tx_hash, detail, int(time.time()), request_id.lower()),
            )

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM payments WHERE request_id=?", (request_id.lower(),)).fetchone()
            return dict(row) if row else None


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


def authorize_and_consume(req: ExecuteRequest, action: dict[str, Any]) -> dict[str, Any]:
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
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Verigate authorization/consume failed closed") from exc


def submit_transaction(
    req: ExecuteRequest, amount_units: int, request_id: str,
    on_broadcast=None,
) -> dict[str, Any]:
    if not Web3.is_address(ROUTER_ADDRESS):
        raise HTTPException(status_code=503, detail="router address is not configured")
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": HTTP_TIMEOUT}))
        if not w3.is_connected():
            raise RuntimeError("Aevum RPC unavailable")
        if w3.eth.chain_id != CHAIN_ID:
            raise RuntimeError(f"wrong chain ID: {w3.eth.chain_id}")
        account = Account.from_key(EXECUTOR_PRIVATE_KEY)
        router = w3.eth.contract(address=Web3.to_checksum_address(ROUTER_ADDRESS), abi=ROUTER_ABI)
        token = w3.eth.contract(address=Web3.to_checksum_address(TOKEN_ADDRESS), abi=ERC20_ABI)
        if router.functions.executor().call().lower() != account.address.lower():
            raise RuntimeError("configured signer is not the router executor")
        if router.functions.paused().call():
            raise RuntimeError("payment router is paused")
        if not router.functions.supportedTokens(Web3.to_checksum_address(TOKEN_ADDRESS)).call():
            raise RuntimeError("tUSD8 is not enabled on the router")
        if token.functions.decimals().call() != TOKEN_DECIMALS:
            raise RuntimeError("configured token decimals do not match on-chain decimals")
        payer = Web3.to_checksum_address(req.payer)
        if token.functions.balanceOf(payer).call() < amount_units:
            raise RuntimeError("payer token balance is insufficient")
        if token.functions.allowance(payer, Web3.to_checksum_address(ROUTER_ADDRESS)).call() < amount_units:
            raise RuntimeError("payer allowance is insufficient")

        data = encode_router_calldata(
            payer, Web3.to_checksum_address(TOKEN_ADDRESS), Web3.to_checksum_address(req.recipient),
            amount_units, request_id, req.deadline, req.payer_signature,
        )
        nonce = w3.eth.get_transaction_count(account.address, "pending")
        tx = {
            "from": account.address,
            "to": Web3.to_checksum_address(ROUTER_ADDRESS),
            "value": 0,
            "data": data,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "gasPrice": w3.eth.gas_price,
        }
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        signed = account.sign_transaction(tx)
        expected_hash = Web3.keccak(signed.raw_transaction).hex()
        try:
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        except Exception as exc:
            # RPC may have accepted the raw transaction before the response was lost.
            # Keep the locally derived hash and require reconciliation; never blind-retry.
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
        return {
            "transaction_hash": tx_hash_hex,
            "block_number": receipt.blockNumber,
            "gas_used": receipt.gasUsed,
            "status": "CONFIRMED",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"transaction preflight/submission unavailable: {type(exc).__name__}",
        ) from exc


app = FastAPI(title="AevumPay Gateway", version="0.1.0")
store = PaymentStore()


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
    try:
        authorization = authorize_and_consume(req, action)
        store.update(request_id, "AUTHORIZED_CONSUMED")
        result = submit_transaction(
            req, amount_units, request_id,
            on_broadcast=lambda tx_hash, status: store.update(request_id, status, tx_hash),
        )
        store.update(request_id, result["status"], result.get("transaction_hash"), result.get("detail"))
        return {
            "request_id": request_id,
            "intent_id": req.intent_id,
            "authorization_id": authorization["payload"]["authorization_id"],
            **result,
        }
    except HTTPException as exc:
        status = "UNKNOWN_REQUIRES_RECONCILIATION" if exc.status_code >= 500 else "REJECTED"
        store.update(request_id, status, detail=str(exc.detail))
        raise


@app.get("/v1/payments/{request_id}", dependencies=[Depends(require_gateway_key)])
def payment_status(request_id: str) -> dict[str, Any]:
    try:
        request_id = normalize_request_id(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = store.get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return record
