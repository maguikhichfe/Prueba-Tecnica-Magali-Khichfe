# Soporte Bot – MineCatalog

Asistente automatizado de soporte técnico que responde preguntas usando documentación interna. Usa búsqueda semántica (FAISS + sentence-transformers) + OpenAI GPT + n8n como orquestador de webhooks.

---

## Arquitectura

```
Usuario / HTTP Client
       │
       ▼
  n8n Webhook  (POST /webhook/soporte)
       │  valida entrada
       ▼
  Python API   (POST /ask  — Flask)
       │  búsqueda semántica (FAISS)
       │  construcción de contexto
       ▼
  OpenAI API   (groq)
       │
       ▼
  Respuesta JSON  →  n8n  →  Cliente
```

---

## Requisitos previos

| Herramienta | Versión mínima | Instalación |
|---|---|---|
| Python | 3.11+ | https://python.org |
| pip | cualquiera | incluido con Python |
| n8n | 1.x | `npm install -g n8n` o Docker |
| Node.js | 18+ | https://nodejs.org (necesario para n8n) |

---

## Instalación y ejecución

### 1. Clonar / descomprimir el proyecto

```bash
git clone https://github.com/<tu-usuario>/Prueba-Técnica-<Nombre-Postulante>.git
cd Prueba-Técnica-<Nombre-Postulante>
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` y completar al menos:

```
OPENAI_API_KEY=sk-...          # tu clave de OpenAI
OPENAI_MODEL=gpt-3.5-turbo     # o gpt-4o-mini para mayor calidad
PYTHON_API_PORT=8000
```

### 3. Instalar dependencias Python

```bash
cd python
pip install -r requirements.txt
```

> En sistemas donde pip requiera el flag: `pip install -r requirements.txt --break-system-packages`

### 4. Indexar la documentación (una sola vez)

```bash
# Desde la carpeta python/
python ingest.py
```

Esto genera `faiss.index` y `chunks_meta.pkl` en la carpeta `python/`.

Salida esperada:
```
INFO: Leyendo: Documentacion_1.pdf  →  8 fragmentos generados
INFO: Leyendo: Documentacion_2.txt  →  6 fragmentos generados
INFO: Leyendo: Documentacion_3.md   →  2 fragmentos generados
INFO: Leyendo: Documentacion_4.json →  3 fragmentos generados
INFO: Índice guardado: faiss.index (19 vectores, dim=384)
INFO: Ingesta completada.
```

### 5. Levantar la API Python

```bash
# Desde la carpeta python/
python app.py
```

Verificar que esté activa:
```bash
curl http://localhost:8000/health
# → {"status": "ok", "timestamp": 1234567890.0}
```

### 6. Levantar n8n

```bash
n8n start
# n8n queda disponible en http://localhost:5678
```

### 7. Importar el workflow en n8n

1. Abrir http://localhost:5678 en el navegador.
2. Ir a **Workflows → Import from file**.
3. Seleccionar `n8n/workflow_soporte_bot.json`.
4. Hacer clic en **Activate** (toggle superior derecho) para activar el webhook.

La URL del webhook queda disponible en:
```
http://localhost:5678/webhook/soporte
```

---

## Uso

### Consulta directa a la API Python

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "No puedo iniciar sesión, dice usuario o contraseña incorrectos"}'
```

### Consulta a través de n8n

```bash
curl -X POST http://localhost:5678/webhook/soporte \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Cómo soluciono el error de código de material duplicado?"}'
```

### Respuesta JSON de ejemplo

```json
{
  "answer": "El error de código duplicado ocurre cuando se intenta registrar un material con un código que ya existe. Para solucionarlo:\n1. Buscar el código en el catálogo.\n2. Verificar si el material ya existe.\n3. Actualizar el registro existente en lugar de crear uno nuevo.\n4. Revisar la configuración de generación automática de códigos si el problema persiste.",
  "found": true,
  "sources": ["Documentacion_4.json", "Documentacion_2.txt"]
}
```

Si no hay información sobre el tema:
```json
{
  "answer": "No encontré información sobre ese tema en la documentación disponible.",
  "found": false,
  "sources": []
}
```

---

## Estructura del proyecto

```
soporte-bot/
├── docs/                        ← Documentación interna
│   ├── Documentacion_1.pdf
│   ├── Documentacion_2.txt
│   ├── Documentacion_3.md
│   └── Documentacion_4.json
├── python/
│   ├── ingest.py                ← Parte 1 y 5: ingesta, chunking, embeddings
│   ├── search.py                ← Parte 3 y 5: búsqueda semántica FAISS
│   ├── app.py                   ← Parte 2, 4 y 6: API REST Flask + OpenAI
│   ├── requirements.txt
│   ├── faiss.index              ← Generado por ingest.py
│   └── chunks_meta.pkl          ← Generado por ingest.py
├── n8n/
│   └── workflow_soporte_bot.json ← Workflow exportado de n8n
├── .env.example
└── README.md
```

---

## Decisiones técnicas

| Componente | Elección | Por qué |
|---|---|---|
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` | Multilingüe, liviano, corre sin GPU, buen rendimiento en español |
| Búsqueda | FAISS `IndexFlatIP` + L2 norm | Búsqueda por coseno exacta, suficiente para colecciones pequeñas |
| Chunking | Por párrafos + solapamiento 80 chars | Preserva contexto semántico de cada fragmento |
| LLM | OpenAI `gpt-3.5-turbo` | Capa gratuita/económica, excelente comprensión en español |
| API | Flask | Liviano, fácil de extender |
| Orquestador | n8n | Requerimiento del enunciado; permite agregar canales (Slack, email, etc.) fácilmente |

---

## Manejo de errores (Parte 6)

| Situación | Comportamiento |
|---|---|
| Pregunta vacía | HTTP 422 con mensaje descriptivo |
| Sin resultados en docs | Respuesta explícita "no encontré información" |
| Timeout en OpenAI | HTTP 504, mensaje amigable al usuario |
| Rate limit OpenAI (429) | HTTP 429, mensaje para reintentar |
| Error interno API | HTTP 500, log detallado en servidor |
| Índice no generado | HTTP 503 con instrucción para ejecutar `ingest.py` |

---

## Agregar nueva documentación

1. Copiar el archivo (`.txt`, `.md`, `.pdf`, `.json`) a la carpeta `docs/`.
2. Volver a ejecutar `python ingest.py` para reindexar.
3. No es necesario reiniciar la API; el índice se recarga en el próximo inicio.

---

## Soporte técnico

Correo: soporte.minecatalog@empresa.com  
Horario: lunes a viernes, 08h00 – 17h00
