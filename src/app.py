"""IBHelm Service Agent - Container and config management API."""
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import settings
from .logging_conf import setup_logging
from .auth import get_current_user, require_admin
from . import docker_manager as docker
from . import config_manager as config

logger = logging.getLogger(__name__)


def mask_secret(value: str) -> str:
    """Mask a secret value, showing only last 3 characters."""
    if not value or len(value) <= 3:
        return "••••••"
    return f"••••••{value[-3:]}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    setup_logging()
    settings.validate_config()
    logger.info("Service Agent starting on port %s", settings.PORT)
    yield
    logger.info("Service Agent stopped")


app = FastAPI(
    title="IBHelm Service Agent",
    description="Container and configuration management for IBHelm services",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health & Status
# =============================================================================

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/services")
async def list_services(user: dict = Depends(get_current_user)):
    """List all services and their status."""
    statuses = docker.get_all_service_statuses()
    return {
        "services": [
            {
                "name": s.name,
                "status": s.status,
                "total_memory_mb": s.total_memory_mb,
                "error": s.error,
                "containers": [asdict(c) for c in s.containers],
            }
            for s in statuses
        ]
    }


@app.get("/services/{name}")
async def get_service(name: str, user: dict = Depends(get_current_user)):
    """Get status of a specific service."""
    if name not in settings.SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    
    s = docker.get_service_status(name)
    return {
        "name": s.name,
        "status": s.status,
        "total_memory_mb": s.total_memory_mb,
        "error": s.error,
        "containers": [asdict(c) for c in s.containers],
    }


@app.get("/services/{name}/logs")
async def get_logs(
    name: str,
    lines: int = Query(100, ge=1, le=1000),
    container: str = Query(None, description="Container name for multi-container services"),
    user: dict = Depends(get_current_user),
):
    """Get recent logs from a service."""
    if name not in settings.SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    return {"logs": docker.get_container_logs(name, lines, container)}


# =============================================================================
# Service Control (Admin only)
# =============================================================================

class OperationResult(BaseModel):
    success: bool
    message: str


@app.post("/services/{name}/start", response_model=OperationResult)
async def start_service(name: str, user: dict = Depends(require_admin)):
    """Start a service."""
    if name not in settings.SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    
    logger.info("Starting service %s (by %s)", name, user.get("email"))
    
    env_config = await config.get_config_for_service(name)
    success, output = await docker.start_service(name, env=env_config)
    
    await config.log_operation(name, "start", success, output, user.get("sub"), user.get("email"))
    
    return OperationResult(success=success, message=output)


@app.post("/services/{name}/stop", response_model=OperationResult)
async def stop_service(name: str, user: dict = Depends(require_admin)):
    """Stop a service."""
    if name not in settings.SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    
    logger.info("Stopping service %s (by %s)", name, user.get("email"))
    
    success, output = await docker.stop_service(name)
    
    await config.log_operation(name, "stop", success, output, user.get("sub"), user.get("email"))
    
    return OperationResult(success=success, message=output)


@app.post("/services/{name}/restart", response_model=OperationResult)
async def restart_service(name: str, user: dict = Depends(require_admin)):
    """Restart a service."""
    if name not in settings.SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    
    logger.info("Restarting service %s (by %s)", name, user.get("email"))
    
    env_config = await config.get_config_for_service(name)
    success, output = await docker.restart_service(name, env=env_config)
    
    await config.log_operation(name, "restart", success, output, user.get("sub"), user.get("email"))
    
    return OperationResult(success=success, message=output)


@app.post("/services/{name}/update", response_model=OperationResult)
async def update_service(name: str, user: dict = Depends(require_admin)):
    """Git pull and rebuild a service."""
    if name not in settings.SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    
    logger.info("Updating service %s (by %s)", name, user.get("email"))
    
    success, output = await docker.update_service(name)
    
    await config.log_operation(name, "update", success, output, user.get("sub"), user.get("email"))
    
    return OperationResult(success=success, message=output)


# =============================================================================
# Configuration (for containers to fetch on startup)
# =============================================================================

@app.get("/config/{service_name}")
async def get_config_for_service(service_name: str):
    """
    Get configuration for a service.
    Called by containers on startup via entrypoint.sh.
    No auth required (internal network only).
    """
    return await config.get_config_for_service(service_name)


# =============================================================================
# Configuration Management (Admin only)
# =============================================================================

@app.get("/config")
async def list_all_config(user: dict = Depends(require_admin)):
    """List all configuration entries."""
    configs = await config.get_all_config()
    
    # Mask secrets - show only last 3 chars
    for c in configs:
        if c.get("is_secret"):
            c["value"] = mask_secret(c.get("value", ""))
    
    return {"configurations": configs}


class ConfigCreate(BaseModel):
    key: str
    value: str
    scope: list[str]
    is_secret: bool = False
    category: str = None
    description: str = None


class ConfigUpdate(BaseModel):
    """For updates, value is optional (only update if provided)."""
    value: str = None
    scope: list[str] = None
    is_secret: bool = None
    category: str = None
    description: str = None


@app.post("/config")
async def create_config(
    data: ConfigCreate,
    user: dict = Depends(require_admin),
):
    """Create a new configuration entry."""
    user_id = user.get("sub")
    
    logger.info("Config create: %s (by %s)", data.key, user.get("email"))
    
    result = await config.upsert_config(
        key=data.key,
        value=data.value,
        scope=data.scope,
        is_secret=data.is_secret,
        category=data.category,
        description=data.description,
        user_id=user_id,
    )
    
    if result.get("is_secret"):
        result["value"] = mask_secret(result.get("value", ""))
    
    await config.log_operation(
        "config", "create", True,
        f"Created config: {data.key}",
        user_id, user.get("email")
    )
    
    return result


@app.put("/config/{key}")
async def update_config(
    key: str,
    data: ConfigUpdate,
    user: dict = Depends(require_admin),
):
    """Update an existing configuration entry."""
    user_id = user.get("sub")
    
    # Get existing config
    existing = await config.get_config_by_key(key)
    if not existing:
        raise HTTPException(404, f"Config not found: {key}")
    
    # Merge updates
    updated_value = data.value if data.value is not None else existing["value"]
    updated_scope = data.scope if data.scope is not None else existing["scope"]
    updated_is_secret = data.is_secret if data.is_secret is not None else existing["is_secret"]
    updated_category = data.category if data.category is not None else existing.get("category")
    updated_description = data.description if data.description is not None else existing.get("description")
    
    logger.info("Config update: %s (by %s)", key, user.get("email"))
    
    result = await config.upsert_config(
        key=key,
        value=updated_value,
        scope=updated_scope,
        is_secret=updated_is_secret,
        category=updated_category,
        description=updated_description,
        user_id=user_id,
    )
    
    if result.get("is_secret"):
        result["value"] = mask_secret(result.get("value", ""))
    
    await config.log_operation(
        "config", "update", True,
        f"Updated config: {key}",
        user_id, user.get("email")
    )
    
    return result


@app.delete("/config/{key}")
async def delete_config(key: str, user: dict = Depends(require_admin)):
    """Delete a configuration entry."""
    user_id = user.get("sub")
    
    logger.info("Config delete: %s (by %s)", key, user.get("email"))
    
    await config.delete_config(key)
    
    await config.log_operation(
        "config", "delete", True,
        f"Deleted config: {key}",
        user_id, user.get("email")
    )
    
    return {"deleted": key}


# =============================================================================
# Categories
# =============================================================================

@app.get("/config/categories")
async def list_categories(user: dict = Depends(require_admin)):
    """List available config categories."""
    return {"categories": settings.CONFIG_CATEGORIES}


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
