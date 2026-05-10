"""
agent/graph.py — Agente LangGraph para validación de seguros en emergencias.

Flujo del grafo:
  START → llamar_llm → [ejecutar_tool | END]
                ↑______________|

El agente razona con las tools (validar_poliza, obtener_preexistencias, registrar_auditoria)
y produce dos mensajes finales: uno para hospital y otro para gestor.
"""

import json
from typing import Annotated, TypedDict
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import get_llm
from agent.tools import TOOLS


# ─── Estado del grafo ─────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    cedula: str
    evento_id: str
    motivo_ingreso: str
    hospital_nombre: str
    # Resultados finales (los llenamos al final)
    mensaje_hospital: str
    mensaje_gestor: str
    decision_cobertura: str


# ─── System prompt del agente ─────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres ARIA (Agente de Respuesta Inmediata en Admisiones), un sistema de validación 
de seguros médicos que actúa cuando un asegurado ingresa a emergencias hospitalarias.

Tu objetivo es procesar el evento en menos de 30 segundos y generar dos mensajes diferenciados.

PROTOCOLO OBLIGATORIO:
1. Llama a `validar_poliza` con la cédula del paciente
2. Llama a `obtener_preexistencias` con la misma cédula
3. Razona sobre la cobertura considerando: estado de póliza, tipo de emergencia, preexistencias, 
   montos disponibles, exclusiones activas y preexistencias no declaradas
4. Llama a `registrar_auditoria` con tu decisión y razonamiento
5. Devuelve tu respuesta SIEMPRE en el siguiente formato JSON (sin markdown, solo JSON puro):

{
  "decision_cobertura": "APROBADA" | "RECHAZADA" | "REQUIERE_REVISION" | "SIN_POLIZA",
  "nivel_urgencia": "CRITICO" | "ALTO" | "MEDIO" | "BAJO",
  "mensaje_hospital": {
    "para": "Departamento de Admisiones",
    "asunto": "...",
    "estado_poliza": "...",
    "cobertura_activa": true/false,
    "monto_disponible": ...,
    "deducible_aplicable": ...,
    "copago_porcentaje": ...,
    "alertas_clinicas": ["..."],
    "preexistencias_relevantes": ["..."],
    "instrucciones": "...",
    "contacto_gestor": "..."
  },
  "mensaje_gestor": {
    "para": "Gestor de Casos",
    "asunto": "...",
    "resumen_ejecutivo": "...",
    "riesgo_financiero": "ALTO" | "MEDIO" | "BAJO",
    "acciones_requeridas": ["..."],
    "preexistencias_no_declaradas": ["..."],
    "recomendacion": "..."
  },
  "razonamiento_agente": "Explicación breve de la lógica de decisión"
}

CRITERIOS DE DECISIÓN:
- APROBADA: póliza vigente, cobertura de emergencias activa, monto disponible > 0
- RECHAZADA: póliza vencida, suspendida, o sin cobertura para emergencias
- REQUIERE_REVISION: póliza vigente pero con preexistencias no declaradas, límite de cobertura 
  casi agotado (<10% disponible), o exclusiones que podrían aplicar al motivo de ingreso
- SIN_POLIZA: no se encontró póliza para la cédula proporcionada

IMPORTANTE: Sé preciso, conciso y clínico. Los médicos y gestores necesitan información accionable,
no explicaciones largas. Siempre incluye alertas clínicas críticas (alergias, medicación actual)
que el hospital necesita conocer inmediatamente.
"""


# ─── Nodos del grafo ──────────────────────────────────────────────────────────

def llamar_llm(state: AgentState) -> dict:
    """Nodo principal: invoca el LLM con las tools disponibles."""
    llm = get_llm()
    llm_con_tools = llm.bind_tools(TOOLS)

    # Si es el primer mensaje, construimos el prompt inicial
    if len(state["messages"]) == 0 or not any(
        isinstance(m, SystemMessage) for m in state["messages"]
    ):
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        user_msg = HumanMessage(content=(
            f"Evento de ingreso a emergencias:\n"
            f"- Cédula del paciente: {state['cedula']}\n"
            f"- ID del evento: {state['evento_id']}\n"
            f"- Hospital: {state['hospital_nombre']}\n"
            f"- Motivo de ingreso reportado: {state['motivo_ingreso']}\n\n"
            f"Procesa este evento siguiendo el protocolo ARIA."
        ))
        messages = [system_msg, user_msg] + list(state["messages"])
    else:
        messages = list(state["messages"])

    response = llm_con_tools.invoke(messages)

    # Si la respuesta final tiene contenido de texto, extraemos los mensajes
    resultado = {"messages": [response]}

    if response.content and not response.tool_calls:
        # El agente terminó — parseamos la respuesta JSON
        try:
            contenido = response.content.strip()
            # Limpieza por si el LLM agrega ```json
            if "```" in contenido:
                contenido = contenido.split("```")[1]
                if contenido.startswith("json"):
                    contenido = contenido[4:]
            data = json.loads(contenido.strip())
            resultado["decision_cobertura"] = data.get("decision_cobertura", "REQUIERE_REVISION")
            resultado["mensaje_hospital"] = json.dumps(data.get("mensaje_hospital", {}), ensure_ascii=False)
            resultado["mensaje_gestor"] = json.dumps(data.get("mensaje_gestor", {}), ensure_ascii=False)
        except (json.JSONDecodeError, IndexError):
            resultado["decision_cobertura"] = "REQUIERE_REVISION"
            resultado["mensaje_hospital"] = response.content
            resultado["mensaje_gestor"] = response.content

    return resultado


def debe_continuar(state: AgentState) -> str:
    """Router: decide si continuar con tools o terminar."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "ejecutar_tools"
    return END


# ─── Construcción del grafo ───────────────────────────────────────────────────

def build_agent():
    """
    Construye y compila el grafo LangGraph del agente ARIA.
    Retorna un grafo compilado listo para invocar.
    """
    tool_node = ToolNode(TOOLS)

    builder = StateGraph(AgentState)

    # Nodos
    builder.add_node("llamar_llm", llamar_llm)
    builder.add_node("ejecutar_tools", tool_node)

    # Edges
    builder.add_edge(START, "llamar_llm")
    builder.add_conditional_edges(
        "llamar_llm",
        debe_continuar,
        {
            "ejecutar_tools": "ejecutar_tools",
            END: END
        }
    )
    builder.add_edge("ejecutar_tools", "llamar_llm")

    return builder.compile()


# Instancia global del agente (se crea una vez al importar)
agent = build_agent()
