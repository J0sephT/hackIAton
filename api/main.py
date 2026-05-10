"""
api/main.py — FastAPI: receptor del webhook y endpoints de simulación.
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from rich import print as rprint

from config import WEBHOOK_SECRET
from agent.graph import agent
from notifications.sender import enviar_notificaciones_paralelo


app = FastAPI(
    title="ARIA - Sistema de Alerta Temprana de Emergencias",
    description="Webhook de validación instantánea de seguros médicos",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Cache de idempotencia (en prod iría en Redis) ─────────────────────────────
eventos_procesados: set[str] = set()
# ─── Resultados para el frontend (en prod iría en Redis/DB) ───────────────────
resultados_cache: dict[str, dict] = {}


# ─── Modelos Pydantic ─────────────────────────────────────────────────────────

class ERAdmissionEvent(BaseModel):
    """Payload que envía el sistema del hospital cuando admite a un paciente."""
    evento_id: Optional[str] = None          # si no viene, lo generamos
    cedula: str                               # cédula del paciente
    nombre_paciente: Optional[str] = None
    hospital_id: str
    hospital_nombre: str
    motivo_ingreso: str                       # descripción clínica del motivo
    timestamp: Optional[str] = None
    # Datos opcionales que el HIS puede incluir
    medico_atencion: Optional[str] = None
    triaje_nivel: Optional[int] = None        # 1=crítico, 2=urgente, 3=moderado


# ─── Verificación HMAC del webhook ───────────────────────────────────────────

def verificar_firma_webhook(payload_raw: bytes, signature: Optional[str]) -> bool:
    """
    Verifica que el webhook viene de una fuente legítima mediante HMAC-SHA256.
    En demo puedes desactivarla con VERIFY_SIGNATURE=false en .env
    """
    if not signature:
        return True  # En hackathon, permisivo si no viene firma
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        payload_raw,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─── Lógica principal de procesamiento ───────────────────────────────────────

async def procesar_evento(evento: ERAdmissionEvent):
    """
    Pipeline completo: agente LangGraph → notificaciones paralelas → log.
    Corre en background para que el webhook retorne 202 inmediatamente.
    """
    evento_id = evento.evento_id
    rprint(f"\n[bold blue]━━━ Procesando evento {evento_id} ━━━[/bold blue]")
    rprint(f"  Paciente cédula: {evento.cedula}")
    rprint(f"  Hospital: {evento.hospital_nombre}")
    rprint(f"  Motivo: {evento.motivo_ingreso}")

    inicio = datetime.now()

    try:
        # ── 1. Invocar agente LangGraph ──────────────────────────────────────
        rprint("[yellow]  → Activando agente ARIA...[/yellow]")

        estado_inicial = {
            "messages": [],
            "cedula": evento.cedula,
            "evento_id": evento_id,
            "motivo_ingreso": evento.motivo_ingreso,
            "hospital_nombre": evento.hospital_nombre,
            "mensaje_hospital": "",
            "mensaje_gestor": "",
            "decision_cobertura": ""
        }

        resultado_agente = await agent.ainvoke(estado_inicial)

        decision = resultado_agente.get("decision_cobertura", "REQUIERE_REVISION")
        msg_hospital = resultado_agente.get("mensaje_hospital", "")
        msg_gestor = resultado_agente.get("mensaje_gestor", "")

        rprint(f"[green]  ✓ Agente completó. Decisión: {decision}[/green]")

        # ── 2. Fan-out de notificaciones paralelas ───────────────────────────
        resultado_notif = await enviar_notificaciones_paralelo(
            evento_id=evento_id,
            cedula=evento.cedula,
            decision=decision,
            mensaje_hospital_raw=msg_hospital,
            mensaje_gestor_raw=msg_gestor
        )

        # ── 3. Guardar resultado en cache (para el frontend) ─────────────────
        duracion_ms = int((datetime.now() - inicio).total_seconds() * 1000)

        resultado_final = {
            "evento_id": evento_id,
            "estado": "completado",
            "decision": decision,
            "duracion_ms": duracion_ms,
            "mensaje_hospital": _parse_json_safe(msg_hospital),
            "mensaje_gestor": _parse_json_safe(msg_gestor),
            "notificaciones": resultado_notif,
            "timestamp_fin": datetime.now().isoformat()
        }
        resultados_cache[evento_id] = resultado_final

        rprint(f"[bold green]━━━ Evento {evento_id} completado en {duracion_ms}ms ━━━[/bold green]\n")

    except Exception as e:
        rprint(f"[bold red]✗ Error procesando evento {evento_id}: {e}[/bold red]")
        resultados_cache[evento_id] = {
            "evento_id": evento_id,
            "estado": "error",
            "error": str(e),
            "timestamp_fin": datetime.now().isoformat()
        }


def _parse_json_safe(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/webhook/er-admission", status_code=202)
async def recibir_evento_emergencia(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature: Optional[str] = Header(None)
):
    """
    Endpoint principal del webhook.
    Retorna 202 Accepted inmediatamente y procesa en background.
    """
    payload_raw = await request.body()

    # Verificar firma HMAC
    if not verificar_firma_webhook(payload_raw, x_hub_signature):
        raise HTTPException(status_code=401, detail="Firma de webhook inválida")

    # Parsear payload
    try:
        data = json.loads(payload_raw)
        evento = ERAdmissionEvent(**data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Payload inválido: {e}")

    # Generar evento_id si no viene
    if not evento.evento_id:
        evento.evento_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"

    # Idempotencia: no procesar dos veces el mismo evento
    if evento.evento_id in eventos_procesados:
        return JSONResponse(
            status_code=200,
            content={"mensaje": "Evento ya procesado", "evento_id": evento.evento_id}
        )
    eventos_procesados.add(evento.evento_id)

    # Guardar estado inicial en cache
    resultados_cache[evento.evento_id] = {
        "evento_id": evento.evento_id,
        "estado": "procesando",
        "timestamp_inicio": datetime.now().isoformat()
    }

    # Procesar en background
    background_tasks.add_task(procesar_evento, evento)

    return JSONResponse(
        status_code=202,
        content={
            "aceptado": True,
            "evento_id": evento.evento_id,
            "mensaje": "Evento recibido. ARIA está procesando.",
            "consultar_resultado": f"/resultado/{evento.evento_id}"
        }
    )


@app.get("/resultado/{evento_id}")
async def obtener_resultado(evento_id: str):
    """Polling endpoint: el frontend consulta aquí hasta que el estado sea 'completado'."""
    if evento_id not in resultados_cache:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return resultados_cache[evento_id]


@app.post("/simular")
async def simular_ingreso(
    background_tasks: BackgroundTasks,
    cedula: str = "1001234567",
    motivo: str = "Dolor torácico agudo con disnea",
    hospital: str = "Hospital General del Norte"
):
    """
    Endpoint de simulación para el demo — dispara un evento sin necesitar el HIS real.
    Cambia la cédula para probar distintos escenarios:
      1001234567 = póliza Gold vigente con preexistencias declaradas (APROBADA)
      1002345678 = póliza Silver, límite casi agotado (REQUIERE_REVISION)
      1003456789 = póliza vencida + preexistencias no declaradas (RECHAZADA)
      1004567890 = póliza Platinum suspendida por mora (RECHAZADA)
      1005678901 = póliza Gold + preexistencia no declarada (REQUIERE_REVISION)
      1006789012 = póliza Silver vigente + Lupus declarado (APROBADA con alertas)
    """
    evento = ERAdmissionEvent(
        evento_id=f"SIM-{uuid.uuid4().hex[:8].upper()}",
        cedula=cedula,
        hospital_id="HOS-001",
        hospital_nombre=hospital,
        motivo_ingreso=motivo,
        timestamp=datetime.now().isoformat()
    )

    eventos_procesados.add(evento.evento_id)
    resultados_cache[evento.evento_id] = {
        "evento_id": evento.evento_id,
        "estado": "procesando",
        "timestamp_inicio": datetime.now().isoformat()
    }

    background_tasks.add_task(procesar_evento, evento)

    return {
        "evento_id": evento.evento_id,
        "mensaje": "Simulación iniciada",
        "consultar_en": f"/resultado/{evento.evento_id}"
    }


@app.get("/health")
async def health_check():
    return {"status": "ok", "servicio": "ARIA v1.0", "timestamp": datetime.now().isoformat()}


@app.get("/audit-log")
async def ver_audit_log():
    """Ver los últimos registros de auditoría."""
    import pathlib
    log_path = pathlib.Path(__file__).parent.parent / "audit_log.jsonl"
    if not log_path.exists():
        return {"registros": []}
    with open(log_path, "r") as f:
        registros = [json.loads(line) for line in f.readlines()[-20:]]
    return {"registros": registros}
