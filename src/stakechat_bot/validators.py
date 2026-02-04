from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from .config import RootConfig


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def looks_like_ss58(s: str) -> bool:
    s = (s or "").strip()
    return bool(re.fullmatch(r"5[1-9A-HJ-NP-Za-km-z]{40,60}", s))


@dataclass(frozen=True)
class ValidatorEntry:
    name: str
    hotkey: str
    source: str


def _get_path(obj: Any, path: str) -> Any:
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class ValidatorResolver:
    """Local cached validator registry with multiple sources."""

    def __init__(self, cfg: RootConfig):
        self.cfg = cfg
        self.cache_path = Path(cfg.app.data_dir) / "validators_cache.json"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Optional alias JSON: {"taostats":"5F...","myval":"5G..."}
        self.aliases: Dict[str, str] = {}
        alias_json = os.getenv("VALIDATOR_ALIASES_JSON", "").strip()
        if alias_json:
            try:
                obj = json.loads(alias_json)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(k, str) and isinstance(v, str) and looks_like_ss58(v.strip()):
                            self.aliases[_norm(k)] = v.strip()
            except Exception:
                pass

        self._loaded = False
        self._entries: List[ValidatorEntry] = []
        self._by_name: Dict[str, List[ValidatorEntry]] = {}
        self._last_refresh_meta: Dict[str, Any] = {}

    def sources_summary(self) -> List[str]:
        out = []
        for s in self.cfg.validators.sources:
            typ = getattr(s, "type", "")
            if typ == "taostats":
                out.append(f"- taostats: {getattr(s, 'api_url', '') or ''} (api_key={'set' if getattr(s,'api_key','') else 'unset'})")
            elif typ == "http_json":
                out.append(f"- http_json: {getattr(s,'url','') or ''}")
            elif typ == "file_json":
                out.append(f"- file_json: {getattr(s,'path','') or ''}")
        if not out:
            out.append("- (no sources configured)")
        out.append(f"- fallback delegates: {self.cfg.validators.delegates_fallback_url}")
        return out

    def _expired(self) -> bool:
        ttl = self.cfg.validators.cache_ttl_minutes * 60
        try:
            age = time.time() - self.cache_path.stat().st_mtime
            return age > ttl
        except FileNotFoundError:
            return True

    def _set_entries(self, entries: List[ValidatorEntry]) -> None:
        self._entries = entries
        by_name: Dict[str, List[ValidatorEntry]] = {}
        for e in entries:
            by_name.setdefault(_norm(e.name), []).append(e)
        self._by_name = by_name
        self._loaded = True

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            entries = []
            for it in data.get("entries", []):
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name", "")).strip()
                hotkey = str(it.get("hotkey", "")).strip()
                src = str(it.get("source", "")).strip() or "cache"
                if name and looks_like_ss58(hotkey):
                    entries.append(ValidatorEntry(name=name, hotkey=hotkey, source=src))
            self._last_refresh_meta = data.get("meta", {}) if isinstance(data.get("meta", {}), dict) else {}
            if entries:
                self._set_entries(entries)
        except Exception:
            return

    def _save_cache(self) -> None:
        payload = {
            "saved_ts": time.time(),
            "meta": self._last_refresh_meta,
            "entries": [e.__dict__ for e in self._entries],
        }
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.cache_path)

    def _fetch_from_delegates(self) -> List[ValidatorEntry]:
        url = self.cfg.validators.delegates_fallback_url
        r = requests.get(url, timeout=25)
        r.raise_for_status()
        data = r.json()
        out: List[ValidatorEntry] = []
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name", "")).strip() or str(it.get("display", "")).strip()
                hotkey = str(it.get("hotkey", "")).strip() or str(it.get("hotkey_ss58", "")).strip()
                if name and looks_like_ss58(hotkey):
                    out.append(ValidatorEntry(name=name, hotkey=hotkey, source="delegates"))
        return out

    def _extract_entries_from_list(self, items: Any, source: str, name_field: str = "name", hotkey_field: str = "hotkey") -> List[ValidatorEntry]:
        out: List[ValidatorEntry] = []
        if not isinstance(items, list):
            return out
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get(name_field, "")).strip() or str(it.get("name", "")).strip() or str(it.get("display", "")).strip()
            hotkey = str(it.get(hotkey_field, "")).strip() or str(it.get("hotkey", "")).strip() or str(it.get("hotkey_ss58", "")).strip()
            if name and looks_like_ss58(hotkey):
                out.append(ValidatorEntry(name=name, hotkey=hotkey, source=source))
        return out

    def _fetch_taostats(self, api_url: str, api_key: str) -> List[ValidatorEntry]:
        headers = {}
        key = (api_key or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
            headers["x-api-key"] = key
        r = requests.get(api_url, headers=headers, timeout=25)
        r.raise_for_status()
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else None
        if items is None:
            items = data if isinstance(data, list) else []
        out: List[ValidatorEntry] = []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = (
                    str(it.get("name", "")).strip()
                    or str(it.get("validator_name", "")).strip()
                    or str(it.get("identity", "")).strip()
                    or str(it.get("display", "")).strip()
                )
                hotkey = (
                    str(it.get("hotkey", "")).strip()
                    or str(it.get("hotkey_ss58", "")).strip()
                    or str(it.get("hotkey_ss58_address", "")).strip()
                )
                if name and looks_like_ss58(hotkey):
                    out.append(ValidatorEntry(name=name, hotkey=hotkey, source="taostats"))
        return out

    def _fetch_http_json(self, url: str, headers: Dict[str, str], data_path: str, name_field: str, hotkey_field: str) -> List[ValidatorEntry]:
        if not url:
            return []
        hdrs = dict(headers or {})
        token = os.getenv("VALIDATOR_REGISTRY_TOKEN", "").strip()
        if token and not hdrs:
            hdrs["Authorization"] = f"Bearer {token}"
        r = requests.get(url, headers=hdrs, timeout=25)
        r.raise_for_status()
        data = r.json()
        items = _get_path(data, data_path) if data_path else data
        return self._extract_entries_from_list(items, source="http_json", name_field=name_field, hotkey_field=hotkey_field)

    def _fetch_file_json(self, path: str, data_path: str, name_field: str, hotkey_field: str) -> List[ValidatorEntry]:
        if not path:
            return []
        p = Path(path)
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        if not p.exists():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
        items = _get_path(data, data_path) if data_path else data
        return self._extract_entries_from_list(items, source="file_json", name_field=name_field, hotkey_field=hotkey_field)

    def refresh(self, force: bool = False) -> Tuple[int, Dict[str, Any]]:
        self._last_refresh_meta = {
            "started_ts": time.time(),
            "sources": [],
            "errors": [],
        }

        entries: List[ValidatorEntry] = []

        for src in self.cfg.validators.sources:
            typ = getattr(src, "type", "")
            try:
                if typ == "taostats":
                    api_url = getattr(src, "api_url", "")
                    api_key = getattr(src, "api_key", "")
                    if api_url and api_key:
                        got = self._fetch_taostats(api_url, api_key)
                        self._last_refresh_meta["sources"].append({"type": "taostats", "count": len(got)})
                        entries += got
                    else:
                        self._last_refresh_meta["sources"].append({"type": "taostats", "count": 0, "skipped": "missing api_url or api_key"})
                elif typ == "http_json":
                    got = self._fetch_http_json(
                        getattr(src, "url", ""),
                        getattr(src, "headers", {}) or {},
                        getattr(src, "data_path", "") or "",
                        getattr(src, "name_field", "name") or "name",
                        getattr(src, "hotkey_field", "hotkey") or "hotkey",
                    )
                    self._last_refresh_meta["sources"].append({"type": "http_json", "count": len(got)})
                    entries += got
                elif typ == "file_json":
                    got = self._fetch_file_json(
                        getattr(src, "path", ""),
                        getattr(src, "data_path", "") or "",
                        getattr(src, "name_field", "name") or "name",
                        getattr(src, "hotkey_field", "hotkey") or "hotkey",
                    )
                    self._last_refresh_meta["sources"].append({"type": "file_json", "count": len(got)})
                    entries += got
            except Exception as e:
                self._last_refresh_meta["errors"].append({"type": typ, "error": str(e)})

        if not entries:
            try:
                got = self._fetch_from_delegates()
                self._last_refresh_meta["sources"].append({"type": "delegates_fallback", "count": len(got)})
                entries = got
            except Exception as e:
                self._last_refresh_meta["errors"].append({"type": "delegates_fallback", "error": str(e)})

        seen = set()
        uniq: List[ValidatorEntry] = []
        for e in entries:
            key = (_norm(e.name), e.hotkey)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(e)

        self._set_entries(uniq)
        self._last_refresh_meta["finished_ts"] = time.time()
        self._last_refresh_meta["total"] = len(uniq)
        self._save_cache()
        return len(uniq), dict(self._last_refresh_meta)

    def refresh_if_needed(self) -> None:
        if not self._loaded:
            self._load_cache()
        if self._loaded and not self._expired():
            return
        try:
            self.refresh(force=True)
        except Exception:
            if not self._loaded:
                self._load_cache()

    def resolve(self, raw: str) -> Tuple[Optional[ValidatorEntry], List[ValidatorEntry]]:
        raw = (raw or "").strip()
        if not raw:
            return None, []

        if looks_like_ss58(raw):
            return ValidatorEntry(name=raw, hotkey=raw, source="ss58"), []

        if _norm(raw) in self.aliases:
            hk = self.aliases[_norm(raw)]
            return ValidatorEntry(name=raw, hotkey=hk, source="alias"), []

        self.refresh_if_needed()

        key = _norm(raw)
        if key in self._by_name and len(self._by_name[key]) == 1:
            return self._by_name[key][0], []

        # fuzzy contains
        cands: List[ValidatorEntry] = []
        for e in self._entries:
            if key and key in _norm(e.name):
                cands.append(e)

        if key in self._by_name and len(self._by_name[key]) > 1:
            cands = self._by_name[key]

        if len(cands) == 1:
            return cands[0], []

        return None, cands[:8]

    def search(self, term: str, limit: int = 10) -> List[ValidatorEntry]:
        self.refresh_if_needed()
        key = _norm(term)
        if not key:
            return []
        hits = [e for e in self._entries if key in _norm(e.name)]
        return hits[:limit]

    def name_for_hotkey(self, hotkey: str) -> Optional[str]:
        """Return a friendly name for a hotkey if present in the local registry."""
        self.refresh_if_needed()
        hk = (hotkey or "").strip()
        for e in self._entries:
            if (e.hotkey or "").strip() == hk:
                return e.name
        return None
        
        

    def last_refresh_meta(self) -> Dict[str, Any]:
        if not self._loaded:
            self._load_cache()
        return dict(self._last_refresh_meta or {})
