"""Vikunja provider implementing the generic integration contract."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from cellos.config import CellosConfig
from cellos.db import CellosDatabase
from cellos.env import env_has, get_required_env
from cellos.integrations.base import IntegrationProvider, IntegrationStatus, SetupResult, SyncDelta
from cellos.models import AgentRole, CommentAuthorType, Task, TaskStatus

from .client import VikunjaClient


_REQUIRED_ROLE_LABELS = ("architect", "engineer")
_DEFAULT_BUCKET_TITLES = ("To-Do", "Doing", "Done")


class VikunjaProvider(IntegrationProvider):
    """Generic CelloS connector for Vikunja projects/tasks."""

    PROVIDER_NAME = "vikunja"
    PROVIDER_DESCRIPTION = "Vikunja project/task sync"

    def __init__(self, config: CellosConfig | None = None, _config_dir: str | None = None, **kwargs: Any) -> None:
        self.config = config or CellosConfig()
        self._config_dir = _config_dir
        self._kwargs = kwargs
        self._db: CellosDatabase | None = kwargs.get("_db")

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def provider_description(self) -> str:
        return self.PROVIDER_DESCRIPTION

    def _provider_config(self):
        return self.config.integrations.get_provider(self.provider_name)

    def _project_id(self) -> str | None:
        value = getattr(self._provider_config(), "project_id", None)
        return str(value) if value is not None else None

    def _view_id(self) -> str | None:
        value = getattr(self._provider_config(), "view_id", None)
        return str(value) if value is not None else None

    def _bucket_map(self) -> dict[str, str]:
        raw = getattr(self._provider_config(), "bucket_map", None) or {}
        return {str(k): str(v) for k, v in raw.items()}

    def _credentials_configured(self) -> bool:
        return env_has("VIKUNJA_BASE_URL") and env_has("VIKUNJA_API_TOKEN")

    def _build_client(self) -> VikunjaClient:
        return VikunjaClient(
            base_url=get_required_env("VIKUNJA_BASE_URL", "Set it in the environment or .env file."),
            api_token=get_required_env("VIKUNJA_API_TOKEN", "Create an API token in Vikunja and export it."),
        )

    async def is_configured(self) -> bool:
        return bool(self._project_id())

    async def setup(self, clean: bool = False) -> SetupResult:
        project_id = self._project_id()
        view_id = self._view_id()
        if not project_id:
            raise ValueError("Vikunja provider requires integrations.vikunja.project_id in config.")
        if not view_id:
            raise ValueError("Vikunja provider requires integrations.vikunja.view_id in config.")

        client = self._build_client()
        project = await client.get_project(project_id)
        if hasattr(client, "get_project_view"):
            await client.get_project_view(project_id, view_id)

        cleanup_details = {
            "cleaned": False,
            "deleted_tasks": 0,
            "deleted_views": [],
            "deleted_buckets": [],
        }
        if clean:
            cleanup_details = await self._clean_project_state(client, project_id, view_id)

        existing_labels = await client.get_labels()
        created_labels = await self._ensure_required_labels(client, existing_labels)
        buckets, created_buckets = await self._ensure_default_buckets(client, project_id, view_id, reset=clean)
        mappings = {_normalize_bucket_name(bucket): str(bucket["id"]) for bucket in buckets if bucket.get("id") is not None}
        self._set_bucket_map(mappings)
        return SetupResult(
            target_id=str(project_id),
            mappings=mappings,
            details={
                "project_title": project.get("title") or project.get("name") or "",
                "view_id": str(view_id),
                "bucket_count": len(buckets),
                "required_labels": list(_REQUIRED_ROLE_LABELS),
                "created_labels": created_labels,
                "created_buckets": created_buckets,
                **cleanup_details,
            },
        )

    async def status(self) -> IntegrationStatus:
        project_id = self._project_id()
        view_id = self._view_id()
        bucket_map = self._bucket_map()
        return IntegrationStatus(
            provider_name=self.provider_name,
            configured=bool(project_id),
            credentials_configured=self._credentials_configured(),
            board_or_target=project_id,
            details={
                "view_id": view_id,
                "list_mapping": bucket_map,
            },
        )

    async def sync(self, push: bool = True, pull: bool = True) -> SyncDelta:
        delta = SyncDelta()
        if push:
            await self._sync_push(delta)
        if pull:
            await self._sync_pull(delta)
        return delta

    async def _sync_push(self, delta: SyncDelta) -> None:
        if self._db is None:
            return
        project_id = self._project_id()
        view_id = self._view_id()
        if not project_id:
            raise ValueError("Vikunja provider requires integrations.vikunja.project_id in config.")
        if not view_id:
            raise ValueError("Vikunja provider requires integrations.vikunja.view_id in config.")
        client = self._build_client()
        for task in await self._db.list_tasks():
            if task.status == TaskStatus.CANCELLED:
                continue
            payload = self._task_to_vikunja_payload(task)
            target_bucket_id = payload.pop("bucket_id", None)
            mapping = await self._get_mapping(task.id)
            if mapping and mapping.get("remote_task_id"):
                remote_task_id = int(mapping["remote_task_id"])
                await client.update_task(str(remote_task_id), payload)
                if target_bucket_id is not None:
                    await client.move_task_to_bucket(str(project_id), str(view_id), int(target_bucket_id), remote_task_id)
                delta.items_updated += 1
                if mapping.get("last_synced_status") != task.status.value:
                    delta.statuses_changed += 1
                    delta.items_moved += 1
                await self._save_mapping(task.id, {
                    **mapping,
                    "remote_task_id": remote_task_id,
                    "last_synced_status": task.status.value,
                    "last_bucket_id": target_bucket_id,
                    "last_push_ts": _utc_now_iso(),
                })
            else:
                created = await client.create_task(str(project_id), payload)
                remote_task_id = int(created["id"])
                if target_bucket_id is not None:
                    await client.move_task_to_bucket(str(project_id), str(view_id), int(target_bucket_id), remote_task_id)
                await self._save_mapping(task.id, {
                    "remote_task_id": remote_task_id,
                    "last_synced_status": task.status.value,
                    "last_bucket_id": target_bucket_id,
                    "last_push_ts": _utc_now_iso(),
                })
                delta.items_created += 1
        await self._record_sync_timestamp("last_push_ts")

    async def _sync_pull(self, delta: SyncDelta) -> None:
        if self._db is None:
            return
        project_id = self._project_id()
        if not project_id:
            raise ValueError("Vikunja provider requires integrations.vikunja.project_id in config.")
        client = self._build_client()
        remote_tasks = await client.list_project_tasks(str(project_id), expand=["buckets"])
        for remote_task in remote_tasks:
            remote_task_id = int(remote_task["id"])
            local_task_id, mapping = await self._find_local_by_remote_task_id(remote_task_id)
            remote_status = _remote_task_to_local_status(remote_task)
            remote_bucket_id = _remote_bucket_id(remote_task)
            if local_task_id is None:
                local_task = Task(
                    id=_imported_local_task_id(remote_task_id),
                    title=str(remote_task.get("title") or f"Vikunja Task {remote_task_id}"),
                    details=str(remote_task.get("description") or "") or None,
                    role=_remote_task_to_local_role(remote_task),
                    status=remote_status,
                )
                await self._db.create_task(local_task)
                mapping = {
                    "remote_task_id": remote_task_id,
                    "last_synced_status": remote_status.value,
                    "last_bucket_id": remote_bucket_id,
                    "imported_comment_ids": [],
                    "last_pull_ts": _utc_now_iso(),
                }
                await self._save_mapping(local_task.id, mapping)
                delta.items_created += 1
                delta.statuses_changed += 1
                local_task_id = local_task.id
            else:
                current = await self._db.get_task(local_task_id)
                if current is None:
                    continue
                if current.status != remote_status:
                    await self._db.update_task(current.model_copy(update={"status": remote_status}))
                    delta.items_updated += 1
                    delta.statuses_changed += 1
                mapping = mapping or {}
                await self._save_mapping(local_task_id, {
                    **mapping,
                    "remote_task_id": remote_task_id,
                    "last_synced_status": remote_status.value,
                    "last_bucket_id": remote_bucket_id,
                    "last_pull_ts": _utc_now_iso(),
                })
            imported = await self._import_remote_comments(
                client=client,
                local_task_id=local_task_id,
                remote_task_id=remote_task_id,
            )
            delta.comments_imported += imported
        await self._record_sync_timestamp("last_pull_ts")

    async def auto_push(self) -> SyncDelta:
        return await self.sync(push=True, pull=False)

    async def auto_pull_maybe(self, pull_interval_seconds: int) -> SyncDelta:
        return await self.sync(push=False, pull=True)

    def _task_to_vikunja_payload(self, task: Task) -> dict[str, Any]:
        bucket_id = self._resolve_bucket_id(task.status)
        payload: dict[str, Any] = {
            "title": task.title,
            "description": task.details or "",
            "done": task.status == TaskStatus.DONE,
        }
        if bucket_id is not None:
            payload["bucket_id"] = bucket_id
        return payload

    def _resolve_bucket_id(self, status: TaskStatus) -> int | None:
        bucket_map = self._bucket_map()
        if status.value in bucket_map:
            return int(bucket_map[status.value])
        lane = _status_to_lane(status)
        if lane in bucket_map:
            return int(bucket_map[lane])
        return None

    def _set_bucket_map(self, bucket_map: dict[str, str]) -> None:
        provider_cfg = self._provider_config()
        extra = object.__getattribute__(provider_cfg, "__pydantic_extra__")
        if extra is None:
            extra = {}
            object.__setattr__(provider_cfg, "__pydantic_extra__", extra)
        extra["bucket_map"] = {str(k): str(v) for k, v in bucket_map.items()}

    async def _ensure_required_labels(
        self,
        client: VikunjaClient,
        existing_labels: list[dict[str, Any]],
    ) -> list[str]:
        existing_titles = {
            str(label.get("title") or label.get("name") or "").strip().lower()
            for label in existing_labels
        }
        created: list[str] = []
        for title in _REQUIRED_ROLE_LABELS:
            if title in existing_titles:
                continue
            await client.create_label(title)
            created.append(title)
            existing_titles.add(title)
        return created

    async def _clean_project_state(
        self,
        client: VikunjaClient,
        project_id: str,
        view_id: str,
    ) -> dict[str, Any]:
        deleted_views: list[str] = []
        views = await client.list_project_views(project_id)
        for view in views:
            remote_view_id = view.get("id")
            if remote_view_id is None or str(remote_view_id) == str(view_id):
                continue
            await client.delete_project_view(project_id, str(remote_view_id))
            deleted_views.append(str(remote_view_id))

        tasks = await client.list_project_tasks(project_id)
        for task in tasks:
            task_id = task.get("id")
            if task_id is None:
                continue
            await client.delete_task(str(task_id))

        old_buckets = await client.get_buckets(project_id, view_id)
        deleted_buckets: list[str] = []
        for bucket in old_buckets:
            bucket_id = bucket.get("id")
            if bucket_id is None:
                continue
            deleted_buckets.append(str(bucket_id))

        cleared_mappings = await self._clear_task_mappings()

        return {
            "cleaned": True,
            "deleted_tasks": len([task for task in tasks if task.get("id") is not None]),
            "deleted_views": deleted_views,
            "deleted_buckets": deleted_buckets,
            "cleared_task_mappings": cleared_mappings,
        }

    async def _ensure_default_buckets(
        self,
        client: VikunjaClient,
        project_id: str,
        view_id: str,
        reset: bool = False,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        created_titles: list[str] = []
        existing_buckets = await client.get_buckets(project_id, view_id)

        if reset:
            created_buckets: list[dict[str, Any]] = []
            for title in _DEFAULT_BUCKET_TITLES:
                created = await client.create_bucket(project_id, view_id, title)
                created_titles.append(title)
                created_buckets.append(created)
            for bucket in existing_buckets:
                bucket_id = bucket.get("id")
                if bucket_id is None:
                    continue
                await client.delete_bucket(project_id, view_id, str(bucket_id))
            return created_buckets, created_titles

        existing_titles = {
            str(bucket.get("title") or bucket.get("name") or "").strip().lower()
            for bucket in existing_buckets
        }
        buckets = list(existing_buckets)
        for title in _DEFAULT_BUCKET_TITLES:
            if title.strip().lower() in existing_titles:
                continue
            created = await client.create_bucket(project_id, view_id, title)
            created_titles.append(title)
            existing_titles.add(title.strip().lower())
            buckets.append(created)
        return buckets, created_titles

    async def _get_mapping(self, local_task_id: str) -> dict[str, Any] | None:
        if self._db is None:
            return None
        cursor = await self._db.conn.execute(
            "SELECT value FROM integration_sync WHERE key = ?",
            (_mapping_key(local_task_id),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return json.loads(row[0])

    async def _find_local_by_remote_task_id(self, remote_task_id: int) -> tuple[str | None, dict[str, Any] | None]:
        if self._db is None:
            return None, None
        cursor = await self._db.conn.execute(
            "SELECT key, value FROM integration_sync WHERE key LIKE 'vikunja.task.%'"
        )
        rows = await cursor.fetchall()
        for key, raw in rows:
            value = json.loads(raw)
            if int(value.get("remote_task_id", -1)) == remote_task_id:
                return str(key).removeprefix("vikunja.task."), value
        return None, None

    async def _import_remote_comments(self, client: VikunjaClient, local_task_id: str, remote_task_id: int) -> int:
        mapping = await self._get_mapping(local_task_id) or {}
        imported_comment_ids = {str(v) for v in mapping.get("imported_comment_ids", [])}
        remote_comments = await client.get_task_comments(str(remote_task_id))
        imported = 0
        for remote_comment in remote_comments:
            remote_comment_id = str(remote_comment.get("id"))
            if not remote_comment_id or remote_comment_id in imported_comment_ids:
                continue
            content = str(remote_comment.get("comment") or remote_comment.get("comment_plain") or "").strip()
            if not content:
                continue
            author = remote_comment.get("author") or {}
            author_id = author.get("username") or author.get("name") or None
            await self._db.create_comment(
                local_task_id,
                CommentAuthorType.SYSTEM,
                content,
                author_id=str(author_id) if author_id else None,
            )
            imported_comment_ids.add(remote_comment_id)
            imported += 1
        if imported:
            await self._save_mapping(local_task_id, {
                **mapping,
                "remote_task_id": remote_task_id,
                "imported_comment_ids": sorted(imported_comment_ids),
                "last_pull_ts": _utc_now_iso(),
            })
        return imported

    async def _save_mapping(self, local_task_id: str, value: dict[str, Any]) -> None:
        if self._db is None:
            return
        await self._db.conn.execute(
            "INSERT INTO integration_sync(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_mapping_key(local_task_id), json.dumps(value)),
        )
        await self._db.conn.commit()

    async def _record_sync_timestamp(self, key: str) -> None:
        if self._db is None:
            return
        await self._db.conn.execute(
            "INSERT INTO integration_sync(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"vikunja.meta.{key}", _utc_now_iso()),
        )
        await self._db.conn.commit()

    async def _clear_task_mappings(self) -> int:
        if self._db is None:
            return 0
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM integration_sync WHERE key LIKE 'vikunja.task.%'"
        )
        row = await cursor.fetchone()
        count = int(row[0]) if row and row[0] is not None else 0
        await self._db.conn.execute(
            "DELETE FROM integration_sync WHERE key LIKE 'vikunja.task.%'"
        )
        await self._db.conn.commit()
        return count


def _normalize_bucket_name(bucket: dict[str, Any]) -> str:
    title = bucket.get("title") or bucket.get("name") or ""
    return str(title).strip().lower()


def _remote_bucket_id(remote_task: dict[str, Any]) -> int | None:
    buckets = remote_task.get("buckets") or []
    if buckets:
        bucket_id = buckets[0].get("id")
        return int(bucket_id) if bucket_id is not None else None
    bucket_id = remote_task.get("bucket_id")
    if bucket_id in (None, 0, "0"):
        return None
    return int(bucket_id)


def _remote_task_to_local_status(remote_task: dict[str, Any]) -> TaskStatus:
    if remote_task.get("done") is True:
        return TaskStatus.DONE
    bucket_title = ""
    buckets = remote_task.get("buckets") or []
    if buckets:
        bucket_title = str(buckets[0].get("title") or "").strip().lower()
    if bucket_title == "done":
        return TaskStatus.DONE
    if bucket_title in {"doing", "in progress"}:
        return TaskStatus.IN_PROGRESS
    if bucket_title in {"to-do", "todo", "backlog"}:
        return TaskStatus.APPROVED
    if _remote_bucket_id(remote_task) is None:
        return TaskStatus.APPROVED
    return TaskStatus.IN_PROGRESS


def _remote_task_to_local_role(remote_task: dict[str, Any]) -> AgentRole:
    for label in remote_task.get("labels") or []:
        title = str(label.get("title") or label.get("name") or "").strip().lower()
        if title == "architect":
            return AgentRole.ARCHITECT
        if title == "engineer":
            return AgentRole.ENGINEER
    return AgentRole.ENGINEER


def _status_to_lane(status: TaskStatus) -> str:
    if status in {TaskStatus.DONE, TaskStatus.CANCELLED}:
        return "done"
    if status in {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.FAILED}:
        return "doing"
    return "to-do"


def _mapping_key(local_task_id: str) -> str:
    return f"vikunja.task.{local_task_id}"


def _imported_local_task_id(remote_task_id: int) -> str:
    return f"vik{remote_task_id}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
