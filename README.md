# Modelo para la Interoperabilidad de Datos entre Asistentes Virtuales Educativos Heterogéneos

![Portada de la Tesis](path/a/la/imagen/de/la/portada.jpg)  <!-- Si tienes la imagen en el repo, pon la ruta; si no, quítala -->

## Introducción

Este prototipo implementa un modelo de interoperabilidad basado en el protocolo Open Voice Interoperability Network (OVON) y Open Floor Protocol (OFP) para permitir la colaboración entre asistentes virtuales educativos (AVE) heterogéneos. El sistema integra asistentes especializados en matemáticas, física y fracciones básicas, permitiendo que respondan de forma individual o colaborativa a consultas de estudiantes.

El prototipo está diseñado para demostrar cómo asistentes con tecnologías diferentes pueden comunicarse de manera estandarizada, superando la heterogeneidad técnica y arquitectónica. Está orientado a estudiantes de nivel básico a medio (primaria, secundaria, bachillerato), con enfoque en temas formales como matemáticas y ciencias físicas.

**Tecnologías clave**:
- Protocolo: OVON/OFP v1.1.0 (para manifests, envelopes, events).
- Contenerización: Docker y Docker Compose.
- Wrappers: Flask para APIs REST compatibles con OFP.
- Orquestador: Python con lógica de clasificación y delegación.

**Cómo ejecutar el prototipo**:
1. Clona el repositorio: `git clone <repo-url>`.
2. Instala dependencias: `pip install -r requirements.txt` (en cada carpeta si es necesario).
3. Levanta con Docker Compose: `docker compose up --build`.
4. Prueba consultas: Envía POST a `http://localhost:5000/query` o `http://localhost:5001/query` (según el orquestador).
   Ejemplo: `curl -X POST http://localhost:5000/query -H "Content-Type: application/json" -d '{"query": "Resuelve 2x + 5 = 13"}'`.

**Dependencias**:
- Python 3.10
- Flask, requests, jsonschema, ollama (para versión con Ollama)
- Docker, Docker Compose
- SWI-Prolog (para RITS)
- Ollama (para asistentes LLM/RAG, opcional en orquestador con manifests)

**Limitaciones generales**:
- Solo soporta texto (no voz o multimodal).
- Clasificación depende de keywords/manifests o LLM (según versión).
- No maneja contexto multi-turno avanzado (solo conversation_id básico).
- Orientado a educación básica/media; no para universidad avanzada.

## Asistentes Virtuales Educativos (AVE)

El prototipo incluye tres asistentes heterogéneos, cada uno con arquitectura, tecnología y enfoque diferente. Todos exponen endpoints `/manifest` y `/receive` mediante wrappers Flask, compatibles con OFP para publicación de capacidades y recepción de mensajes.

### 1. Asistente de Matemáticas (Qwen-Math)

- **Orientado a**: Estudiantes de secundaria y bachillerato que necesitan resolver problemas matemáticos paso a paso.
- **Nivel de enseñanza**: Básico a medio (álgebra, cálculo, ecuaciones, geometría).
- **Límites**: No maneja temas avanzados como matemáticas discretas o análisis complejo. Puede generar errores en problemas ambiguos o muy creativos. Dependiente de Ollama para inferencia, lo que consume recursos.
- **Arquitectura**: Basado en modelo de lenguaje grande (LLM) con fine-tuning para matemáticas. Usa razonamiento paso a paso (step-by-step) para explicar soluciones.
- **Tecnología**: Ollama (servidor local LLM), modelo Qwen2:7b (quantizado Q4_0). Wrapper Flask traduce peticiones OFP a llamadas al modelo y responde en envelope OFP.
- **Capacidades**: Resuelve ecuaciones, factoriza, calcula derivadas, simplifica expresiones. Publica manifest con keywords ["matemáticas", "ecuaciones", "cálculo", "álgebra"] y capabilities ["math-solving", "step-by-step-explanation"].
- **Ejemplo de uso**: "Resuelve 2x + 5 = 13" → "Paso 1: Resta 5... Paso 2: Divide por 2... x = 4".

### 2. Asistente de Física (Physics RAG)

- **Orientado a**: Estudiantes de secundaria y bachillerato que buscan explicaciones conceptuales o cálculos físicos con contexto real.
- **Nivel de enseñanza**: Básico a medio (mecánica clásica, leyes de Newton, energía, movimiento).
- **Límites**: Dependiente de PDF cargados para RAG (no busca en web). No maneja temas avanzados como cuántica o relatividad. Si el vectorstore falla, responde con LLM básico (menos preciso).
- **Arquitectura**: Retrieval-Augmented Generation (RAG): carga PDF de física, crea vectorstore para búsquedas semánticas, combina con LLM para respuestas contextualizadas.
- **Tecnología**: Ollama para LLM, LangChain o similar para RAG (embeddings, vectorstore). Wrapper Flask traduce OFP a consultas RAG y responde compliant.
- **Capacidades**: Explica leyes físicas, calcula velocidades/aceleración, conservación de energía. Manifest con keywords ["física", "movimiento", "fuerzas", "energía"] y capabilities ["physics-explanation", "rag-enhanced"].
- **Ejemplo de uso**: "Explica la inercia" → "La inercia es la tendencia de un objeto a resistir cambios en su movimiento. Ejemplo: un pasajero en un auto que frena se inclina adelante".

