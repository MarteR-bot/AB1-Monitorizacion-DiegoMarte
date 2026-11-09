# Monitorización de sistema con n8n

Un script en Python mide CPU, RAM, SWAP, temperatura y los cinco procesos que más memoria usan. Cada cinco lecturas (unos 20 segundos) envía las medias a un webhook de n8n. El workflow comprueba los umbrales y, si se supera alguno, un modelo de lenguaje local explica la situación y propone acciones. El resultado llega por correo electrónico.

## Contenido de la entrega

```
proyecto-monitorizacion/
├── workflow.json       # workflow de n8n exportado
├── monitor.py          # script de monitorización
├── requirements.txt    # dependencias de Python
└── README.md
```

## Cómo funciona

```
monitor.py --POST JSON--> Webhook --> Code in JavaScript --> If --> Message a model --> Send an Email
```

El script envía este JSON a la ruta `/monitor` del webhook:

```json
{
  "mediaRAM": 62.3,
  "mediaCPU": 31.8,
  "SwapPorcentaje": 12.0,
  "temperatura": null,
  "procesos": [
    { "nombre": "Google Chrome", "ram_porcentaje": 9.7, "usuario": "usuario" }
  ]
}
```

El nodo Code compara cada valor con su umbral. Los umbrales están en la constante `UMBRALES` de ese nodo:

| Métrica | Umbral |
|---|---|
| CPU media | 80 % |
| RAM media | 85 % |
| SWAP | 70 % |
| Temperatura | 80 °C |

Si ninguna métrica supera su umbral, el nodo If corta la ejecución y no se envía nada.

## Nodos deterministas y nodos de IA

| Nodo | Tipo | Función |
|---|---|---|
| Webhook | Determinista | Recibe el POST de `monitor.py`. |
| Code in JavaScript | Determinista | Compara las métricas con los umbrales y construye la lista de alertas y el booleano `hayAlertas`. |
| If | Determinista | Deja pasar solo las ejecuciones con `hayAlertas` verdadero. |
| Message a model | IA | Modelo `llama3.2:3b` en Ollama. Recibe las alertas, los valores actuales y los procesos, y redacta un diagnóstico con tres acciones. |
| Send an Email | Determinista | Envía por SMTP el texto que generó el modelo. |

La decisión de avisar es determinista. El modelo no evalúa si hay alerta: recibe las que el nodo Code ya calculó. El prompt de sistema limita la respuesta a los datos recibidos, pide texto plano en español y prohíbe afirmar nada sobre el desgaste del hardware. La temperatura del modelo es 0.1 para que las respuestas varíen poco entre ejecuciones.

## Requisitos

- n8n en local, en una versión reciente (el workflow usa la versión 2.3 del nodo If).
- Python 3.9 o superior.
- Ollama con el modelo `llama3.2:3b`.
- Una cuenta de correo con acceso SMTP.
- InfluxDB 2.x (opcional, ver más abajo).

Probado con n8n TU_VERSION_N8N, Python TU_VERSION_PYTHON y macOS.

## Puesta en marcha

1. Instala las dependencias de Python dentro de un entorno virtual:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate      # en Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Descarga el modelo en Ollama:

   ```bash
   ollama pull llama3.2:3b
   ```

3. En n8n, importa el workflow: en la lista de workflows, menú `⋯` y "Import from file", y elige `workflow.json`.

4. Crea las dos credenciales y asígnalas a sus nodos. Al importar, los nodos aparecen sin credencial.
   - Ollama, para el nodo "Message a model". Base URL: `http://localhost:11434`. Si n8n corre en Docker, usa `http://host.docker.internal:11434`.
   - SMTP, para el nodo "Send an Email". Con Gmail: host `smtp.gmail.com`, puerto 465 con SSL, usuario la dirección de correo y como contraseña una contraseña de aplicación (requiere verificación en dos pasos).

5. En el nodo "Send an Email", cambia los campos From Email y To Email por tu dirección. Con Gmail, From debe coincidir con la cuenta autenticada.

