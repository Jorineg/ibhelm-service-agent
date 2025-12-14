"""Configuration for Service Agent."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8100"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Logging
BETTERSTACK_SOURCE_TOKEN = os.getenv("BETTERSTACK_SOURCE_TOKEN")
BETTERSTACK_INGEST_HOST = os.getenv("BETTERSTACK_INGEST_HOST")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Docker - base path for services on host
SERVICES_BASE_PATH = os.getenv("SERVICES_BASE_PATH", "/root")

# Service definitions
# container_name: exact container name as shown by `docker ps`
# For multi_container services, we find by compose project label instead
SERVICES = {
    "teamworkmissiveconnector": {
        "dir": "TeamworkMissiveConnector",
        "compose": "docker-compose.yml",
        "container_name": "teamwork-missive-connector",
    },
    "thumbnailtextextractor": {
        "dir": "ThumbnailTextExtractor",
        "compose": "docker-compose.yml",
        "container_name": "thumbnail-text-extractor",
    },
    "mcp": {
        "dir": "ibhelm-mcp",
        "compose": "docker-compose.yml",
        "container_name": "ibhelm-mcp-server",
    },
    "supabase": {
        "dir": "supabase/docker",
        "compose": ["docker-compose.yml", "docker-compose.s3.yml"],
        "container_name": None,  # Multi-container, found by project label
        "multi_container": True,
    },
}

# Config categories (full names)
CONFIG_CATEGORIES = [
    "shared",
    "teamwork_api",
    "missive_api",
    "craft_api",
    "teamworkmissiveconnector",
    "thumbnailtextextractor",
    "mcp",
    "supabase",
]


def validate_config():
    errors = []
    if not SUPABASE_URL:
        errors.append("SUPABASE_URL is required")
    if not SUPABASE_SERVICE_KEY:
        errors.append("SUPABASE_SERVICE_KEY is required")
    if not SUPABASE_JWT_SECRET:
        errors.append("SUPABASE_JWT_SECRET is required")
    if errors:
        raise ValueError("Config errors:\n  " + "\n  ".join(errors))
