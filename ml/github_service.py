"""GitHub REST API integration for the hosted release-risk application.

This module intentionally does not start Docker or a GitHub MCP server, so it
can run on standard Python hosting platforms such as Render.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/github", tags=["GitHub"])
GITHUB_API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 10  # Bound request volume while allowing up to 1,000 records per list.


class GitHubPRRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=100)
    pull_number: int = Field(gt=0)


def _validate_repo_part(value: str, label: str) -> str:
    # Prevent path/query injection and reject malformed GitHub identifiers.
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise HTTPException(status_code=422, detail=f"Invalid GitHub {label}.")
    return value


async def _github_get(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> tuple[Any, httpx.Headers]:
    response = await client.get(f"{GITHUB_API}{path}", params=params)
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="GitHub repository or pull request was not found, or the token cannot access it.")
    if response.status_code == 401:
        raise HTTPException(status_code=502, detail="GitHub rejected the configured access token. Replace it in the hosting environment settings.")
    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")
        detail = "GitHub denied the request. Check token permissions and API rate limits."
        if remaining == "0":
            detail = "GitHub API rate limit reached. Please try again later."
        raise HTTPException(status_code=502, detail=detail)
    if response.is_error:
        logger.warning("GitHub API returned HTTP %s for %s", response.status_code, path)
        raise HTTPException(status_code=502, detail=f"GitHub API request failed (HTTP {response.status_code}).")
    try:
        return response.json(), response.headers
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub returned an unreadable response.") from exc


async def _get_paginated_list(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    base_params = dict(params or {})
    for page in range(1, MAX_PAGES + 1):
        page_params = {**base_params, "per_page": PER_PAGE, "page": page}
        data, _ = await _github_get(client, path, page_params)
        if isinstance(data, dict):
            # Actions API returns {total_count, workflow_runs}.
            items = data.get("workflow_runs", [])
        else:
            items = data
        if not isinstance(items, list):
            raise HTTPException(status_code=502, detail="GitHub returned an unexpected list response.")
        collected.extend(item for item in items if isinstance(item, dict))
        if len(items) < PER_PAGE:
            break
    return collected


def _module_from_path(filename: str) -> str | None:
    parts = filename.replace("\\", "/").strip("/").split("/")
    for root in ("src", "app", "services", "modules", "packages"):
        if root in parts:
            index = parts.index(root)
            if index + 1 < len(parts):
                return f"{root}/{parts[index + 1]}"
    return parts[0] if len(parts) > 1 else None


async def fetch_github_data(owner: str, repo: str, pull_number: int) -> dict[str, Any]:
    owner = _validate_repo_part(owner, "owner")
    repo = _validate_repo_part(repo, "repository name")
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="GitHub access token is not configured. Add GITHUB_PERSONAL_ACCESS_TOKEN in Render Environment settings.")

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "release-risk-analyzer",
    }
    timeout = httpx.Timeout(25.0, connect=10.0)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False) as client:
        root = f"/repos/{owner}/{repo}"
        pr, _ = await _github_get(client, f"{root}/pulls/{pull_number}")
        if not isinstance(pr, dict):
            raise HTTPException(status_code=502, detail="GitHub returned unexpected pull request data.")

        files = await _get_paginated_list(client, f"{root}/pulls/{pull_number}/files")
        modules = {_module_from_path(str(item.get("filename", ""))) for item in files}
        modules.discard(None)

        # Issues endpoint also returns pull requests; exclude those explicitly.
        issues = await _get_paginated_list(
            client,
            f"{root}/issues",
            {"state": "open", "labels": "bug"},
        )
        defects = [issue for issue in issues if "pull_request" not in issue and str(issue.get("state", "open")).lower() == "open"]

        base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
        base_branch = base.get("ref")
        workflow_params: dict[str, Any] = {"status": "completed"}
        if base_branch:
            workflow_params["branch"] = base_branch
        runs = await _get_paginated_list(client, f"{root}/actions/runs", workflow_params)
        failures = sum(1 for run in runs if str(run.get("conclusion", "")).lower() == "failure")

        labels = pr.get("labels") or []
        label_names = {
            (label.get("name", "") if isinstance(label, dict) else str(label)).strip().lower()
            for label in labels
        }
        criticality = next(
            (level for level in ("high", "medium", "low")
             if f"criticality:{level}" in label_names or f"priority:{level}" in label_names),
            "medium",
        )

        descriptions: list[str] = []
        if pr.get("title"):
            descriptions.append(f"Pull request: {pr['title']}")
        if pr.get("body"):
            descriptions.append(str(pr["body"]))
        for issue in defects:
            if issue.get("body"):
                descriptions.append(f"Issue #{issue.get('number')}: {issue['body']}")

        description = "\n\n".join(descriptions) or "No PR or defect description found; manual review needed."
        return {
            "changed_files": int(pr.get("changed_files", len(files))),
            "changed_lines": int(pr.get("additions", 0)) + int(pr.get("deletions", 0)),
            "affected_modules": len(modules),
            "open_defects": len(defects),
            "criticality": criticality,
            "recent_failures": failures,
            "defect_description": description[:5000],
        }


@router.post("/release-data")
async def get_release_data(payload: GitHubPRRequest):
    try:
        return await fetch_github_data(payload.owner, payload.repo, payload.pull_number)
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        logger.exception("GitHub API request timed out")
        raise HTTPException(status_code=504, detail="GitHub did not respond in time. Please try again.") from exc
    except Exception as exc:
        logger.exception("GitHub REST API request failed")
        raise HTTPException(status_code=502, detail=f"Unable to retrieve GitHub data ({type(exc).__name__}). Check the server logs.") from exc