### 3. Asistente RITS (Rule-Based Intelligent Tutoring System)

- **Orientado a**: Estudiantes de primaria/secundaria que necesitan práctica guiada en fracciones básicas.
- **Nivel de enseñanza**: Básico (fracciones simples, operaciones aritméticas con fracciones).
- **Límites**: Solo maneja fracciones básicas (suma/resta/multiplicación/división, simplificación). No soporta álgebra avanzada ni conceptos no formales. Es determinístico, pero no creativo (no genera ejemplos nuevos).
- **Arquitectura**: Basado en reglas lógicas (no LLM). Usa tutoría interactiva paso a paso con hints, corrección y explicación pedagógica.
- **Tecnología**: SWI-Prolog para lógica rule-based. Wrapper Flask para OFP, pyswip para interfaz Python-Prolog.
- **Capacidades**: Simplifica fracciones, suma/resta con denominador común, conversión decimal-fracción. Manifest con keywords ["fracciones", "matemáticas básicas", "suma fracciones"] y capabilities ["rule-based-tutoring", "step-by-step-explanation"].
- **Ejemplo de uso**: "What is 1/2 + 1/3?" → "Paso 1: Denominador común 6. 1/2 = 3/6, 1/3 = 2/6. Paso 2: Suma 5/6. Simplificado".

## Los Wrappers

Cada asistente tiene un **wrapper** (en Flask) para exponer una API compatible con OFP. Los wrappers conforman el "adaptador" que traduce la tecnología interna del asistente a envelopes OFP.

- **Arquitectura general de wrappers**:
  - Endpoint `/manifest`: Publica las capacidades del asistente (role, keywords, capabilities).
  - Endpoint `/receive`: Recibe envelope OFP, valida contra schema, extrae utterance (pregunta), procesa con tecnología interna, devuelve respuesta en envelope OFP.
  - Validación: Usa jsonschema con schema oficial OVON/OFP v1.1.0.
  - Manejo de events: utterance, getManifests, request_delegation.

- **Tecnología común**: Python 3.10, Flask para API, jsonschema para validación. Montados en Docker con volúmenes para schemas.
- **Límites**: No soportan multi-turno avanzado (solo conversation_id). Dependientes de la tecnología interna (e.g., Ollama para math/physics).
- **Ejemplo de estructura** (común a todos):
  - Carga schema OFP.
  - Publica manifest.
  - En /receive: valida envelope, procesa utterance, responde compliant.

## El Orquestador

El orquestador es el componente central que coordina la interoperabilidad.

- **Orientado a**: Estudiantes que hacen consultas educativas, delegando a asistentes especializados o colaborativos.
- **Nivel de enseñanza**: Adaptable (básico/medio, según asistentes).
- **Límites**: Clasificación basada en keywords/manifests (puede fallar en preguntas ambiguas). No soporta más de 2 colaboradores simultáneos. Dependiente de manifests bien definidos.
- **Arquitectura**: Flask para API, carga manifests al inicio, clasifica pregunta por matching keywords/capabilities, envía envelopes OFP, combina respuestas.
- **Tecnología**: Python 3.10, Flask, requests, jsonschema. Dos versiones: con Ollama (clasificación LLM) y sin (clasificación manifests).
- **Capacidades**: Clasificación de intención, delegación individual/colaborativa, mantenimiento de conversation_id. Publica su propio manifest.
- **Ejemplo de uso**: Pregunta "1/2 + 1/3" → clasifica "rits", envía a RITS, devuelve explicación.

Para más detalles, consulta el código fuente o ejecuta el prototipo. Si tienes preguntas, contacta a Deneb Moliner Morales.


• math-assistant/ → Qwen2.5-Math
https://github.com/QwenLM/Qwen2.5-Math

• physics-assistant/ → Physics-Chatbot-using-Advanced-RAG  
https://github.com/tan7vir/Physics-Chatbot-using-Advanced-RAG

# ALICE + AIML (el más rápido y conversacional)

Tipo: Patrones de reglas XML (coincidencia exacta + wildcards). 100% simbólico.
Asignaturas: Historia, Cultura general, Idiomas, Geografía, Biología básica, Química introductoria, cualquier cosa que quieras (solo agregas reglas).
Base de conocimiento: Trae el ALICE Foundation Set (miles de reglas pre-hechas: hechos históricos, definiciones, conversaciones básicas, preguntas comunes). Ya chatea decentemente desde el minuto 1 sin que tú hagas nada.
Repo: https://github.com/drwallace/aiml-en-us-foundation-alice/tree/master

