"""
AI race engineer assistant — powered by local Ollama LLM.
Streams tokens back to the client for fast perceived response.
"""

import json
import requests
from flask import Blueprint, request, jsonify, Response, stream_with_context
from database.db import get_db
from processing.ai_context import build_full_context
import config

ai_bp = Blueprint('ai', __name__)


def _ollama_chat(system_prompt, history, user_message, stream=True, model=None):
    """
    Call Ollama /api/chat. Yields text chunks if stream=True,
    returns full string if stream=False.
    """
    messages = [{'role': 'system', 'content': system_prompt}]
    messages.extend(history)
    messages.append({'role': 'user', 'content': user_message})

    payload = {
        'model': model or config.OLLAMA_MODEL,
        'messages': messages,
        'stream': stream,
        'options': {'temperature': 0.7, 'num_predict': 600},
    }

    resp = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json=payload,
        timeout=config.OLLAMA_TIMEOUT,
        stream=stream,
    )
    resp.raise_for_status()

    if stream:
        for line in resp.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    token = chunk.get('message', {}).get('content', '')
                    if token:
                        yield token
                except json.JSONDecodeError:
                    pass
    else:
        yield resp.json()['message']['content']


def _get_best_model(available_models):
    """
    Pick the best available model for the race engineer persona.
    Priority: user-configured > phi3:mini > llama3.2 > any small model > first available.
    """
    if not available_models:
        return config.OLLAMA_MODEL
    # Prefer configured model
    for m in available_models:
        if m == config.OLLAMA_MODEL or m.startswith(config.OLLAMA_MODEL.split(':')[0]):
            return m
    # Preferred fallbacks (good for conversation)
    for preferred in ['phi3', 'llama3.2', 'llama3', 'mistral', 'gemma', 'qwen2.5']:
        for m in available_models:
            if m.startswith(preferred):
                return m
    # Last resort: just use whatever is installed
    return available_models[0]


@ai_bp.route('/ai/status', methods=['GET'])
def ai_status():
    try:
        resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        models = [m['name'] for m in resp.json().get('models', [])]
        active_model = _get_best_model(models)
        model_ready = len(models) > 0
        return jsonify({
            'online': True,
            'model': active_model,
            'model_ready': model_ready,
            'available_models': models,
        })
    except Exception as e:
        return jsonify({'online': False, 'error': str(e)})


@ai_bp.route('/ai/chat', methods=['POST'])
def chat():
    data = request.get_json()
    session_id = data.get('session_id')
    user_message = data.get('message', '').strip()
    stream_response = data.get('stream', True)

    if not user_message:
        return jsonify({'error': 'message required'}), 400

    db = get_db()

    # Build history (last 10 exchanges to stay within context)
    history = []
    if session_id:
        rows = db.execute(
            """SELECT role, content FROM ai_conversations
               WHERE session_id=? ORDER BY created_at DESC LIMIT 20""",
            (session_id,)
        ).fetchall()
        history = [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]

    # Determine the best available model
    try:
        tags_resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        available = [m['name'] for m in tags_resp.json().get('models', [])]
        active_model = _get_best_model(available)
    except Exception:
        active_model = config.OLLAMA_MODEL

    # Build system prompt
    if session_id:
        system_prompt = build_full_context(session_id)
    else:
        from processing.ai_context import RACE_ENGINEER_PROMPT, build_kart_context
        system_prompt = RACE_ENGINEER_PROMPT.format(
            kart_comparison_data=build_kart_context(),
            session_data="No specific session selected."
        )

    def _save_exchange(user_msg, assistant_msg):
        if session_id:
            db.execute(
                "INSERT INTO ai_conversations (session_id, role, content) VALUES (?,?,?)",
                (session_id, 'user', user_msg)
            )
            db.execute(
                "INSERT INTO ai_conversations (session_id, role, content) VALUES (?,?,?)",
                (session_id, 'assistant', assistant_msg)
            )
            db.commit()
        db.close()

    if stream_response:
        def generate():
            full_reply = []
            try:
                for token in _ollama_chat(system_prompt, history, user_message,
                                          stream=True, model=active_model):
                    full_reply.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                _save_exchange(user_message, ''.join(full_reply))
            except requests.exceptions.ConnectionError:
                yield f"data: {json.dumps({'error': 'Ollama is offline. Run: ollama serve'})}\n\n"
                db.close()
            except requests.exceptions.Timeout:
                yield f"data: {json.dumps({'error': 'Ollama timed out loading the model. Try again — it will be faster once loaded.'})}\n\n"
                db.close()
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                db.close()

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'X-Content-Type-Options': 'nosniff',
            }
        )
    else:
        try:
            reply = ''.join(_ollama_chat(system_prompt, history, user_message,
                                         stream=False, model=active_model))
            _save_exchange(user_message, reply)
            return jsonify({'reply': reply})
        except requests.exceptions.ConnectionError:
            db.close()
            return jsonify({'error': 'Ollama is offline'}), 503
        except Exception as e:
            db.close()
            return jsonify({'error': str(e)}), 500


@ai_bp.route('/ai/conversations/<int:session_id>', methods=['GET'])
def get_conversations(session_id):
    db = get_db()
    rows = db.execute(
        """SELECT role, content, created_at FROM ai_conversations
           WHERE session_id=? ORDER BY created_at ASC""",
        (session_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@ai_bp.route('/ai/conversations/<int:session_id>', methods=['DELETE'])
def clear_conversations(session_id):
    db = get_db()
    db.execute("DELETE FROM ai_conversations WHERE session_id=?", (session_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})
