import streamlit as st
import requests

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA Y ESTILOS
# ==========================================
st.set_page_config(
    page_title="EduOrchAV | Interoperabilidad", 
    page_icon="iconoEduOrch.svg", # <--- Aquí enlazas el archivo vectorial creado
    layout="wide"
)

# Estilos CSS para forzar el modo oscuro y personalizar componentes
st.markdown("""
    <style>
    /* Ocultar menú default y footer de Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Forzar fondo oscuro general y color de texto */
    .stApp {
        background-color: #0e1117;
        color: #fafafa;
    }

    /* Fondo y texto de la barra lateral */
    [data-testid="stSidebar"] {
        background-color: #161b22;
        color: #fafafa;
    }

    /* Ajustar textos generales en la barra lateral */
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {
        color: #c9d1d9 !important;
    }

    /* Estilo de los expanders (acordeones) */
    .streamlit-expanderHeader {
        background-color: #21262d !important;
        color: #c9d1d9 !important;
        border-radius: 6px;
    }
    
    /* Contenido interno de los expanders */
    .streamlit-expanderContent {
        background-color: #0d1117 !important;
        color: #8b949e !important;
        border: 1px solid #30363d;
        border-top: none;
        border-bottom-left-radius: 6px;
        border-bottom-right-radius: 6px;
    }

    /* Cajas de chat y entradas de texto */
    .stChatInputContainer input {
        background-color: #161b22 !important;
        color: #fafafa !important;
        border: 1px solid #30363d !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. BARRA LATERAL (SIDEBAR)
# ==========================================
with st.sidebar:
    # Añadimos la imagen del ícono aquí, ajustando el tamaño (width)
    st.image("iconoEduOrch.svg", width=80)
    
    st.markdown("### EduOrchAV")
    st.caption("Modelo de orquestación con asistentes especializados")
    st.markdown("---")
    
    st.markdown("#### Reglas de dominio")
    st.caption("El orquestador enruta la consulta basándose en los siguientes perfiles estrictos:")


    with st.expander("Física"):
        st.write(
            """Dirigido a nivel secundaria (grados 9° y 10°, currículo del \textit{National Curriculum and Textbook Board}, de Bangladesh), cubre física conceptual y de resolución de problemas mediante RAG sobre el libro Physics Classes 9-10 y fuentes complementarias (Panjeree Test Paper, Teachingbd24.com), con generación a cargo de modelo de lenguaje pequeño servido vía Ollama."""
        )

    with st.expander("Matemática Básica"):
        st.write(
            """Dirigido a estudiantes desde 1ro de primaria hasta 2do de secundaria (aritmética, fracciones, porcentajes, ecuaciones de primer grado, perímetros y áreas básicas).  La generación corre sobre un modelo Ollama configurable. Rechaza explícitamente consultas avanzadas remitiéndolas a Matemática Avanzada y en consultas mixtas resuelve solo la parte básica dejando una marca de traspaso [BASE LISTA...] para que el asistente avanzado continúe."""
        )

    with st.expander("Matemática Avanzada"):
        st.write(
            """Dirigido a estudiantes desde 2do de secundaria hasta Cálculo 1 (álgebra intermedia, trigonometría, funciones, límites, derivadas e integrales). La generación corre sobre un modelo Ollama configurable, respaldado por una rutina de verificación simbólica con SymPy para derivadas, integrales y límites. Rechaza explícitamente consultas puramente básicas, remitiéndolas a Matemática Básica."""
        )

    with st.expander("Álgebra"):
        st.write(
            """Cubre álgebra y matemáticas (polinomios, factorización, ecuaciones y conceptos teóricos) mediante RAG sobre "Problemas resueltos álgebra", con generación a cargo del modelo qwen2.5:3b."""
        )

    with st.expander("Computación"):
        st.write(
            """Cubre fundamentos de computación e informática (hardware y software) mediante RAG sobre "Introducción a la Informática", con generación a cargo del modelo llama3.2:3b."""
        )

    with st.expander("Programación"):
        st.write(
            """Especializado en programación y lógica computacional con énfasis en C++, mediante RAG sobre "Programación y resolución de problemas con C++", con generación a cargo del modelo llama3.1:8b."""
        )

    with st.expander("Español"):
        st.write(
            """Cubre gramática, ortografía y literatura mediante RAG sobre "Nueva gramática básica de la Lengua Española" y "Ortografía de la Lengua Española", con generación a cargo del modelo gemma2:2b."""
        )

    with st.expander("Historia"):
        st.write(
            """Cubre historia universal y contemporánea mediante RAG sobre "Historia Universal Contemporánea Quinto semestre" de la Secretaría de Educación Pública y "Toda la historia del mundo: De la prehistoria a la actualidad", con generación a cargo del modelo gemma2:2b."""
        )

    with st.expander("Química"):
        st.write(
            """Cubre elementos, átomos y reacciones mediante RAG sobre química disponible en https://cemsa.edu.mx/ y "Química general un enfoque en competencias", con generación a cargo del modelo qwen2.5:3b."""
        )

    with st.expander("Traductor"):
        st.write(
            """Asistente conversacional de aprendizaje de idiomas voz a voz, implementado con voz-a-texto y texto-a-voz y generación mediante cualquier modelo servido vía Ollama."""
        )
