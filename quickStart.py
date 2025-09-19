import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from logging import INFO
from dotenv import load_dotenv
from flask import Blueprint,Flask, request, jsonify
from graphiti_core.utils.maintenance.graph_data_operations import clear_data
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from openai import OpenAI
 
# Allowed relationship types   
ALLOWED_RELATION_TYPES = {
    "does", "performs", "includes", "happens_on", "focuses_on", "practices"
}
 
# Logging config
logging.basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
 
# Load .env
load_dotenv()
neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
openai_api_key = os.getenv("OPENAI_API_KEY")
 
if not all([neo4j_uri, neo4j_user, neo4j_password, openai_api_key]):
    raise ValueError("Missing required environment variables.")
 
client = OpenAI(api_key=openai_api_key)
graphiti = Graphiti(neo4j_uri, neo4j_user, neo4j_password)
 
# -------------------------
# LLM extract function
# -------------------------
async def extract_structured_json(text: str) -> dict:
    prompt = f"""
You are an expert at extracting structured data for knowledge graph generation.
 
Given a short paragraph, extract:
- Specific entities (people, activities, days, exercises)
- Clear, action-based relationships between them
 
⚠️ DO NOT use generic relationships like "mentions", "related_to", or "associates_with".
✅ You MUST use only the following relationships:
  - "does"
  - "performs"
  - "includes"
  - "happens_on"
  - "focuses_on"
  - "practices"
 
If no valid relationship can be formed, do NOT include that edge.
 
Output JSON structure:
{{
  "nodes": [{{ "name": "<entity>" }}],
  "edges": [{{ "source": "<entity>", "target": "<entity>", "type": "<relationship>" }}]
}}
 
Now extract from the following paragraph:
 
{text}
"""
    completion = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
 
    response_text = completion.choices[0].message.content.strip()
    logger.info("LLM Response:\n%s", response_text)
 
    try:
        structured_data = json.loads(response_text)
 
        # Filter invalid relationships
        if "edges" in structured_data:
            structured_data["edges"] = [
                edge
                for edge in structured_data["edges"]
                if edge.get("type") in ALLOWED_RELATION_TYPES
            ]
        return structured_data
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM JSON: %s", e)
        return {}
 
# -------------------------
# Insert function
# -------------------------
async def insert_structured_graph(driver, structured_data: dict, episode_name: str):
    async with driver.session() as session:
        # Nodes
        for node in structured_data.get("nodes", []):
            name = node.get("name")
            if name:
                await session.run("MERGE (n:Entity {name: $name})", name=name)
                await session.run(
                    """
                    MATCH (e:Episode {name: $episode_name})
                    MATCH (n:Entity {name: $entity_name})
                    MERGE (e)-[:MENTIONS]->(n)
                    """,
                    episode_name=episode_name,
                    entity_name=name,
                )
 
        # Edges
        for edge in structured_data.get("edges", []):
            source = edge.get("source")
            target = edge.get("target")
            rel_type = edge.get("type")
            if rel_type not in ALLOWED_RELATION_TYPES:
                continue
            query = f"""
            MATCH (a:Entity {{name: $source}})
            MATCH (b:Entity {{name: $target}})
            MERGE (a)-[r:`{rel_type}`]->(b)
            """
            await session.run(query, source=source, target=target)
 
# -------------------------
# API setup
# -------------------------
quickstart_bp = Blueprint("QuickStart", __name__, url_prefix="/QuickStart")
 
# // -------- Single Pyload --------------- //
 
# @quickstart_bp.route("/add_episode", methods=["POST"])
# def add_episode():
#     """API to dynamically add episodes"""
#     data = request.json
#     name = data.get("name")
#     content = data.get("content")
#     description = data.get("description", "")
#     reference_time = data.get("reference_time")
 
#     if not name or not content:
#         return jsonify({"error": "name and content are required"}), 400
 
#     # Parse reference_time
#     ref_time = datetime.now(timezone.utc)
#     if reference_time:
#         try:
#             ref_time = datetime.fromisoformat(reference_time)
#         except Exception:
#             return jsonify({"error": "Invalid reference_time format. Use ISO 8601"}), 400
 
#     async def process():
#         try:
#             await graphiti.add_episode(
#                 name=name,
#                 episode_body=content,
#                 source=EpisodeType.text,
#                 source_description=description,
#                 reference_time=ref_time,
#             )
 
#             structured_json = await extract_structured_json(content)
#             if structured_json:
#                 await insert_structured_graph(graphiti.driver, structured_json, name)
 
#             return {"message": "Episode added successfully", "structured": structured_json}
#         except Exception as e:
#             logger.error("Error: %s", e)
#             return {"error": str(e)}
 
#     # Run async inside sync Flask
#     result = asyncio.run(process())
#     return jsonify(result)
 
# // ----------- * --------------
 
# // -------- Multiple Pyload --------------- //
 
@quickstart_bp.route("/AddEpisodes", methods=["POST"])
def add_episodes():
    """API to add multiple episodes"""
    episodes = request.json
 
    if not isinstance(episodes, list):
        return jsonify({"error": "Expected a list of episodes"}), 400
 
    async def process_all():
        results = []
 
        for ep in episodes:
            name = ep.get("name")
            content = ep.get("content")
            description = ep.get("description", "")
            reference_time = ep.get("reference_time")
 
            if not name or not content:
                results.append({"error": f"Missing name or content for one episode"})
                continue
 
            # Parse reference time
            ref_time = datetime.now(timezone.utc)
            if reference_time:
                try:
                    ref_time = datetime.fromisoformat(reference_time)
                except Exception:
                    results.append({"error": f"Invalid reference_time for episode: {name}"})
                    continue
 
            try:
                await graphiti.add_episode(
                    name=name,
                    episode_body=content,
                    source=EpisodeType.text,
                    source_description=description,
                    reference_time=ref_time,
                )
 
                structured_json = await extract_structured_json(content)
                if structured_json:
                    await insert_structured_graph(graphiti.driver, structured_json, name)
 
                results.append({
                    "name": name,
                    "message": "Episode added successfully",
                    "structured": structured_json
                })
            except Exception as e:
                logger.error("Error in episode '%s': %s", name, e)
                results.append({"name": name, "error": str(e)})
 
        return results
 
    result = asyncio.run(process_all())
    return jsonify(result)
 
 
 
 
@quickstart_bp.route("/Clear", methods=["POST"])
def clear():
    """Clear all graph data"""
    asyncio.run(clear_data(graphiti.driver))
    return jsonify({"message": "Graph cleared"})