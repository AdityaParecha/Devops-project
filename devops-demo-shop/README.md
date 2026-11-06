# DevOps Demo Shop

Small FastAPI + PostgreSQL application built specifically for the AI-DevOps project.

## Run
docker compose up -d --build

Open http://localhost:8000

## Endpoints
GET /api/health
GET /api/products
GET /api/orders
POST /api/orders
GET /api/stats
GET /metrics

## Controlled fault injection
GET /api/fault/slow?seconds=5
GET /api/fault/error
GET /api/fault/cpu?seconds=10
GET /api/fault/memory?mb=100

Container failures can be tested with:
docker stop devops-demo-app
docker restart devops-demo-app
docker stop devops-demo-postgres

Fault injection is enabled only for this controlled test environment.
