from flask import Blueprint,Flask, jsonify

grafity_bp = Blueprint("Grafity", __name__, url_prefix="/Grafity")

# A simple GET API endpoint
@grafity_bp.route("/Hello", methods=["GET"])
def hello_world():
    return jsonify({"message": "Hello, World!"})