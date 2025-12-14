"""Configuration management via Supabase REST API."""
import httpx
from . import settings

# Schema where our tables live
SCHEMA = "service_agent"


def _headers(prefer: str = "return=representation") -> dict:
    """Get headers for Supabase REST API with service_agent schema."""
    return {
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Accept-Profile": SCHEMA,  # Read from service_agent schema
        "Content-Profile": SCHEMA,  # Write to service_agent schema
        "Prefer": prefer,
    }


def _url(table: str) -> str:
    return f"{settings.SUPABASE_URL}/rest/v1/{table}"


async def get_config_for_service(service_name: str) -> dict:
    """
    Get configuration for a service.
    Returns dict of key -> value for all configs where service is in scope.
    """
    async with httpx.AsyncClient() as client:
        # Use PostgREST array contains operator
        resp = await client.get(
            _url("configurations"),
            headers=_headers(),
            params={
                "select": "key,value",
                "or": f"(scope.cs.{{{service_name}}},scope.cs.{{*}})",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
    
    return {row["key"]: row["value"] for row in rows}


async def get_all_config() -> list[dict]:
    """Get all configuration entries."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _url("configurations"),
            headers=_headers(),
            params={
                "select": "id,key,value,is_secret,scope,category,description,updated_at",
                "order": "category,key",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_config_by_key(key: str) -> dict | None:
    """Get a single configuration entry by key."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _url("configurations"),
            headers=_headers(),
            params={
                "select": "id,key,value,is_secret,scope,category,description,updated_at",
                "key": f"eq.{key}",
            },
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None


async def upsert_config(
    key: str,
    value: str,
    scope: list[str],
    is_secret: bool = False,
    category: str = None,
    description: str = None,
    user_id: str = None,
) -> dict:
    """Create or update a configuration entry."""
    data = {
        "key": key,
        "value": value,
        "scope": scope,
        "is_secret": is_secret,
        "category": category,
        "description": description,
        "updated_by": user_id,
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _url("configurations"),
            headers=_headers("resolution=merge-duplicates,return=representation"),
            json=data,
        )
        resp.raise_for_status()
        result = resp.json()
        return result[0] if result else data


async def delete_config(key: str) -> bool:
    """Delete a configuration entry."""
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            _url("configurations"),
            headers=_headers(),
            params={"key": f"eq.{key}"},
        )
        resp.raise_for_status()
        return True


async def log_operation(
    service_name: str,
    operation: str,
    success: bool,
    message: str = None,
    user_id: str = None,
    user_email: str = None,
):
    """Log a service operation for audit trail."""
    data = {
        "service_name": service_name,
        "operation": operation,
        "success": success,
        "message": message[:1000] if message else None,  # Truncate long messages
        "performed_by": user_id,
        "performed_by_email": user_email,
    }
    
    async with httpx.AsyncClient() as client:
        await client.post(
            _url("operation_logs"),
            headers=_headers(),
            json=data,
        )
