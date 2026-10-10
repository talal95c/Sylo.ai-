import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import ValidationError

from api.orchestrator import orchestrator

router = APIRouter()


@router.post("/payments")
async def create_payment(
    payload: dict[str, Any] = Body(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return await orchestrator.submit_order(
            payload,
            idempotency_key=idempotency_key,
        )
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/payments/{payment_id}/approve")
async def approve_payment(payment_id: str, payload: dict[str, Any] = Body(...)):
    try:
        approver = payload.get("by") or payload.get("approver")
        return await orchestrator.approve_payment(payment_id, str(approver))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/payments/{payment_id}")
async def get_payment(payment_id: str):
    try:
        return orchestrator.payment_response(payment_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/payments/{payment_id}/proof")
async def get_payment_proof(payment_id: str):
    try:
        return orchestrator.payment_proof(payment_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/payees/{payee_id}/verify")
async def verify_payee(
    payee_id: str,
    payload: dict[str, Any] = Body(default={}),
):
    try:
        return orchestrator.verify_payee(
            payee_id,
            payload.get("paymentId"),
            payload,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/cases")
async def list_cases():
    return {"cases": orchestrator.list_cases()}


@router.post("/cases")
async def create_case(payload: dict[str, Any] = Body(...)):
    try:
        return await orchestrator.create_case(payload)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/cases/{case_id}/actions")
async def act_on_case(case_id: str, payload: dict[str, Any] = Body(...)):
    try:
        return await orchestrator.case_action(case_id, payload)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sim/scene/{scene}")
async def start_scene(scene: str):
    try:
        return await orchestrator.play_scene(scene)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/sim/attack/{attack}")
async def simulate_attack(attack: str):
    try:
        return await orchestrator.simulate_attack(attack)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/sim/reset")
async def reset_simulation():
    return orchestrator.reset()


@router.get("/metrics")
async def metrics():
    metrics_path = Path(__file__).resolve().parents[1] / "ml" / "metrics.json"
    if not metrics_path.exists():
        return {"status": "pending"}
    return json.loads(metrics_path.read_text(encoding="utf-8"))
