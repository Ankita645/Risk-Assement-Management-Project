# Local GitHub MCP version

The original Docker/MCP implementation from the uploaded project is preserved as
`ml/github_service_mcp.py`. The default `ml/github_service.py` is now the
Render-compatible GitHub REST API implementation.

To run the hosted-compatible version locally, use the current files and set
`GITHUB_PERSONAL_ACCESS_TOKEN` in `ml/.env`.

To switch the local app back to MCP for a demonstration:

1. Make sure Docker Desktop is running and the GitHub MCP container image can
   be pulled.
2. Back up `ml/github_service.py`.
3. Copy `ml/github_service_mcp.py` over `ml/github_service.py`.
4. Install the MCP dependency used by the original implementation: `pip install mcp`.
5. Ensure `GITHUB_PERSONAL_ACCESS_TOKEN` is set in `ml/.env`.
6. Start FastAPI from the `ml` directory with
   `python -m uvicorn api:app --reload --port 8000`.

Before deploying to Render, restore the REST version as `ml/github_service.py`.
Do not deploy the MCP version to the standard Render free Python service.
