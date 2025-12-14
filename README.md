# IBHelm Service Agent

REST API for managing IBHelm Docker services and configuration.

## Features

- **Service Control**: Start, stop, restart containers
- **Service Updates**: Git pull + rebuild
- **Log Viewing**: Fetch recent container logs
- **Configuration Management**: Centralized config in PostgreSQL
- **JWT Auth**: Uses Supabase tokens, admin role required for mutations
- **Audit Logging**: All operations logged to database
- **Security Isolation**: Config stored in separate `service_agent` schema (not accessible via anon key)

## API Endpoints

### Public (No Auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/config/{service}` | Get config for a service (for containers) |

### Authenticated (Any User)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/services` | List all services and status |
| GET | `/services/{name}` | Get service status |
| GET | `/services/{name}/logs` | Get service logs |

### Admin Only

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/services/{name}/start` | Start service |
| POST | `/services/{name}/stop` | Stop service |
| POST | `/services/{name}/restart` | Restart service |
| POST | `/services/{name}/update` | Git pull + rebuild |
| GET | `/config` | List all config |
| POST | `/config` | Create/update config |
| DELETE | `/config/{key}` | Delete config |

## Setup

### 1. Enable service_agent Schema in Supabase

Edit your Supabase `config.toml` to expose the new schema:

```toml
[api]
# Add service_agent to the schemas list
schemas = ["public", "graphql_public", "service_agent"]
```

Then restart Supabase or just the REST container.

### 2. Apply Database Schema

```bash
cd ibhelmDB
./apply_schema.sh
```

This creates:
- `service_agent.configurations` - Config key-value store
- `service_agent.operation_logs` - Audit trail

### 3. Set Admin Role on Your User

```sql
UPDATE auth.users 
SET raw_app_metadata = COALESCE(raw_app_metadata, '{}'::jsonb) || '{"role": "admin"}'::jsonb
WHERE email = 'your@email.com';
```

### 4. Configure Environment

```bash
cp env.example .env
# Edit .env with your values:
# - SUPABASE_URL
# - SUPABASE_SERVICE_KEY (from Supabase dashboard)
# - SUPABASE_JWT_SECRET (from Supabase dashboard)
# - SERVICES_BASE_PATH (where your services are on the host)
```

### 5. Run with Docker Compose

```bash
docker compose up -d
```

## How Config Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Dashboard edits config via /config endpoints (requires admin JWT)       │
│                                                                              │
│ 2. Config stored in service_agent.configurations table                      │
│    (NOT accessible via anon key - separate schema with revoked public)     │
│                                                                              │
│ 3. Container starts, entrypoint.sh calls /config/{service_name}            │
│                                                                              │
│ 4. Agent returns all configs where service is in scope                      │
│                                                                              │
│ 5. entrypoint.sh exports as env vars, app starts                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Security Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ANON KEY (Dashboard)                                                         │
│ └─ Can access: public schema only                                           │
│ └─ Cannot access: service_agent schema (REVOKE ALL FROM PUBLIC)            │
│                                                                              │
│ SERVICE KEY (Service Agent)                                                  │
│ └─ Can access: all schemas including service_agent                          │
│ └─ Used by: service-agent only (not exposed to frontend)                   │
│                                                                              │
│ JWT with admin role                                                          │
│ └─ Required for: service control, config changes                           │
│ └─ Verified by: service-agent before any mutation                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase API URL |
| `SUPABASE_SERVICE_KEY` | Yes | Service role key (full access) |
| `SUPABASE_JWT_SECRET` | Yes | JWT secret for token verification |
| `SERVICES_BASE_PATH` | Yes | Path to IBHelm services on host |
| `HOST` | No | Listen address (default: 0.0.0.0) |
| `PORT` | No | Listen port (default: 8100) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |
| `BETTERSTACK_SOURCE_TOKEN` | No | Better Stack logging token |
| `BETTERSTACK_INGEST_HOST` | No | Better Stack host |
