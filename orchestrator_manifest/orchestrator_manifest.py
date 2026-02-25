from flask import Flask, request, jsonify
import requests
import uuid
from datetime import datetime
import jsonschema
import os
import json
import re
import unicodedata
from colorama import Fore, Style

app = Flask(__name__)

AGENTS = {
    "math": "http://assistant_math:5001/receive",
    "physics": "http://assistant_physics:5002/receive",
    "rits": "http://rits-math:5003/receive"
}

ORCHESTRATOR_URL = "http://orchestrator_manifest:5000/receive"
ORCHESTRATOR_SPEAKER_URI = "tag:orchestrator.local,2026:orch001"

SCHEMA_PATH = "/app/schemas/conversation-envelope-schema_v1.1.0.json"

try:
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        OFP_SCHEMA = json.load(f)
    print("[Manifest Orch] Schema OFP cargado OK")
except Exception as e:
    print(f"[Manifest Orch] ERROR Schema: {e}")
    OFP_SCHEMA = None

manifests = {}

def normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFD', text.lower())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text

def load_manifests():
    global manifests
    manifests = {}
    print("[Manifest Orch] Cargando manifests...")
    for key, base_url in AGENTS.items():
        manifest_url = f"{base_url.replace('/receive', '/manifest')}"
        print(f"  Intentando GET a: {manifest_url}")
        try:
            resp = requests.get(manifest_url, timeout=5)
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  JSON crudo recibido para {key}: {json.dumps(data, indent=2, ensure_ascii=False)}")
                openfloor = data.get('openFloor', {})
                events = openfloor.get('events', [])
                print(f"  Events encontrados: {len(events)}")
                for event in events:
                    if event.get('eventType') == 'publishManifest':
                        params = event.get('parameters', {})
                        manifest = params.get('manifest', params)
                        speaker_uri = manifest.get('service', {}).get('speakerUri')
                        if speaker_uri:
                            manifests[speaker_uri] = {
                                'url': manifest.get('service', {}).get('url', '') + "/receive",
                                'keywords': [normalize_text(k) for k in manifest.get('keywords', [])],
                                'capabilities': [normalize_text(c) for c in manifest.get('capabilities', [])],
                                'role': normalize_text(manifest.get('role', '')),
                                'name': manifest.get('name', '')
                            }
                            print(f"  Cargado OK: {manifests[speaker_uri]['name']} - Keywords: {manifests[speaker_uri]['keywords']}")
                        else:
                            print("  No se encontró speakerUri")
            else:
                print(f"  Falló {key}: status {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"  Error cargando {key} ({manifest_url}): {e}")

load_manifests()

def validate_envelope(data):
    if OFP_SCHEMA is None:
        return
    jsonschema.validate(instance=data, schema=OFP_SCHEMA)

def create_openfloor_envelope(events, conversation_id=None):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "conversation": {"id": conversation_id},
            "sender": {"speakerUri": ORCHESTRATOR_SPEAKER_URI},
            "events": events
        }
    }

def send_ovon_event(url, events, conversation_id=None):
    try:
        payload = create_openfloor_envelope(events, conversation_id)
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[Manifest Orch] Error enviando a {url}: {e}")
        return {"openFloor": {"events": [], "error": str(e)}}

def extract_reply_from_ovon(response):
    try:
        events = response.get("openFloor", {}).get("events", [])
        for event in events:
            if event.get("eventType") == "utterance":
                tokens = event.get("parameters", {}).get("dialogEvent", {}).get("features", {}).get("text", {}).get("tokens", [])
                if tokens:
                    return tokens[0].get("value", "Sin respuesta")
        return "Sin respuesta"
    except Exception as e:
        print(f"[Manifest Orch] Error extrayendo respuesta: {e}")
        return "Error procesando respuesta"

