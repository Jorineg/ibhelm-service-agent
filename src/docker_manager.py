"""Docker container management."""
import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import docker
from docker.errors import NotFound, APIError

from . import settings


@dataclass
class ContainerStatus:
    """Status of a single container."""
    name: str
    status: str  # running, exited, paused, restarting, not_found, error
    container_id: Optional[str] = None
    image: Optional[str] = None
    started_at: Optional[str] = None
    health_status: Optional[str] = None
    exit_code: Optional[int] = None
    restart_count: int = 0
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    memory_limit_mb: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ServiceStatus:
    """Status of a service (may have multiple containers)."""
    name: str
    status: str  # running, partial, stopped, not_found, error
    containers: list[ContainerStatus] = field(default_factory=list)
    # Aggregated stats
    total_memory_mb: Optional[float] = None
    error: Optional[str] = None


def get_docker_client():
    """Get Docker client."""
    return docker.from_env()


def get_service_config(service_name: str) -> dict:
    """Get service configuration."""
    config = settings.SERVICES.get(service_name)
    if not config:
        raise ValueError(f"Unknown service: {service_name}")
    return config


def get_service_path(service_name: str) -> Path:
    """Get path to service directory."""
    config = get_service_config(service_name)
    return Path(settings.SERVICES_BASE_PATH) / config["dir"]


def get_container_status(container) -> ContainerStatus:
    """Get detailed status from a container object."""
    attrs = container.attrs
    state = attrs.get("State", {})
    
    status = ContainerStatus(
        name=container.name,
        status=container.status,
        container_id=container.short_id,
        image=container.image.tags[0] if container.image.tags else str(container.image.id)[:12],
        started_at=state.get("StartedAt"),
        exit_code=state.get("ExitCode"),
        restart_count=attrs.get("RestartCount", 0),
    )
    
    # Health check status
    health = state.get("Health", {})
    if health:
        status.health_status = health.get("Status")
    
    # Resource usage (only for running containers)
    if container.status == "running":
        try:
            stats = container.stats(stream=False)
            
            cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                       stats["precpu_stats"]["cpu_usage"]["total_usage"]
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                          stats["precpu_stats"]["system_cpu_usage"]
            num_cpus = stats["cpu_stats"].get("online_cpus", 1)
            
            if system_delta > 0:
                status.cpu_percent = round((cpu_delta / system_delta) * num_cpus * 100, 2)
            
            memory_stats = stats.get("memory_stats", {})
            if memory_stats.get("usage"):
                status.memory_mb = round(memory_stats["usage"] / (1024 * 1024), 1)
            if memory_stats.get("limit"):
                status.memory_limit_mb = round(memory_stats["limit"] / (1024 * 1024), 1)
        except Exception:
            pass
    
    return status


def get_service_status(service_name: str) -> ServiceStatus:
    """Get status of a service (handles multi-container services)."""
    client = get_docker_client()
    config = get_service_config(service_name)
    
    is_multi = config.get("multi_container", False)
    
    if is_multi:
        # Find all containers for this service (by compose project name)
        project_name = service_name
        containers = client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={project_name}"}
        )
        
        if not containers:
            return ServiceStatus(name=service_name, status="not_found")
        
        container_statuses = [get_container_status(c) for c in containers]
        
        # Determine overall status
        running_count = sum(1 for c in container_statuses if c.status == "running")
        total_count = len(container_statuses)
        
        if running_count == total_count:
            overall_status = "running"
        elif running_count == 0:
            overall_status = "stopped"
        else:
            overall_status = "partial"
        
        # Aggregate memory
        total_memory = sum(c.memory_mb or 0 for c in container_statuses)
        
        return ServiceStatus(
            name=service_name,
            status=overall_status,
            containers=container_statuses,
            total_memory_mb=round(total_memory, 1) if total_memory else None,
        )
    else:
        # Single container service
        container_suffix = config.get("container_suffix", "app-1")
        # Docker Compose lowercases project names
        dir_name = config["dir"].replace("/", "-").lower()
        container_name = f"{dir_name}-{container_suffix}"
        
        try:
            container = client.containers.get(container_name)
            container_status = get_container_status(container)
            
            return ServiceStatus(
                name=service_name,
                status=container_status.status,
                containers=[container_status],
                total_memory_mb=container_status.memory_mb,
            )
        except NotFound:
            return ServiceStatus(name=service_name, status="not_found")
        except APIError as e:
            return ServiceStatus(name=service_name, status="error", error=str(e))


