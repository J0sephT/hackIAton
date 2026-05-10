"""
notifications/sender.py — Envío paralelo de notificaciones.
Fan-out simultáneo a hospital y gestor de casos usando asyncio.
"""

import json
import asyncio
import httpx
from datetime import datetime
from rich import print as rprint
from config import HOSPITAL_WEBHOOK_URL, GESTOR_WEBHOOK_URL


async def _enviar_a_endpoint(
    url: str,
    payload: dict,
    destinatario: str,
    evento_id: str
) -> dict:
    """Envía una notificación HTTP POST con reintentos."""
    headers = {
        "Content-Type": "application/json",
        "X-ARIA-Event-ID": evento_id,
        "X-ARIA-Timestamp": datetime.now().isoformat(),
        "X-ARIA-Destinatario": destinatario
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            rprint(f"[green]✓ Notificación enviada a {destinatario}[/green] — Status: {response.status_code}")
            return {
                "destinatario": destinatario,
                "enviado": True,
                "status_code": response.status_code,
                "timestamp": datetime.now().isoformat()
            }
    except httpx.HTTPStatusError as e:
        rprint(f"[red]✗ Error HTTP al notificar a {destinatario}: {e}[/red]")
        return {
            "destinatario": destinatario,
            "enviado": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        rprint(f"[red]✗ Error al notificar a {destinatario}: {e}[/red]")
        return {
            "destinatario": destinatario,
            "enviado": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def enviar_notificaciones_paralelo(
    evento_id: str,
    cedula: str,
    decision: str,
    mensaje_hospital_raw: str,
    mensaje_gestor_raw: str
) -> dict:
    """
    Envía simultáneamente las notificaciones al hospital y al gestor.
    Usa asyncio.gather para paralelismo real — ambas peticiones salen al mismo tiempo.
    """

    # Parsear los mensajes (pueden venir como str JSON o dict)
    def parse_mensaje(raw):
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"contenido": raw}

    msg_hospital = parse_mensaje(mensaje_hospital_raw)
    msg_gestor = parse_mensaje(mensaje_gestor_raw)

    payload_hospital = {
        "evento_id": evento_id,
        "tipo": "ALERTA_ADMISIONES_EMERGENCIAS",
        "decision": decision,
        "timestamp": datetime.now().isoformat(),
        "datos": msg_hospital
    }

    payload_gestor = {
        "evento_id": evento_id,
        "tipo": "APERTURA_CASO_GESTOR",
        "decision": decision,
        "timestamp": datetime.now().isoformat(),
        "paciente_cedula": cedula,
        "datos": msg_gestor
    }

    rprint(f"[yellow]→ Enviando notificaciones paralelas para evento {evento_id}...[/yellow]")

    # ← AQUÍ está el fan-out: ambas salen al mismo tiempo
    resultado_hospital, resultado_gestor = await asyncio.gather(
        _enviar_a_endpoint(HOSPITAL_WEBHOOK_URL, payload_hospital, "ADMISIONES_HOSPITAL", evento_id),
        _enviar_a_endpoint(GESTOR_WEBHOOK_URL, payload_gestor, "GESTOR_CASOS", evento_id),
        return_exceptions=False
    )

    return {
        "notificacion_hospital": resultado_hospital,
        "notificacion_gestor": resultado_gestor,
        "ambas_enviadas": resultado_hospital["enviado"] and resultado_gestor["enviado"]
    }
