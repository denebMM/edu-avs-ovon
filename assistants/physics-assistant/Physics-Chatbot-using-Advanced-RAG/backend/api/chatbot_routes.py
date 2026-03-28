from flask import Blueprint, request, jsonify
from services.response_generator import get_response

api_blueprint = Blueprint('api', __name__)

@api_blueprint.route('/generate', methods=['POST'])
def generate():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data received"}), 400
    
    response = get_response(data)
    return jsonify(response)