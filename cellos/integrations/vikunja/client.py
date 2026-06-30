"""Minimal async Vikunja API client using the public REST API."""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from typing import Any


class VikunjaClient:
    """Small async wrapper around Vikunja's HTTP API.

    Uses ``urllib`` under ``asyncio.to_thread`` so the integration does not add a
    mandatory runtime dependency beyond the Python standard library.
    """

    def __init__(self, base_url: str, api_token: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    def _make_url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}{path}"
        if query:
            encoded = urllib.parse.urlencode(
                {k: v for k, v in query.items() if v is not None},
                doseq=True,
            )
            if encoded:
                url = f"{url}?{encoded}"
        return url

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            self._make_url(path, query=query),
            data=data,
            headers=headers,
            method=method.upper(),
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))

    async def get_projects(self) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(self._request, "GET", "/projects")
        return result or []

    async def get_project(self, project_id: str) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "GET", f"/projects/{project_id}")
        return result or {}

    async def list_project_views(self, project_id: str) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(self._request, "GET", f"/projects/{project_id}/views")
        return result or []

    async def get_project_view(self, project_id: str, view_id: str) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "GET", f"/projects/{project_id}/views/{view_id}")
        return result or {}

    async def delete_project_view(self, project_id: str, view_id: str) -> Any:
        return await asyncio.to_thread(self._request, "DELETE", f"/projects/{project_id}/views/{view_id}")

    async def get_buckets(self, project_id: str, view_id: str) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(
            self._request,
            "GET",
            f"/projects/{project_id}/views/{view_id}/buckets",
        )
        return result or []

    async def create_bucket(self, project_id: str, view_id: str, title: str) -> dict[str, Any]:
        result = await asyncio.to_thread(
            self._request,
            "PUT",
            f"/projects/{project_id}/views/{view_id}/buckets",
            {"title": title},
        )
        return result or {}

    async def update_bucket(self, project_id: str, view_id: str, bucket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(
            self._request,
            "POST",
            f"/projects/{project_id}/views/{view_id}/buckets/{bucket_id}",
            payload,
        )
        return result or {}

    async def delete_bucket(self, project_id: str, view_id: str, bucket_id: str) -> Any:
        return await asyncio.to_thread(
            self._request,
            "DELETE",
            f"/projects/{project_id}/views/{view_id}/buckets/{bucket_id}",
        )

    async def list_project_tasks(
        self,
        project_id: str,
        expand: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] | None = None
        if expand:
            query = {"expand": expand}
        result = await asyncio.to_thread(
            self._request,
            "GET",
            f"/projects/{project_id}/tasks",
            None,
            query,
        )
        return result or []

    async def create_task(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "PUT", f"/projects/{project_id}/tasks", payload)
        return result or {}

    async def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "POST", f"/tasks/{task_id}", payload)
        return result or {}

    async def delete_task(self, task_id: str) -> Any:
        return await asyncio.to_thread(self._request, "DELETE", f"/tasks/{task_id}")

    async def move_task_to_bucket(
        self,
        project_id: str,
        view_id: str,
        bucket_id: int,
        task_id: int,
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(
            self._request,
            "POST",
            f"/projects/{project_id}/views/{view_id}/buckets/{bucket_id}/tasks",
            {"task_id": task_id},
        )
        return result or {}

    async def get_task(self, task_id: str) -> dict[str, Any]:
        result = await asyncio.to_thread(self._request, "GET", f"/tasks/{task_id}")
        return result or {}

    async def get_task_comments(self, task_id: str) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(self._request, "GET", f"/tasks/{task_id}/comments")
        return result or []

    async def create_task_comment(self, task_id: str, comment_text: str) -> dict[str, Any]:
        result = await asyncio.to_thread(
            self._request,
            "PUT",
            f"/tasks/{task_id}/comments",
            {"comment": comment_text},
        )
        return result or {}

    async def get_labels(self) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(self._request, "GET", "/labels")
        return result or []

    async def create_label(self, title: str) -> dict[str, Any]:
        result = await asyncio.to_thread(
            self._request,
            "PUT",
            "/labels",
            {"title": title},
        )
        return result or {}
