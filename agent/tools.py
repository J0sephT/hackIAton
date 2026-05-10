"""
agent/tools.py — Herramientas que el agente LangGraph puede invocar.
Cada función es una "tool": el LLM decide cuándo y cómo llamarlas.
"""

import json
from datetime import date
from langchain_core.tools import tool
from config import POLIZAS_PATH, HISTORIAL_PATH


def _load_json(path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── Tool 1: Validar póliza ───────────────────────────────────────────────────

@tool
def validar_poliza(cedula: str) -> dict:
    """
    Busca y valida la póliza de seguro de un paciente por su número de cédula.
    Devuelve el estado de la póliza, cobertura para emergencias, monto disponible,
    exclusiones activas y datos del gestor de casos.
    Úsala siempre como primer paso cuando recibes un evento de ingreso a emergencias.
    """
    polizas = _load_json(POLIZAS_PATH)
    poliza = next((p for p in polizas if p["cedula"] == cedula), None)

    if not poliza:
        return {
            "encontrada": False,
            "mensaje": f"No se encontró póliza activa para cédula {cedula}",
            "cedula": cedula
        }

    # Calcular monto disponible
    monto_disponible = poliza["monto_maximo_anual"] - poliza["monto_usado"]

    # Verificar vigencia por fecha
    hoy = date.today()
    fecha_fin = date.fromisoformat(poliza["fecha_fin"])
    dias_para_vencer = (fecha_fin - hoy).days
    vencida_por_fecha = fecha_fin < hoy

    return {
        "encontrada": True,
        "poliza_id": poliza["poliza_id"],
        "cedula": cedula,
        "nombre_paciente": poliza["nombre"],
        "tipo_plan": poliza["tipo_plan"],
        "estado": poliza["estado"],
        "vigente": poliza["estado"] == "vigente" and not vencida_por_fecha,
        "fecha_fin": poliza["fecha_fin"],
        "dias_para_vencer": dias_para_vencer if not vencida_por_fecha else 0,
        "cubre_emergencias": poliza["cobertura_emergencias"],
        "cubre_hospitalizacion": poliza["cobertura_hospitalizacion"],
        "cubre_cirugia": poliza["cobertura_cirugia"],
        "cubre_medicamentos": poliza["cobertura_medicamentos"],
        "monto_maximo_anual": poliza["monto_maximo_anual"],
        "monto_usado": poliza["monto_usado"],
        "monto_disponible": monto_disponible,
        "porcentaje_usado": round((poliza["monto_usado"] / poliza["monto_maximo_anual"]) * 100, 1),
        "deducible": poliza["deducible"],
        "copago_porcentaje": poliza["copago_porcentaje"],
        "exclusiones": poliza["exclusiones"],
        "contacto_gestor": poliza["contacto_gestor"],
        "telefono_gestor": poliza["telefono_gestor"],
        "alertas": poliza.get("alerta"),
        "meses_mora": poliza.get("meses_mora", 0)
    }


# ─── Tool 2: Obtener historial y preexistencias ───────────────────────────────

@tool
def obtener_preexistencias(cedula: str) -> dict:
    """
    Recupera el historial médico y las preexistencias del paciente por su cédula.
    Incluye condiciones crónicas, medicación actual, alergias, hospitalizaciones previas
    y si las preexistencias fueron declaradas al contratar la póliza.
    Úsala después de validar_poliza para tener el contexto clínico completo.
    """
    historiales = _load_json(HISTORIAL_PATH)
    historial = next((h for h in historiales if h["cedula"] == cedula), None)

    if not historial:
        return {
            "encontrado": False,
            "mensaje": f"No se encontró historial médico para cédula {cedula}",
            "cedula": cedula
        }

    preexistencias_no_declaradas = [
        p for p in historial["preexistencias"]
        if not p.get("declarada_en_poliza", True)
    ]

    preexistencias_declaradas = [
        p for p in historial["preexistencias"]
        if p.get("declarada_en_poliza", True)
    ]

    return {
        "encontrado": True,
        "cedula": cedula,
        "nombre": historial["nombre"],
        "edad": historial["edad"],
        "tipo_sangre": historial["tipo_sangre"],
        "alergias": historial["alergias"],
        "tiene_preexistencias": len(historial["preexistencias"]) > 0,
        "preexistencias_declaradas": preexistencias_declaradas,
        "preexistencias_no_declaradas": preexistencias_no_declaradas,
        "alerta_preexistencias_ocultas": len(preexistencias_no_declaradas) > 0,
        "total_preexistencias": len(historial["preexistencias"]),
        "hospitalizaciones_previas": historial["hospitalizaciones_previas"],
        "medico_cabecera": historial["medico_cabecera"],
        "notas_criticas": historial["notas_criticas"]
    }


# ─── Tool 3: Registrar evento procesado ──────────────────────────────────────

@tool
def registrar_auditoria(
    cedula: str,
    evento_id: str,
    decision_cobertura: str,
    razonamiento: str
) -> dict:
    """
    Registra en el log de auditoría la decisión tomada sobre la cobertura.
    Llámala al final del proceso, después de haber validado póliza y preexistencias.
    decision_cobertura debe ser: 'APROBADA', 'RECHAZADA', 'REQUIERE_REVISION', 'SIN_POLIZA'
    """
    from datetime import datetime
    import pathlib

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "evento_id": evento_id,
        "cedula": cedula,
        "decision": decision_cobertura,
        "razonamiento": razonamiento
    }

    log_path = pathlib.Path(__file__).parent.parent / "audit_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    return {
        "registrado": True,
        "timestamp": log_entry["timestamp"],
        "decision": decision_cobertura
    }


# ─── Lista de herramientas disponibles para el agente ─────────────────────────
TOOLS = [validar_poliza, obtener_preexistencias, registrar_auditoria]