6. En `monitor.py`, usa la URL de producción del webhook. Comenta la línea de `webhook-test` y descomenta la de `/webhook/`:

   ```python
   #N8N_WEBHOOK = "http://localhost:5678/webhook-test/monitor"
   N8N_WEBHOOK = "http://localhost:5678/webhook/monitor"
   ```

   La URL de `webhook-test` solo acepta una llamada por cada vez que pulsas "Listen for test event" en el editor, así que no sirve para un script que envía datos de forma continua.

7. Activa el workflow en n8n (interruptor Active o botón Publish, según la versión).

8. Ejecuta el script:

   ```bash
   python3 monitor.py
   ```

   Muestra cada lectura por pantalla. Cuando completa cinco lecturas imprime "ENVIO A n8n" y el estado de la petición. Se detiene con Ctrl+C.

## Cómo probarlo

Un equipo normal no supera los umbrales, así que lo más rápido es simular una alerta enviando datos a mano al webhook (con el workflow activo):

```bash
curl -X POST http://localhost:5678/webhook/monitor \
  -H "Content-Type: application/json" \
  -d '{
    "mediaRAM": 92.4,
    "mediaCPU": 86.1,
    "SwapPorcentaje": 75.0,
    "temperatura": 86,
    "procesos": [
      {"nombre": "Docker Desktop", "ram_porcentaje": 18.2, "usuario": "usuario"},
      {"nombre": "Google Chrome", "ram_porcentaje": 9.7, "usuario": "usuario"},
      {"nombre": "Code Helper", "ram_porcentaje": 6.1, "usuario": "usuario"}
    ]
  }'
```

Ese JSON supera los cuatro umbrales. En la pestaña Executions de n8n debe aparecer una ejecución con todos los nodos en verde, y el correo llega en unos segundos. La primera llamada tarda más porque Ollama carga el modelo en memoria. En Windows puedes lanzar la misma petición con Postman.

Otra opción es bajar temporalmente los valores de `UMBRALES` en el nodo Code (por ejemplo `cpu: 1`) y dejar corriendo `monitor.py`.

## InfluxDB (opcional)

En cada ciclo el script también escribe las lecturas en InfluxDB (medida `ordenador_personal`) para poder graficarlas. La configuración está al principio de `monitor.py`:

```python
TOKEN = ""            # token de InfluxDB
ORG = "MSMK"
BUCKET = "Memoria_RAM"
URL = "http://localhost:8086"
```

Sin InfluxDB, o con el token vacío, el script imprime "Error enviando datos a InfluxDB" en cada ciclo y sigue funcionando. El envío a n8n no depende de InfluxDB. No subas el token a ningún repositorio.

## Temperatura según el sistema

`psutil` solo ofrece lectura de temperatura en Linux y FreeBSD. En macOS y Windows la función no existe, el script envía `"temperatura": null` y el nodo Code se salta esa comprobación. La alerta de temperatura solo se activa con datos reales en Linux, o con el `curl` de arriba.

## Problemas frecuentes

- El script imprime un error 404 al enviar a n8n: el workflow no está activo, o `N8N_WEBHOOK` sigue apuntando a `webhook-test`.
- El script imprime "enviado correctamente" pero no llega ningún correo: ninguna métrica superó su umbral y el nodo If terminó la ejecución. Comprueba la pestaña Executions.
- Error de conexión en "Message a model": Ollama no está en marcha o la Base URL de la credencial no es accesible desde n8n (caso de Docker, ver paso 4).
- Error de modelo no encontrado: falta ejecutar `ollama pull llama3.2:3b`.
- Error de autenticación en "Send an Email": con Gmail hace falta una contraseña de aplicación, no la contraseña normal de la cuenta.
- `ModuleNotFoundError` al ejecutar el script: el entorno virtual no está activado o falta `pip install -r requirements.txt`.

## Limitaciones conocidas

- No hay control de repetición. Mientras una métrica siga por encima del umbral llegará un correo cada unos 20 segundos. Detén el script con Ctrl+C al terminar las pruebas.
- El nombre del equipo, `MacBook_Diego`, está escrito a mano en `monitor.py` y como valor por defecto en el prompt del nodo de IA. El prompt de sistema también da por hecho que el equipo es un Mac con macOS.
