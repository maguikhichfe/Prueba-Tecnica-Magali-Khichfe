"""
app.py — Partes 2, 4 y 6: API REST que recibe preguntas desde n8n,
recupera contexto con búsqueda semántica y consulta OpenAI para generar
la respuesta final.
"""

import os
import logging
import time
from pathlib import Path

import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from search import get_searcher

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "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"
OPENAI_MODEL = "llama-3.3-70b-versatile"
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "30"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "3000"))

SYSTEM_PROMPT = """Eres un asistente de soporte técnico para el sistema MineCatalog.
Tu función es responder preguntas de los usuarios utilizando únicamente la documentación interna proporcionada.

Reglas estrictas:
1. Responde SOLO con información que esté en el contexto entregado.
2. Si la información no está en el contexto, responde exactamente: "No encontré información sobre ese tema en la documentación disponible."
3. Sé claro, conciso y directo. Usa listas numeradas o con viñetas cuando haya pasos o causas múltiples.
4. No inventes datos, URLs, correos ni instrucciones que no aparezcan en el contexto.
5. Responde siempre en español."""


def build_context(chunks: list[dict]) -> str:
    """Construye el bloque de contexto a enviar al LLM."""
    parts = []
    total = 0
    for i, chunk in enumerate(chunks, 1):
        block = f"[Fragmento {i} — {chunk['source']}]\n{chunk['text']}"
        if total + len(block) > MAX_CONTEXT_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "\n\n---\n\n".join(parts)


def ask_openai(question: str, context: str) -> str:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY no configurada.")

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Documentación disponible:\n\n{context}\n\nPregunta del usuario: {question}"},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
    }

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=OPENAI_TIMEOUT,
    )
    
    if response.status_code == 429:
        # Rate limit: devolver respuesta basada solo en el contexto recuperado
        return f"[Respuesta basada en documentación — OpenAI rate limit activo]\n\nSegún la documentación encontrada:\n\n{context[:800]}"
    
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.route("/search", methods=["POST"])
def search_only():
    body = request.get_json() or {}
    question = body.get("question", "").strip()
    chunks = get_searcher().search(question)
    return jsonify({"fragments": chunks})



@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/ask", methods=["POST"])
def ask():
    """
    Endpoint principal. Recibe JSON con { "question": "..." }
    Devuelve { "answer": "...", "sources": [...], "found": true/false }
    """
    # ── Validar entrada ──────────────────────────────────────────────────────
    if not request.is_json:
        return jsonify({"error": "Content-Type debe ser application/json"}), 400

    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()

    if not question:
        return jsonify({"error": "El campo 'question' es obligatorio y no puede estar vacío."}), 422

    log.info(f"Pregunta recibida: {question!r}")

    # ── Búsqueda semántica ───────────────────────────────────────────────────
    try:
        searcher = get_searcher()
        chunks = searcher.search(question)
    except FileNotFoundError:
        log.error("Índice FAISS no encontrado. Ejecuta python ingest.py primero.")
        return jsonify({"error": "El índice de documentación no está disponible. Contacta al administrador."}), 503
    except Exception as e:
        log.exception("Error en búsqueda semántica")
        return jsonify({"error": f"Error interno en búsqueda: {str(e)}"}), 500

    if not chunks:
        log.info("Sin resultados relevantes en documentación.")
        return jsonify({
            "answer": "No encontré información sobre ese tema en la documentación disponible.",
            "sources": [],
            "found": False,
        })

    context = build_context(chunks)
    sources = list({c["source"] for c in chunks})
    log.info(f"Contexto construido desde: {sources}")

    # ── Consulta al LLM ──────────────────────────────────────────────────────
    try:
        answer = ask_openai(question, context)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503
    except requests.exceptions.Timeout:
        log.error("Timeout en llamada a OpenAI")
        return jsonify({"error": "El servicio de IA tardó demasiado en responder. Intenta nuevamente."}), 504
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else 0
        if status == 429:
            return jsonify({"error": "Límite de solicitudes a OpenAI alcanzado. Intenta en unos minutos."}), 429
        log.exception("Error HTTP en OpenAI")
        return jsonify({"error": f"Error al consultar el servicio de IA (HTTP {status})."}), 502
    
    except Exception as e:
        
        log.exception("Error inesperado al consultar OpenAI")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

    log.info("Respuesta generada correctamente.")
    return jsonify({
        "answer": answer,
        "sources": sources,
        "found": True,
    })


if __name__ == "__main__":
    port = int(os.getenv("PYTHON_API_PORT", "8000"))
    log.info(f"Iniciando API en puerto {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