def get_manifest():
    return {
        "openFloor": {
            "schema": {"version": "1.1.0"},
            "events": [{
                "eventType": "publishManifest",
                "parameters": {
                    "manifest": {
                        "service": {"url": ORCHESTRATOR_URL, "speakerUri": ORCHESTRATOR_SPEAKER_URI},
                        "role": "Orquestador (manifests)",
                        "name": "EduOrch-Manifest",
                        "description": "Coordina usando manifests OVON/OFP.",
                        "keywords": ["orquestador", "interoperabilidad", "educación"],
                        "languages": ["es", "en"],
                        "modalities": ["text"],
                        "capabilities": ["delegation", "floor-management"]
                    }
                }
            }]
        }
    }

@app.route('/manifest', methods=['GET'])
def publish_manifest():
    return jsonify(get_manifest())

@app.route('/receive', methods=['POST'])
def handle_receive():
    try:
        data = request.get_json() or {}
        validate_envelope(data)
        openfloor = data.get('openFloor', {})
        events = openfloor.get('events', [])
        conversation_id = openfloor.get('conversation', {}).get('id')

        responses = []
        for event in events:
            event_type = event.get('eventType')
            if event_type == 'getManifests':
                resp = get_manifest()
                if conversation_id:
                    resp['openFloor']['conversation'] = {'id': conversation_id}
                return jsonify(resp)
            elif event_type in ['utterance', 'request_delegation', 'transfer_control', 'yield_floor']:
                responses.append({"eventType": "ack", "parameters": {"message": "Recibido"}})
            else:
                responses.append({"eventType": "error", "parameters": {"message": f"Evento no soportado: {event_type}"}})

        return jsonify(create_openfloor_envelope(responses, conversation_id))
    except Exception as e:
        print(f"[Manifest Orch] ERROR /receive: {e}")
        return jsonify({"error": str(e)}), 500

def classify_with_manifests(query: str):
    q = normalize_text(query)
    tokens = set(re.findall(r'\w+', q))

    print(f"[Manifest Orch] Clasificando: '{query}' → normalizado: '{q}' - Tokens: {tokens}")

    scores = {uri: 0 for uri in manifests}

    # Fallback directo por palabras clave obvias (prioridad máxima)
    if any(w in q for w in ['resolver', 'resuelve', 'soluciona', 'ecuacion', 'ecuaciones', 'factoriza', 'derivada', 'integral', 'logaritmo', 'simplificar', 'polinomio', 'expresion', '2x', 'x=', 'algebra']):
        print("  → Fallback directo: math")
        return ['math']

    if any(w in q for w in ['fuerza', 'velocidad', 'aceleracion', 'movimiento', 'newton', 'inercia', 'energia', 'trayectoria', 'proyectil', 'caida', 'frena', 'detener', 'tiempo', 'distancia', 'altura', 'orbita', 'satelite', 'gravedad', 'conservacion', 'segunda ley', 'ley de', 'plano inclinado']):
        print("  → Fallback directo: physics")
        return ['physics']

    if any(w in q for w in ['fraccion', 'fracciones', 'simplifica', 'suma', 'resta', 'multiplica', 'divide', 'irreductible', 'equivalentes', '1/2', '3/4', '4/5', '5/6']):
        print("  → Fallback directo: rits")
        return ['rits']

    # Si hay cálculo + física → both
    if any(w in q for w in ['calcula', 'tiempo', 'distancia', 'velocidad']) and any(w in q for w in ['aceleracion', 'caida', 'proyectil', 'frena']):
        print("  → Fallback: both por combinación cálculo + física")
        return ['both']

    # Matching con keywords del manifest (si existen)
    for uri, info in manifests.items():
        for kw in info['keywords']:
            if kw in tokens or kw in q:
                print(f"  Match manifest keyword '{kw}' → +5 para {info['name']}")
                scores[uri] += 5

    # Decisión final
    best_score = max(scores.values(), default=0)
    print(f"  Mejor score: {best_score}")

    if best_score == 0:
        print("  → No hay matches → fallback por rol")
        for uri, info in manifests.items():
            role = info['role'].lower()
            if 'math' in role:
                print("    Fallback math por rol")
                return ['math']
            elif 'physics' in role:
                print("    Fallback physics por rol")
                return ['physics']
            elif 'rule-based' in info['capabilities']:
                print("    Fallback rits por rol")
                return ['rits']
        print("    Aún sin candidatos → other")
        return ["other"]

    winners = [uri for uri, s in scores.items() if s == best_score]

    intents = []
    for uri in winners:
        role = manifests[uri]['role'].lower()
        caps = manifests[uri]['capabilities']
        if 'math' in role:
            intents.append('math')
        elif 'physics' in role:
            intents.append('physics')
        elif 'rule-based' in caps:
            intents.append('rits')

    intents = list(set(intents))

    if len(intents) > 1:
        return ['both']

    return intents if intents else ["other"]