def get_all_service_statuses() -> list[ServiceStatus]:
    """Get status of all known services."""
    return [get_service_status(name) for name in settings.SERVICES]


async def run_compose_command(
    service_name: str,
    command: list[str],
    env: dict = None,
) -> tuple[bool, str, str]:
    """Run a docker-compose command for a service."""
    service_path = get_service_path(service_name)
    
    if not service_path.exists():
        return False, "", f"Service path not found: {service_path}"
    
    config = get_service_config(service_name)
    compose_files = config.get("compose", "docker-compose.yml")
    
    # Build command with one or more -f flags
    full_command = ["docker", "compose"]
    if isinstance(compose_files, list):
        for f in compose_files:
            full_command.extend(["-f", f])
    else:
        full_command.extend(["-f", compose_files])
    full_command.extend(command)
    
    # Merge provided env with current environment
    import os
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    
    proc = await asyncio.create_subprocess_exec(
        *full_command,
        cwd=str(service_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=run_env,
    )
    
    stdout, stderr = await proc.communicate()
    success = proc.returncode == 0
    
    return success, stdout.decode(), stderr.decode()


async def start_service(service_name: str, env: dict = None) -> tuple[bool, str]:
    """Start a service."""
    success, stdout, stderr = await run_compose_command(
        service_name,
        ["up", "-d"],
        env=env,
    )
    return success, stdout + stderr


async def stop_service(service_name: str) -> tuple[bool, str]:
    """Stop a service."""
    success, stdout, stderr = await run_compose_command(
        service_name,
        ["down"],
    )
    return success, stdout + stderr


async def restart_service(service_name: str, env: dict = None) -> tuple[bool, str]:
    """Restart a service."""
    success, stdout, stderr = await run_compose_command(
        service_name,
        ["up", "-d", "--force-recreate"],
        env=env,
    )
    return success, stdout + stderr


async def update_service(service_name: str) -> tuple[bool, str]:
    """Git pull and rebuild a service."""
    service_path = get_service_path(service_name)
    
    # Git pull
    proc = await asyncio.create_subprocess_exec(
        "git", "pull",
        cwd=str(service_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        return False, f"Git pull failed: {stderr.decode()}"
    
    git_output = stdout.decode()
    
    # Rebuild and restart
    success, stdout, stderr = await run_compose_command(
        service_name,
        ["up", "-d", "--build", "--force-recreate"],
    )
    
    return success, f"Git: {git_output}\nCompose: {stdout + stderr}"


def get_container_logs(service_name: str, lines: int = 100, container_name: str = None) -> str:
    """Get recent logs from a container."""
    client = get_docker_client()
    config = get_service_config(service_name)
    
    if container_name:
        # Specific container requested
        target_name = container_name
    elif config.get("multi_container"):
        # For multi-container, return logs from all (or require specific container)
        return "Multi-container service. Specify container_name parameter."
    else:
        # Single container - Docker Compose lowercases project names
        container_suffix = config.get("container_suffix", "app-1")
        dir_name = config["dir"].replace("/", "-").lower()
        target_name = f"{dir_name}-{container_suffix}"
    
    try:
        container = client.containers.get(target_name)
        return container.logs(tail=lines, timestamps=True).decode()
    except NotFound:
        return f"Container not found: {target_name}"
    except APIError as e:
        return f"Error getting logs: {e}"
