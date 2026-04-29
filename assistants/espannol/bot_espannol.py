from flask import Flask, request, jsonify
import PyPDF2
import requests

app = Flask(__name__)

# 📘 CARGAR PDF
def cargar_pdf(nombre):
    texto = ""
    try:
        with open(nombre, "rb") as f:
            lector = PyPDF2.PdfReader(f)
            for pagina in lector.pages:
                contenido = pagina.extract_text()
                if contenido:
                    texto += contenido + "\n"
    except Exception as e:
        print(f"Error al cargar PDF: {e}")
    return texto

# 🔎 RETRIEVAL
def recuperar_contexto(pregunta, texto):
    palabras = pregunta.lower().split()
    fragmentos = []
    for linea in texto.split("\n"):
        if any(p in linea.lower() for p in palabras):
            fragmentos.append(linea.strip())
    return "\n".join(fragmentos[:8])

# 🤖 GENERACIÓN CON OLLAMA
def generar_con_ollama(pregunta, contexto):
    prompt = f"""
Eres un profesor experto en Lengua Española y Literatura.
Usa este contexto del libro:
{contexto}

Pregunta:
{pregunta}
Responde de forma clara y educativa.
"""
    try:
        response = requests.post(
            "http://ollama:11434/api/generate", # DNS de Docker
            json={
                "model": "llama3.1",
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        return response.json()["response"]
    except Exception as e:
        return f"Error de conexión con Ollama: {e}"

# 🚀 INICIO
print("📘 Cargando libro de Español...")
LIBRO_DATA = cargar_pdf("espannol.pdf")
print("✅ Libro listo")

@app.route('/preguntar', methods=['POST'])
def preguntar():
    data = request.json
    pregunta = data.get("pregunta", "")
    contexto = recuperar_contexto(pregunta, LIBRO_DATA)
    respuesta = generar_con_ollama(pregunta, contexto)
    return jsonify({"respuesta": respuesta})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)