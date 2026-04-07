import streamlit as st
import requests

st.set_page_config(page_title="Edu-AVS Interoperability", layout="wide")
st.title("🎓 EduOrch: Sistema de Asistentes Educativos")

query = st.text_area("Introduce tu consulta para los agentes:", placeholder="Ej: Traduce al francés: deriva f(x)=x^2")

if st.button("Consultar Sistema"):
    if query:
        with st.spinner("Los agentes están colaborando..."):
            try:
                # Cambia el puerto si tu orquestador usa otro
                r = requests.post("http://localhost:5000/query", json={"query": query}, timeout=180)
                r.raise_for_status()
                
                # Extraemos el contenido del evento 'utterance'
                events = r.json().get("openFloor", {}).get("events", [])
                
                # Mostramos la respuesta final (normalmente la última del traductor)
                for event in events:
                    if event.get("eventType") == "utterance":
                        texto = event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
                        st.subheader(f"Respuesta de: {event['parameters']['dialogEvent']['speakerUri']}")
                        st.markdown(texto) # <-- Aquí ocurre la magia del formato
                        
            except Exception as e:
                st.error(f"Error de conexión: {e}")
    else:
        st.warning("Por favor, escribe algo.")