# ==========================================
# 3. ENCABEZADO PRINCIPAL
# ==========================================
st.title("EduOrchAV")
st.markdown("Modelo de interoperabilidad entre asistentes virtuales educativos heterogéneos")
st.markdown("---")

# ==========================================
# 4. ÁREA CENTRAL Y LÓGICA DE CONSULTA
# ==========================================
col1, col2, col3 = st.columns([1, 8, 1])

with col2:
    query = st.chat_input("Introduce la consulta a evaluar...") 

    if query:
        # Avatar dinámico para el Usuario
        url_avatar_usuario = "https://ui-avatars.com/api/?name=U&background=004A87&color=fff&rounded=true"
        with st.chat_message("user", avatar=url_avatar_usuario):
            st.markdown(query)
        
        with st.spinner("Procesando solicitud..."):
            try:
                r = requests.post("http://localhost:5000/query", json={"query": query}, timeout=1000)
                r.raise_for_status()
                
                events = r.json().get("openFloor", {}).get("events", [])
                
                if not events:
                    st.warning("El orquestador no devolvió eventos válidos en la respuesta.")
                else:
                    for event in events:
                        if event.get("eventType") == "utterance":
                            texto = event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
                            speaker = event['parameters']['dialogEvent']['speakerUri']
                            
                            try:
                                nombre_agente = speaker.split("tag:")[1].split(".local")[0]
                            except IndexError:
                                nombre_agente = speaker 
                            
                            inicial = nombre_agente[0].upper() if nombre_agente else "A"
                            url_avatar_agente = f"https://ui-avatars.com/api/?name={inicial}&background=4A4A4A&color=fff&rounded=true"
                            
                            with st.chat_message("assistant", avatar=url_avatar_agente):
                                st.caption(f"Respuesta generada por: **{nombre_agente}**")
                                st.markdown(texto)
                                
                    with st.expander("Ver carga útil de red (JSON)"):
                        st.json(r.json())
                        
            except requests.exceptions.RequestException as e:
                st.error(f"Fallo en la comunicación con el servicio de orquestación: {e}")



# import streamlit as st
# import requests

# # ==========================================
# # 1. CONFIGURACIÓN DE LA PÁGINA Y ESTILOS
# # ==========================================
# st.set_page_config(
#     page_title="EduOrchAV | Interoperabilidad", 
#     page_icon="iconoEduOrch.svg", # <--- Aquí enlazas el archivo vectorial creado
#     layout="wide"
# )

# # Ocultar menú default y footer de Streamlit (SIN ocultar el header para no romper el sidebar)
# st.markdown("""
#     <style>
#     #MainMenu {visibility: hidden;}
#     footer {visibility: hidden;}
#     </style>
#     """, unsafe_allow_html=True)

# # ==========================================
# # 2. BARRA LATERAL (SIDEBAR)
# # ==========================================
# with st.sidebar:
#     # Añadimos la imagen del ícono aquí, ajustando el tamaño (width)
#     st.image("iconoEduOrch.svg", width=80)
    
#     st.markdown("### EduOrchAV")
#     st.caption("Modelo de orquestación con asistentes especializados")
#     st.markdown("---")
    
#     st.markdown("#### Reglas de dominio")
#     st.caption("El orquestador enruta la consulta basándose en los siguientes perfiles estrictos:")


#     with st.expander("Física"):
#         st.write(
#             """Dirigido a nivel secundaria (grados 9° y 10°, currículo del \textit{National Curriculum and Textbook Board}, de Bangladesh), cubre física conceptual y de resolución de problemas mediante RAG sobre el libro Physics Classes 9-10 y fuentes complementarias (Panjeree Test Paper, Teachingbd24.com), con generación a cargo de modelo de lenguaje pequeño servido vía Ollama."""
#         )

#     with st.expander("Matemática Básica"):
#         st.write(
#             """Dirigido a estudiantes desde 1ro de primaria hasta 2do de secundaria (aritmética, fracciones, porcentajes, ecuaciones de primer grado, perímetros y áreas básicas).  La generación corre sobre un modelo Ollama configurable. Rechaza explícitamente consultas avanzadas remitiéndolas a Matemática Avanzada y en consultas mixtas resuelve solo la parte básica dejando una marca de traspaso [BASE LISTA...] para que el asistente avanzado continúe."""
#         )

