from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Draft, DraftStory
from .utils import isoformat, parse_datetime, utcnow


class SessionStore:
    """Tiny local JSON store for one-user sessions, drafts, dedupe, and logs."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init()

    def init(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._write_state(self._empty_state())
                return
            self._read_state()

    def save_draft(self, draft: Draft, mark_seen: bool = True) -> None:
        now = isoformat(utcnow())
        with self._lock:
            state = self._read_state()
            state["drafts"][draft.id] = self._draft_to_record(draft)
            order = [draft_id for draft_id in state["draft_order"] if draft_id != draft.id]
            state["draft_order"] = [draft.id, *order]
            if mark_seen:
                for story in draft.stories:
                    existing = state["seen_stories"].get(story.key, {})
                    state["seen_stories"][story.key] = {
                        "first_seen_at": existing.get("first_seen_at", now),
                        "last_seen_at": now,
                        "title": story.title,
                        "url": story.url,
                    }
            self._write_state(state)

    def list_drafts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
            rows = []
            for draft_id in state["draft_order"][:limit]:
                record = state["drafts"].get(draft_id)
                if record:
                    rows.append(
                        {
                            "id": record["id"],
                            "created_at": record["created_at"],
                            "status": record["status"],
                            "caption": record["caption"],
                            "manual_export_path": record.get("manual_export_path", ""),
                            "published_at": record.get("published_at"),
                            "publish_response": record.get("publish_response", ""),
                            "log_json": json.dumps(record.get("log", {}), sort_keys=True),
                        }
                    )
            return rows

    def get_draft(self, draft_id: str) -> Draft | None:
        with self._lock:
            record = self._read_state()["drafts"].get(draft_id)
        return self._draft_from_record(record) if record else None

    def update_draft(
        self,
        draft_id: str,
        *,
        status: str | None = None,
        caption: str | None = None,
        manual_export_path: str | None = None,
        published_at: datetime | None = None,
        publish_response: str | None = None,
        log: dict | None = None,
    ) -> None:
        with self._lock:
            state = self._read_state()
            record = state["drafts"].get(draft_id)
            if not record:
                return
            if status is not None:
                record["status"] = status
            if caption is not None:
                record["caption"] = caption
            if manual_export_path is not None:
                record["manual_export_path"] = manual_export_path
            if published_at is not None:
                record["published_at"] = isoformat(published_at)
            if publish_response is not None:
                record["publish_response"] = publish_response
            if log is not None:
                record["log"] = log
            self._write_state(state)

    def update_story_assets(self, draft_id: str, stories: list[DraftStory]) -> None:
        by_key = {story.key: story for story in stories}
        with self._lock:
            state = self._read_state()
            record = state["drafts"].get(draft_id)
            if not record:
                return
            for story_record in record["stories"]:
                story = by_key.get(story_record["key"])
                if story:
                    story_record["slide_path"] = story.slide_path
                    story_record["rights_risk"] = story.rights_risk
            self._write_state(state)

    def replace_draft_stories(self, draft: Draft, mark_seen: bool = True) -> None:
        now = isoformat(utcnow())
        with self._lock:
            state = self._read_state()
            record = state["drafts"].get(draft.id)
            if not record:
                return
            record["stories"] = [self._story_to_record(story) for story in draft.stories]
            record["caption"] = draft.caption
            record["status"] = draft.status
            record["log"] = draft.log
            if mark_seen:
                for story in draft.stories:
                    existing = state["seen_stories"].get(story.key, {})
                    state["seen_stories"][story.key] = {
                        "first_seen_at": existing.get("first_seen_at", now),
                        "last_seen_at": now,
                        "title": story.title,
                        "url": story.url,
                    }
            self._write_state(state)

    def recent_seen_keys(self, hours: int) -> set[str]:
        cutoff = utcnow() - timedelta(hours=hours)
        with self._lock:
            state = self._read_state()
            return {
                key
                for key, record in state["seen_stories"].items()
                if (parse_datetime(record.get("last_seen_at", "")) or utcnow()) >= cutoff
            }

    def log_event(self, level: str, message: str, context: dict | None = None) -> None:
        with self._lock:
            state = self._read_state()
            state["events"].append(
                {
                    "created_at": isoformat(utcnow()),
                    "level": level,
                    "message": message,
                    "context": context or {},
                }
            )
            state["events"] = state["events"][-500:]
            self._write_state(state)

    def _read_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            backup_path = self.path.with_suffix(self.path.suffix + ".unreadable")
            if not backup_path.exists():
                self.path.replace(backup_path)
            state = self._empty_state()
            self._write_state(state)
        return self._normalize_state(state)

    def _write_state(self, state: dict[str, Any]) -> None:
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._normalize_state(state), indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {"drafts": {}, "draft_order": [], "seen_stories": {}, "events": []}

    @classmethod
    def _normalize_state(cls, state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(state, dict):
            return cls._empty_state()
        normalized = cls._empty_state()
        normalized["drafts"] = state.get("drafts") if isinstance(state.get("drafts"), dict) else {}
        order = state.get("draft_order") if isinstance(state.get("draft_order"), list) else []
        normalized["draft_order"] = [draft_id for draft_id in order if draft_id in normalized["drafts"]]
        missing_ids = [draft_id for draft_id in normalized["drafts"] if draft_id not in normalized["draft_order"]]
        missing_ids.sort(key=lambda draft_id: normalized["drafts"][draft_id].get("created_at", ""), reverse=True)
        normalized["draft_order"].extend(missing_ids)
        normalized["seen_stories"] = (
            state.get("seen_stories") if isinstance(state.get("seen_stories"), dict) else {}
        )
        normalized["events"] = state.get("events") if isinstance(state.get("events"), list) else []
        return normalized

    @classmethod
    def _draft_to_record(cls, draft: Draft) -> dict[str, Any]:
        return {
            "id": draft.id,
            "created_at": isoformat(draft.created_at),
            "status": draft.status,
            "caption": draft.caption,
            "manual_export_path": draft.manual_export_path,
            "published_at": isoformat(draft.published_at),
            "publish_response": draft.publish_response,
            "log": draft.log,
            "stories": [cls._story_to_record(story) for story in draft.stories],
        }

    @staticmethod
    def _story_to_record(story: DraftStory) -> dict[str, Any]:
        return {
            "key": story.key,
            "title": story.title,
            "url": story.url,
            "source": story.source,
            "category": story.category,
            "published_at": isoformat(story.published_at),
            "summary": story.summary,
            "image_url": story.image_url,
            "source_count": story.source_count,
            "score": story.score,
            "slide_path": story.slide_path,
            "rights_risk": story.rights_risk,
        }

    @classmethod
    def _draft_from_record(cls, record: dict[str, Any]) -> Draft:
        return Draft(
            id=record["id"],
            created_at=parse_datetime(record.get("created_at", "")) or utcnow(),
            status=record.get("status", "draft"),
            stories=[cls._story_from_record(story) for story in record.get("stories", [])],
            caption=record.get("caption", ""),
            manual_export_path=record.get("manual_export_path", ""),
            published_at=parse_datetime(record.get("published_at", "")),
            publish_response=record.get("publish_response", ""),
            log=record.get("log", {}),
        )

    @staticmethod
    def _story_from_record(record: dict[str, Any]) -> DraftStory:
        return DraftStory(
            key=record["key"],
            title=record["title"],
            url=record["url"],
            source=record["source"],
            category=record["category"],
            published_at=parse_datetime(record.get("published_at", "")),
            summary=record.get("summary", ""),
            image_url=record.get("image_url", ""),
            source_count=int(record.get("source_count") or 1),
            score=float(record.get("score") or 0),
            slide_path=record.get("slide_path", ""),
            rights_risk=record.get("rights_risk", ""),
        )


Database = SessionStore
