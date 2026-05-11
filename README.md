# ARIA — Sistema de Alerta Temprana de Ingresos a Emergencias

Agente LLM construido con LangGraph que automatiza la validación de seguros médicos
en tiempo real cuando un paciente asegurado ingresa a urgencias hospitalarias.

## Problema

El proceso actual de verificación de cobertura en emergencias es manual: el personal
de admisiones llama a la aseguradora, espera atención, obtiene respuesta verbal y
notifica al médico. Este proceso toma entre 20 y 45 minutos, en el momento más
crítico para el paciente.

## Solución

ARIA recibe un webhook del sistema hospitalario en el momento del registro, activa
un agente que valida la póliza y el historial de preexistencias, razona sobre la
cobertura, y notifica simultáneamente al departamento de admisiones del hospital
y al gestor de casos de la aseguradora. El ciclo completo toma menos de 20 segundos.

## Arquitectura

```
[Hospital ER] --webhook--> [FastAPI] --background--> [Agente LangGraph]
                                                            |
                                              [validar_poliza] [obtener_preexistencias]
                                              [registrar_auditoria]
                                                            |
                                              asyncio.gather (fan-out paralelo)
                                             /                            \
                                   [Admisiones Hospital]         [Gestor de Casos]
```

El agente usa tool calling: el LLM decide cuándo y cómo invocar cada herramienta,
razona sobre los resultados y produce dos mensajes diferenciados con distinto
nivel de detalle para cada destinatario.

## Stack

- FastAPI — servidor y receptor del webhook
- LangGraph — orquestación del agente y ciclo de razonamiento
- LangChain — abstracción del LLM (intercambiable: OpenAI, Anthropic, Groq)
- httpx — notificaciones HTTP paralelas con asyncio

## Instalación

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # editar con tu API key
```

## Configuración

Editar `.env`. Solo se necesita un proveedor activo:

```env
# OpenAI
OPENAI_API_KEY=sk-...
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini

# Anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# LLM_PROVIDER=anthropic
# LLM_MODEL=claude-3-haiku-20240307

# Groq (gratis)
# GROQ_API_KEY=gsk_...
# LLM_PROVIDER=groq
# LLM_MODEL=llama-3.1-8b-instant
```

Para cambiar de proveedor basta editar esas dos líneas. El agente no requiere
ningún otro cambio.

## Ejecución

```bash
python run.py
# Servidor en http://localhost:8000
# UI del demo en http://localhost:8000
# Documentación de API en http://localhost:8000/docs
```

## Casos de prueba

| Cedula       | Escenario                              | Decision esperada    |
|--------------|----------------------------------------|----------------------|
| 1001234567   | Poliza Gold vigente, preex. declaradas | APROBADA             |
| 1002345678   | Silver vigente, limite casi agotado    | REQUIERE_REVISION    |
| 1003456789   | Poliza vencida + preex. no declaradas  | RECHAZADA            |
| 1004567890   | Platinum suspendida por mora           | RECHAZADA            |
| 1005678901   | Gold vigente + epilepsia no declarada  | REQUIERE_REVISION    |
| 1006789012   | Silver vigente + Lupus declarado       | APROBADA con alertas |

## Simular un ingreso

```bash
curl -X POST "http://localhost:8000/simular?cedula=1001234567&motivo=Dolor+toracico"
# Retorna: {"evento_id": "SIM-XXXXXXXX", ...}

curl "http://localhost:8000/resultado/SIM-XXXXXXXX"
```

O desde la UI en `http://localhost:8000`.

## Endpoints

| Metodo | Ruta                   | Descripcion                              |
|--------|------------------------|------------------------------------------|
| POST   | /webhook/er-admission  | Receptor del webhook (produccion)        |
| POST   | /simular               | Dispara evento de prueba (demo)          |
| GET    | /resultado/{evento_id} | Consulta resultado por polling           |
| GET    | /audit-log             | Ultimas 20 entradas del log de auditoria |
| GET    | /health                | Healthcheck                              |
| GET    | /docs                  | Documentacion interactiva (Swagger)      |

## Seguridad implementada

- Verificacion de firma HMAC-SHA256 en el webhook
- Idempotencia por evento_id (el mismo evento no se procesa dos veces)
- Audit log inmutable en JSONL con timestamp, decision y razonamiento del agente

## Despliegue en Railway

```bash
# 1. Subir proyecto a GitHub
# 2. railway.app -> New Project -> Deploy from GitHub
# 3. Agregar variables de entorno (API key del LLM)
# 4. Start command: uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

## Limitaciones actuales y trabajo futuro

- Base de datos mock en JSON. En produccion: PostgreSQL o similar.
- Sin integracion con estandares HL7/FHIR del sector salud.
- Notificaciones via webhook HTTP. En produccion: cola de mensajes (RabbitMQ, SQS).
- El audit log es un archivo JSONL local. En produccion: base de datos con indices.

## Estructura del proyecto

```
er_alert_system/
├── data/
│   ├── polizas.json
│   └── historial_medico.json
├── agent/
│   ├── tools.py          <- herramientas del agente
│   └── graph.py          <- grafo LangGraph
├── api/
│   └── main.py           <- FastAPI
├── notifications/
│   └── sender.py         <- fan-out paralelo
├── frontend/
│   └── index.html        <- UI del demo
├── config.py             <- factory del LLM
├── run.py
└── requirements.txt
```