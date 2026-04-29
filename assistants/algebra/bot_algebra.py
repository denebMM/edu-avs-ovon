from flask import Flask, request, jsonify
import PyPDF2
import requests

app = Flask(__name__)

# --- TUS FUNCIONES DE PDF (IGUALES) ---
def cargar_pdf(nombres):
    texto = ""
    for nombre in nombres:
        try:
            with open(nombre, "rb") as f:
                lector = PyPDF2.PdfReader(f)
                for pagina in lector.pages:
                    contenido = pagina.extract_text()
                    if contenido: texto += contenido + "\n"
        except Exception as e:
            print(f"Error cargando {nombre}: {e}")
    return texto

def recuperar_contexto(pregunta, texto):
    palabras = pregunta.lower().split()
    fragmentos = [linea.strip() for linea in texto.split("\n") 
                  if any(p in linea.lower() for p in palabras)]
    return "\n".join(fragmentos[:8])

# --- CARGA INICIAL (SOLO UNA VEZ) ---
print("📘 Cargando libros de álgebra...")
LIBRO_DATA = cargar_pdf(["algebra.pdf", "algebra1.pdf"])
print("✅ Libros listos")

@app.route('/preguntar', methods=['POST'])
def preguntar():
    data = request.json
    pregunta = data.get("pregunta", "")
    
    contexto = recuperar_contexto(pregunta, LIBRO_DATA)
    
    # IMPORTANTE: Cambiamos localhost por 'ollama' para Docker
    prompt = f"Eres un profesor experto en algebra.\nContexto:\n{contexto}\nPregunta: {pregunta}"
    
    try:
        response = requests.post(
            "http://ollama:11434/api/generate",
            json={
                "model": "qwen3-embedding:4b", # Asegúrate que este modelo sea de texto, no solo embeddings
                "prompt": prompt,
                "stream": False
            }
        )
        respuesta_ia = response.json().get("response", "Error procesando respuesta")
    except Exception as e:
        respuesta_ia = f"Error conectando con Ollama: {str(e)}"

    return jsonify({"respuesta": respuesta_ia})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)