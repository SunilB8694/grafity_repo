from flask import Flask
from flask_cors import CORS
from flasgger import Swagger
import secrets
import os
 
from grafityMain import grafitymain_bp
from quickStart import quickstart_bp
from grafityGet import grafity_bp
# from grafitymain_routes import grafitymain_bp
# from quickstart_routes import quickstart_bp
 
# from ocr import ocr_bp
 
SECRET_KEY = secrets.token_urlsafe(32)
 
app = Flask(__name__)
swagger = Swagger(app)
CORS(app, origins=["http://localhost:4200"])
 
# app.config["SECRET_KEY"] = os.urandom(24)
# app.config["REFRESH_SECRET_KEY"] = os.urandom(24)
 
# Register Blueprints

app.register_blueprint(grafity_bp)
app.register_blueprint(grafitymain_bp)
app.register_blueprint(quickstart_bp)
 
if __name__ == "__main__":
    app.run(debug=True)
 