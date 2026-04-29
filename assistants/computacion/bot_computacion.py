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
        print(f"❌ Error al cargar el PDF: {e}")
    return texto

# 🔎 RETRIEVAL (búsqueda simple)
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
Eres un profesor experto en computacion.
Usa este contexto del libro:
{contexto}

Pregunta:
{pregunta}

Responde de forma clara y educativa.
"""
    # CAMBIO: Se usa 'ollama' como host para la red de Docker
    try:
        response = requests.post(
            "http://ollama:11434/api/generate",
            json={
                "model": "llama3.1",
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        return response.json()["response"]
    except Exception as e:
        return f"Error conectando con Ollama: {str(e)}"

# 🚀 CARGA INICIAL DEL LIBRO
print("📘 Cargando libro de computación...")
LIBRO_DATA = cargar_pdf("computacion.pdf")
print("✅ Libro cargado correctamente")

# 🌐 ENDPOINT PARA EL WRAPPER
@app.route('/preguntar', methods=['POST'])
def preguntar():
    datos = request.json
    pregunta_usuario = datos.get("pregunta", "")
    
    if not pregunta_usuario:
        return jsonify({"error": "No se recibió ninguna pregunta"}), 400

    # 1. Buscar en el PDF
    contexto = recuperar_contexto(pregunta_usuario, LIBRO_DATA)
    
    # 2. Generar respuesta con IA
    respuesta_ia = generar_con_ollama(pregunta_usuario, contexto)
    
    # 3. Responder en formato JSON
    return jsonify({
        "respuesta": respuesta_ia,
        "status": "success"
    })

if __name__ == '__main__':
    # El host '0.0.0.0' permite conexiones externas dentro de Docker
    app.run(host='0.0.0.0', port=5000)