#     with st.expander("Matemática Avanzada"):
#         st.write(
#             """Dirigido a estudiantes desde 2do de secundaria hasta Cálculo 1 (álgebra intermedia, trigonometría, funciones, límites, derivadas e integrales). La generación corre sobre un modelo Ollama configurable, respaldado por una rutina de verificación simbólica con SymPy para derivadas, integrales y límites. Rechaza explícitamente consultas puramente básicas, remitiéndolas a Matemática Básica."""
#         )

#     with st.expander("Álgebra"):
#         st.write(
#             """Cubre álgebra y matemáticas (polinomios, factorización, ecuaciones y conceptos teóricos) mediante RAG sobre "Problemas resueltos álgebra", con generación a cargo del modelo qwen2.5:3b."""
#         )

#     with st.expander("Computación"):
#         st.write(
#             """Cubre fundamentos de computación e informática (hardware y software) mediante RAG sobre "Introducción a la Informática", con generación a cargo del modelo llama3.2:3b."""
#         )

#     with st.expander("Programación"):
#         st.write(
#             """Especializado en programación y lógica computacional con énfasis en C++, mediante RAG sobre "Programación y resolución de problemas con C++", con generación a cargo del modelo llama3.1:8b."""
#         )

#     with st.expander("Español"):
#         st.write(
#             """Cubre gramática, ortografía y literatura mediante RAG sobre "Nueva gramática básica de la Lengua Española" y "Ortografía de la Lengua Española", con generación a cargo del modelo gemma2:2b."""
#         )

#     with st.expander("Historia"):
#         st.write(
#             """Cubre historia universal y contemporánea mediante RAG sobre "Historia Universal Contemporánea Quinto semestre" de la Secretaría de Educación Pública y "Toda la historia del mundo: De la prehistoria a la actualidad", con generación a cargo del modelo gemma2:2b."""
#         )

#     with st.expander("Química"):
#         st.write(
#             """Cubre elementos, átomos y reacciones mediante RAG sobre química disponible en https://cemsa.edu.mx/ y "Química general un enfoque en competencias", con generación a cargo del modelo qwen2.5:3b."""
#         )

#     with st.expander("Traductor"):
#         st.write(
#             """Asistente conversacional de aprendizaje de idiomas voz a voz, implementado con voz-a-texto y texto-a-voz y generación mediante cualquier modelo servido vía Ollama."""
#         )
# # ==========================================
# # 3. ENCABEZADO PRINCIPAL
# # ==========================================
# st.title("EduOrchAV")
# st.markdown("Modelo de interoperabilidad entre asistentes virtuales educativos heterogéneos")
# st.markdown("---")

# # ==========================================
# # 4. ÁREA CENTRAL Y LÓGICA DE CONSULTA
# # ==========================================
# col1, col2, col3 = st.columns([1, 8, 1])

# with col2:
#     query = st.chat_input("Introduce la consulta a evaluar...") 

#     if query:
#         # Avatar dinámico para el Usuario (Letra U en círculo azul institucional)
#         url_avatar_usuario = "https://ui-avatars.com/api/?name=U&background=004A87&color=fff&rounded=true"
#         with st.chat_message("user", avatar=url_avatar_usuario):
#             st.markdown(query)
        
#         with st.spinner("Procesando solicitud..."):
#             try:
#                 # OJO: Usa "http://orchestrator_ollama:5000/query" si metes la UI en Docker Compose
#                 #r = requests.post("http://localhost:5000/query", json={"query": query}, timeout=1000)
#                 r = requests.post("http://localhost:5000/query", json={"query": query}, timeout=1000)

#                 r.raise_for_status()
                
#                 events = r.json().get("openFloor", {}).get("events", [])
                
#                 if not events:
#                     st.warning("El orquestador no devolvió eventos válidos en la respuesta.")
#                 else:
#                     for event in events:
#                         if event.get("eventType") == "utterance":
#                             texto = event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
#                             speaker = event['parameters']['dialogEvent']['speakerUri']
                            
#                             # =========================================================
#                             # EXTRACCIÓN PRECISA DEL ID DEL AGENTE
#                             # Convierte "tag:translator_global.local,2026:agent001" en "translator_global"
#                             # =========================================================
#                             try:
#                                 nombre_agente = speaker.split("tag:")[1].split(".local")[0]
#                             except IndexError:
#                                 nombre_agente = speaker # Fallback por si cambia el formato del orquestador
                            
#                             # Obtener inicial y generar un avatar gris oscuro profesional
#                             inicial = nombre_agente[0].upper() if nombre_agente else "A"
#                             url_avatar_agente = f"https://ui-avatars.com/api/?name={inicial}&background=4A4A4A&color=fff&rounded=true"
                            
#                             with st.chat_message("assistant", avatar=url_avatar_agente):
#                                 st.caption(f"Respuesta generada por: **{nombre_agente}**")
#                                 st.markdown(texto)
                                
#                     with st.expander("Ver carga útil de red (JSON)"):
#                         st.json(r.json())
                        
#             except requests.exceptions.RequestException as e:
#                 st.error(f"Fallo en la comunicación con el servicio de orquestación: {e}")