@app.route('/query', methods=['POST'])
def handle_query():
    print(f"{Fore.GREEN}[MANIFEST ORQUESTADOR] ← Recibida pregunta{Style.RESET_ALL}")
    data = request.get_json()
    user_query = data.get('query')
    if not user_query or not isinstance(user_query, str):
        return jsonify({"error": "Falta 'query'"}), 400

    intents = classify_with_manifests(user_query)

    conversation_id = str(uuid.uuid4())

    utterance_event = [{
        "eventType": "utterance",
        "parameters": {
            "dialogEvent": {
                "speakerUri": "tag:user.local,2026:user001",
                "span": {
                    "startTime": datetime.utcnow().isoformat() + "Z",
                    "endTime": datetime.utcnow().isoformat() + "Z"
                },
                "features": {
                    "text": {
                        "mimeType": "text/plain",
                        "tokens": [{"value": user_query}]
                    }
                }
            }
        }
    }]

    # Prioridad RITS en fracciones
    if 'rits' in intents or ('math' in intents and any(word in normalize_text(user_query) for word in ['fraccion', 'fracciones', '1/2', '3/4', 'simplifica'])):
        rits_url = next((info['url'] for uri, info in manifests.items() if 'rule-based' in info['capabilities']), AGENTS["rits"])
        resp = send_ovon_event(rits_url, utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)

    elif 'both' in intents:
        invite = [{"eventType": "invite", "parameters": {"role": "collaborator"}}]
        math_url = next((info['url'] for uri, info in manifests.items() if 'math' in info['role'].lower()), AGENTS["math"])
        physics_url = next((info['url'] for uri, info in manifests.items() if 'physics' in info['role'].lower()), AGENTS["physics"])

        send_ovon_event(math_url, invite, conversation_id)
        send_ovon_event(physics_url, invite, conversation_id)

        math_resp = send_ovon_event(math_url, utterance_event, conversation_id)
        physics_resp = send_ovon_event(physics_url, utterance_event, conversation_id)

        math_text = extract_reply_from_ovon(math_resp)
        physics_text = extract_reply_from_ovon(physics_resp)
        final_reply = f"**Matemáticas:**\n{math_text}\n\n**Física:**\n{physics_text}"

    elif 'math' in intents:
        math_url = next((info['url'] for uri, info in manifests.items() if 'math' in info['role'].lower()), AGENTS["math"])
        resp = send_ovon_event(math_url, utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)

    elif 'physics' in intents:
        physics_url = next((info['url'] for uri, info in manifests.items() if 'physics' in info['role'].lower()), AGENTS["physics"])
        resp = send_ovon_event(physics_url, utterance_event, conversation_id)
        final_reply = extract_reply_from_ovon(resp)

    else:
        final_reply = "No pude clasificar claramente tu pregunta. ¿Es de matemáticas, física o ambas?"

    return jsonify({
        "reply": final_reply,
        "classified_as": ", ".join(sorted(set(intents))),
        "conversation_id": conversation_id
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)