Docker: Casi todos se dockerizan en 5 minutos (hay imágenes públicas de ProgramAB o pyAIML).
Wrapper: Súper sencillo. El intérprete AIML expone una función getResponse(texto). Envuelves en FastAPI y listo para tu protocolo Open Floor.
Ventaja para prototipo: En 1 hora tienes un asistente conversacional de historia funcionando con conocimiento base.

# HistoryBot
  HistoryBot is a virtual assistant specializing in historical inquiries. Trained on the intents.json dataset, it is adept at recognizing and responding to a variety of historical questions within its training data's scope. With regular updates, HistoryBot ensures an adaptable and enriching user experience.
https://github.com/amiruzzaman1/History-Bot

Enfoque: Historia general.
Tecnología: Procesamiento de Lenguaje Natural (NLP) tradicional y concordancia de patrones.


# MathBuddyBot
https://github.com/parvanovkp/MathBuddyBot

# LingoNaut
https://github.com/FoamoftheSea/lingonaut-python

## Requisitos  del prototipo del modelo de interoperabilidad de datos entre entre AVs usando OFP

- Docker & Docker Compose
- Ollama corriendo (modelos: qwen2:7b o phi3:mini)
- Puertos libres: 5000, 5001, 5002, 5003, 5004, 11434

## Comandos Docker útiles

### Control global

```bash
# Detener todo
docker compose down

# Detener y limpiar (muy recomendado cuando hay errores)
docker compose down --remove-orphans --volumes

# Reconstruir todo desde cero
docker compose build --no-cache
docker compose up -d

# Reconstruir y levantar solo un servicio
docker compose build --no-cache orchestrator_manifest
docker compose up -d orchestrator_manifest

# Lista de contenedores y puertos
docker compose ps

# Ver todas las imágenes
docker images | grep edu-avs-ovon

# Logs del orquestador manifests en tiempo real
docker logs -f orchestrator_manifest

# Últimas 100 líneas (rápido)
docker logs orchestrator_manifest --tail 100

# Logs de un asistente específico
docker logs assistant_math --tail 50
docker logs assistant_physics --tail 50
docker logs rits-math --tail 50

# Logs de Ollama (para ver si carga modelos)
docker logs ollama_server --tail 50

# Borrar redes huérfanas
docker network prune -f

# Borrar todo lo no usado (cuidado: borra imágenes y volúmenes)
docker system prune -a -f --volumes


stemming al manifest significa normalizar las palabras clave (keywords/capabilities) a su raíz lingüística para que el orquestador pueda hacer matching semántico más flexible y no depender de coincidencias exactas.


1. Verificar en qué carpeta estoy 
git status  

2. Agrega los archivos
git add .

3. Haz el commit
git commit -m "Descripción de los cambios"

4. Sube (push) al repositorio
git push


# PARA Abrir la carpeta directamente en el Explorador de Windows desde WSL
cd ~/tesis/edu-avs-ovon
explorer.exe .



¿Cómo correr la UI a partir de ahora?
Cada vez que quieras ver tu modelo de interoperabilidad funcionando en la web:

# 1- Asegúrate de que tus contenedores de Docker estén corriendo 
docker compose up -d

# 2- En la terminal, activa el entorno:
 source venv/bin/activate

# 3- Lanza la aplicación: 
streamlit run ui.py

#Logs en tiempo real, abre una segunda terminal (mantén la de Streamlit abierta en una y abre otra nueva) y ejecuta este comando en la carpeta de tu proyecto, -f (follow): Hace que la pantalla se actualice automáticamente cada vez que un agente escribe algo.


docker compose logs -f


#Si solo te interesan algunos agentes para no marearte con tanto texto, puedes filtrar:
docker compose logs -f orchestrator_ollama assistant_translator mathbuddy-avanzado-backend


# CAMBIOS SEGUN SI estoy en PC de 11 GB de GPU o 4 GPU


  - OLLAMA_NUM_GPU_LAYERS=-1
  - NVIDIA_VISIBLE_DEVICES=all
  - OLLAMA_KEEP_ALIVE=-1  
  # JUSTADO A 11GB
  - OLLAMA_MAX_LOADED_MODELS=2
  - OLLAMA_NUM_PARALLEL=2
  - OLLAMA_MAX_QUEUE=6  
  - OLLAMA_NUM_THREADS=0



   - OLLAMA_NUM_GPU_LAYERS=20     # no usar -1 (no cabe todo en GPU)
  - NVIDIA_VISIBLE_DEVICES=all
  - OLLAMA_KEEP_ALIVE=-1
  #  PARA 4GB
  - OLLAMA_MAX_LOADED_MODELS=1
  - OLLAMA_NUM_PARALLEL=1
  - OLLAMA_MAX_QUEUE=2
  - OLLAMA_NUM_THREADS=0