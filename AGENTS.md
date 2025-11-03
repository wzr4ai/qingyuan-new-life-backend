# Repository Guidelines

This guide helps contributors work efficiently on the Qingyuan New Life backend. Keep each change small and aligned with the FastAPI architecture already in place.

## Project Structure & Module Organization

Application code lives in `src/`. `src/main.py` wires routers and middleware. Feature modules stay under `src/modules/*` (e.g., `auth`, `admin`, `schedule`, `ai-plan`) so every feature remains self-contained. Cross-cutting configuration and database helpers reside in `src/core/`, while reusable models and dependency utilities sit in `src/shared/`. SQLAlchemy migrations live in `alembic/versions`; create a new revision for each schema change.

## Build, Test, and Development Commands

Use `uv` for dependency management—`uv.lock` keeps versions reproducible. Typical workflow:
```bash
uv sync
uv run uvicorn src.main:app --reload --port 8002
uv run alembic upgrade head
uv run pytest
```
Add `.env` files locally to satisfy required settings before starting the server.

## Coding Style & Naming Conventions

Target Python 3.13 and follow PEP 8 with 4-space indentation, snake_case modules, and descriptive function names. Type hints are expected for request/response models. Keep router registrations in `src/main.py` and expose endpoints via `APIRouter` instances in `src/modules/<feature>/router.py`. Avoid hard-coding secrets or URLs; read them via `Settings` in `src/core/config.py`.

## Testing Guidelines

Prefer `pytest` with async-friendly fixtures for FastAPI endpoints. Place tests under `tests/` mirroring the module structure (e.g., `tests/modules/test_admin.py`) and name files `test_*.py`. Cover success and failure paths for new endpoints, and add regression tests when touching scheduling or authentication flows. Run `uv run pytest` before opening a pull request.

## Commit & Pull Request Guidelines

The current history only includes an `Initial commit`; adopt Conventional Commit prefixes (`feat:`, `fix:`, `chore:`) to keep future history scannable. Each commit should focus on one logical change and include migrations or tests when relevant. Pull requests must summarise the change, reference related issues, call out schema or configuration updates, and attach screenshots or sample responses for user-facing adjustments. Confirm `uv run pytest` and required migration commands succeed before requesting review.

## Configuration & Security Tips

`src/core/config.py` loads secrets from environment variables or a local `.env`. Never commit real credentials, COS tokens, or admin OpenIDs. When adding new settings, document defaults and validation, and update deployment instructions accordingly. Sanitize logs that might expose access tokens or personally identifiable information.
