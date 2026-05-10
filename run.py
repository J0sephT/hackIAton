"""
run.py — Punto de entrada para levantar el servidor ARIA.
Ejecuta desde la raíz del proyecto:
    python run.py
O con uvicorn directamente:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""

import uvicorn
from config import APP_HOST, APP_PORT

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║   ARIA - Agente de Respuesta Inmediata en Admisiones    ║
║   Sistema de Alerta Temprana de Ingresos a Emergencias  ║
╚══════════════════════════════════════════════════════════╝
""")
    uvicorn.run(
        "api.main:app",
        host=APP_HOST,
        port=APP_PORT,
        reload=True,
        log_level="info"
    )
