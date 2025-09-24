from flask import Blueprint,Flask, request, jsonify
from dataclasses import dataclass
from neo4j import GraphDatabase
from pydantic import BaseModel
from typing import List, Optional
import logging
import os
import uuid
import getpass
import traceback
import asyncio
 
from dotenv import load_dotenv
from pydantic_ai import Agent, RunContext
# from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
 
# Load environment variables
load_dotenv()
 
# Neo4j + OpenAI credentials
uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")
api_key = os.getenv('OPENAI_API_KEY')
 
# Logging setup
logger = logging.getLogger("flask.app")
logging.basicConfig(level=logging.DEBUG)
 
# Flask app
# app = Flask(__name__)
grafitymain_bp = Blueprint("GrafityMain", __name__, url_prefix="/GrafityMain")
 
# Dataclass for Graphiti dependencies
@dataclass
class GraphitiDependencies:
    graphiti_client: Graphiti
 
# Get OpenAI model
def get_model():
    model_choice = os.getenv('MODEL_CHOICE', 'gpt-4.1-mini')
    return OpenAIModel(model_choice, provider=OpenAIProvider(api_key=api_key))
 
# Pydantic-AI agent
graphiti_agent = Agent(
    get_model(),
    system_prompt="You are a helpful assistant with access to a knowledge graph filled with temporal data about LLMs.",
    deps_type=GraphitiDependencies
)
 
# Result model
class GraphitiSearchResult(BaseModel):
    uuid: str
    fact: str
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    source_node_uuid: Optional[str] = None
 
# Search request schema
class SearchRequest(BaseModel):
    query: str
 
# Add episode request schema
class EpisodeRequest(BaseModel):
    name: str
    content: str
    type: str  # "text" or "json"
    description: str
 
# Hardcoded model & usage for RunContext
model = "default-model"
usage = {
    "user": getpass.getuser(),
    "request_id": str(uuid.uuid4())
}
 
# Search tool registered with agent
@graphiti_agent.tool
async def search_graphiti(ctx: RunContext[GraphitiDependencies], query: str) -> List[GraphitiSearchResult]:
    graphiti = ctx.deps.graphiti_client
    try:
        logger.info(f"Performing search with query: {query}")
        results = await graphiti.search(query)
        logger.info(f"Search returned {len(results)} results")
 
        formatted_results = []
        for result in results:
            logger.debug(f"Processing result: {result}")
            formatted_result = GraphitiSearchResult(
                uuid=result.uuid,
                fact=result.fact,
                source_node_uuid=getattr(result, 'source_node_uuid', None),
                valid_at=str(getattr(result, 'valid_at', None)) if getattr(result, 'valid_at', None) else None,
                invalid_at=str(getattr(result, 'invalid_at', None)) if getattr(result, 'invalid_at', None) else None
            )
            formatted_results.append(formatted_result)
 
        return formatted_results
 
    except Exception as e:
        logger.error(f"Error searching Graphiti: {str(e)}", exc_info=True)
        raise Exception(f"Graphiti search failed: {e}")
 
# Async function to insert episode
async def add_episode_to_graphiti(graphiti: Graphiti, episode: EpisodeRequest):
    try:
        episode_type = EpisodeType[episode.type.lower()]
    except KeyError:
        raise ValueError(f"Invalid episode type: {episode.type}. Must be one of {[e.name for e in EpisodeType]}")
 
    from datetime import datetime, timezone
    await graphiti.add_episode(
        name=episode.name,
        episode_body=episode.content,
        source=episode_type,
        source_description=episode.description,
        reference_time=datetime.now(timezone.utc)
    )
 
# API endpoint: Search
@grafitymain_bp.route("/Search", methods=["POST"])
def search_graphiti_api():
    try:
        request_data = request.get_json()
        logger.info(f"Search request data: {request_data}")

        search_request = SearchRequest(**request_data)
        graphiti_client = Graphiti(uri, user, password)
        deps = GraphitiDependencies(graphiti_client=graphiti_client)
        ctx = RunContext(deps=deps, model=model, usage=usage)

        # Run async search inside sync endpoint
        search_results = asyncio.run(search_graphiti(ctx, search_request.query))
        return jsonify([result.dict() for result in search_results])

    except Exception as e:
        logger.error(f"Error handling search request: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"detail": "An error occurred while processing the request"}), 500

 