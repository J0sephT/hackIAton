# ARIA — Sistema de Alerta Temprana de Ingresos a Emergencias

Agente LangGraph que se activa vía webhook cuando un asegurado ingresa a emergencias,
valida la póliza, revisa preexistencias y notifica simultáneamente a hospital y gestor.

## Estructura

```
er_alert_system/
├── data/
│   ├── polizas.json           ← BD mock de pólizas (6 casos de prueba)
│   └── historial_medico.json  ← BD mock de historiales con preexistencias
├── agent/
│   ├── tools.py               ← Herramientas del agente (validar_poliza, etc.)
│   └── graph.py               ← Grafo LangGraph (lógica del agente ARIA)
├── api/
│   └── main.py                ← FastAPI: webhook receiver + endpoints
├── notifications/
│   └── sender.py              ← Fan-out paralelo de notificaciones
├── config.py                  ← Config central + factory del LLM
├── run.py                     ← Punto de entrada
├── requirements.txt
└── .env.example
```

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env
# Edita .env con tu API key del LLM y config
```

## Correr

```bash
python run.py
# API disponible en http://localhost:8000
# Docs automáticas en http://localhost:8000/docs
```

## Probar

### Simular ingreso (para el demo)
```bash
curl -X POST "http://localhost:8000/simular?cedula=1001234567&motivo=Dolor%20toracico"
# Responde con evento_id, luego:
curl "http://localhost:8000/resultado/EVT-XXXXXXXX"
```

### Webhook real
```bash
curl -X POST http://localhost:8000/webhook/er-admission \
  -H "Content-Type: application/json" \
  -d '{
    "cedula": "1001234567",
    "hospital_id": "HOS-001",
    "hospital_nombre": "Hospital General",
    "motivo_ingreso": "Hiperglucemia severa"
  }'
```

## Casos de prueba (cédulas)

| Cédula       | Escenario                                 | Decisión esperada   |
|--------------|-------------------------------------------|---------------------|
| 1001234567   | Póliza Gold vigente + preexistencias OK  | APROBADA            |
| 1002345678   | Póliza Silver, límite casi agotado        | REQUIERE_REVISION   |
| 1003456789   | Póliza vencida + preexistencias ocultas   | RECHAZADA           |
| 1004567890   | Póliza Platinum suspendida por mora       | RECHAZADA           |
| 1005678901   | Póliza Gold + epilepsia no declarada      | REQUIERE_REVISION   |
| 1006789012   | Póliza Silver + Lupus declarado           | APROBADA con alertas|

## Cambiar LLM

Solo edita `.env`:
```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-haiku-20240307
```
Sin tocar una línea del agente.
