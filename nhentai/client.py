import requests
import time
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union
from urllib.parse import urlparse

BASE_URL = "https://nhentai.net/api/v2/search"
GALLERIES_URL = "https://nhentai.net/api/v2/galleries"
GALLERY_URL = "https://nhentai.net/api/v2/galleries/{id}"
GALLERY_FAV_URL = "https://nhentai.net/api/v2/galleries/{id}/favorite"
FAVORITES_URL = "https://nhentai.net/api/v2/favorites"
TAGS_SEARCH_URL = "https://nhentai.net/api/v2/tags/search"
TAGS_IDS_URL = "https://nhentai.net/api/v2/tags/ids"
BLACKLIST_URL = "https://nhentai.net/api/v2/blacklist"
CDN_URL = "https://nhentai.net/api/v2/cdn"
VALID_SORTS = {"date", "popular", "popular-today", "popular-week", "popular-month"}
VALID_TAG_TYPES = {"artist", "category", "character", "group", "language", "parody", "tag"}
MAX_TAGS_BY_IDS = 100

RATE_LIMITS = {
    "galleries": {"anon": (15, 60), "api": (30, 60)},
    "gallery": {"anon": (20, 60), "api": (40, 60)},
    "favorite": {"anon": (15, 60), "api": (15, 60)},
    "tags_ids": {"anon": (15, 60), "api": (15, 60)},
    "tags_search": {"anon": (30, 60), "api": (30, 60)},
    "search": {"anon": (10, 60), "api": (20, 60)},
    "blacklist": {"anon": (15, 60), "api": (15, 60)},
    "favorites": {"anon": (15, 60), "api": (15, 60)},
}


class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._buckets = {}

    def _key_for(self, url, api_key):
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path
        endpoint = "default"
        for name, prefix in [
            ("galleries", "/api/v2/galleries"),
            ("gallery", "/api/v2/galleries/"),
            ("favorite", "/favorite"),
            ("tags_ids", "/api/v2/tags/ids"),
            ("tags_search", "/api/v2/tags/search"),
            ("search", "/api/v2/search"),
            ("blacklist", "/api/v2/blacklist"),
            ("favorites", "/api/v2/favorites"),
        ]:
            if path.startswith(prefix) or prefix in path:
                endpoint = name
                break
        mode = "api" if api_key else "anon"
        return (host, endpoint, mode)

    def wait(self, url, api_key=None):
        key = self._key_for(url, api_key)
        host, endpoint, mode = key
        limits = RATE_LIMITS.get(endpoint, {"anon": (30, 60), "api": (30, 60)})
        count, window = limits.get(mode, (30, 60))
        interval = window / max(count, 1)
        with self._lock:
            now = time.monotonic()
            next_allowed = self._buckets.get(key, 0.0)
            if now < next_allowed:
                sleep_time = next_allowed - now
                time.sleep(sleep_time)
                now = time.monotonic()
            self._buckets[key] = now + interval

    def wait_host(self, url):
        parsed = urlparse(url)
        host = parsed.netloc
        key = (host, "cdn", "any")
        with self._lock:
            now = time.monotonic()
            next_allowed = self._buckets.get(key, 0.0)
            if now < next_allowed:
                time.sleep(next_allowed - now)
                now = time.monotonic()
            self._buckets[key] = now + 0.05


_rate_limiter = RateLimiter()


def _format_date(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _group_tags(tags: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for t in tags or []:
        ttype = t.get("type") or "unknown"
        grouped.setdefault(ttype, []).append({"id": t.get("id"), "name": t.get("name")})
    return grouped


def _assign_servers(servers: List[str], n: int) -> List[str]:
    if not servers or n <= 0:
        return []
    return (servers * (n // len(servers) + 1))[:n]


def _build_pages(pages, image_servers, thumb_servers):
    n = len(pages or [])
    imgs = _assign_servers(image_servers, n)
    thumbs = _assign_servers(thumb_servers, n)
    out = []
    for p, img_base, th_base in zip(pages, imgs, thumbs):
        img_path = (p.get("path") or "").lstrip("/")
        th_path = (p.get("thumbnail") or "").lstrip("/")
        out.append({
            "number": p.get("number"),
            "image": {"url": f"{img_base}/{img_path}" if img_path else None, "width": p.get("width"), "height": p.get("height")},
            "thumbnail": {"url": f"{th_base}/{th_path}" if th_path else None, "width": p.get("thumbnail_width"), "height": p.get("thumbnail_height")},
        })
    return out


def _format_gallery_item(item, base_url):
    eng = item.get("english_title")
    jp = item.get("japanese_title")
    title = eng if eng not in (None, "") else jp
    thumb_path = (item.get("thumbnail") or "").lstrip("/")
    url = f"{base_url}/{thumb_path}" if base_url and thumb_path else None
    return {
        "id": item.get("id"),
        "title": title,
        "thumbnail": {"url": url, "width": item.get("thumbnail_width"), "height": item.get("thumbnail_height")},
        "num_pages": item.get("num_pages"),
        "num_favorites": item.get("num_favorites"),
        "blacklisted": item.get("blacklisted"),
        "tag_ids": item.get("tag_ids") or [],
    }


class NHentaiClient:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        headers = {"accept": "*/*"}
        if self.api_key:
            headers["Authorization"] = f"Key {self.api_key}"
        self.session.headers.update(headers)
        self._cdn_cache = None

    def _headers_for(self, api_key):
        if api_key is None or api_key == self.api_key:
            return None
        return {"Authorization": f"Key {api_key}"}

    def _request(self, method, url, api_key=None, **kwargs):
        headers = kwargs.pop("headers", None)
        extra = self._headers_for(api_key)
        if extra:
            headers = dict(headers or {})
            headers.update(extra)
        kwargs.setdefault("timeout", self.timeout)
        while True:
            _rate_limiter.wait(url, api_key)
            try:
                r = self.session.request(method, url, headers=headers, **kwargs)
                if r.status_code == 443:
                    time.sleep(61)
                    continue
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait = int(retry_after) if retry_after and retry_after.isdigit() else 61
                    time.sleep(wait)
                    continue
                if r.status_code == 503:
                    time.sleep(61)
                    continue
                r.raise_for_status()
                return r
            except requests.exceptions.ConnectionError:
                time.sleep(61)
                continue
            except requests.exceptions.Timeout:
                time.sleep(61)
                continue
            except requests.exceptions.HTTPError:
                raise

    def _get(self, url, api_key=None, **kwargs):
        return self._request("GET", url, api_key=api_key, **kwargs)

    def _post(self, url, api_key=None, **kwargs):
        return self._request("POST", url, api_key=api_key, **kwargs)

    def _delete(self, url, api_key=None, **kwargs):
        return self._request("DELETE", url, api_key=api_key, **kwargs)

    def _raw_search(self, query, sort, page, api_key=None):
        r = self._get(BASE_URL, api_key=api_key, params={"query": query, "sort": sort, "page": page})
        return r.json()

    def _raw_galleries(self, page=1, per_page=25, sort=None, api_key=None):
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        r = self._get(GALLERIES_URL, api_key=api_key, params=params)
        return r.json()

    def _raw_gallery(self, gallery_id, include=None, api_key=None):
        params = {}
        if include:
            params["include"] = include
        r = self._get(GALLERY_URL.format(id=gallery_id), api_key=api_key, params=params or None)
        return r.json()

    def _get_cdn(self, api_key=None):
        if self._cdn_cache is not None:
            return self._cdn_cache
        r = self._get(CDN_URL, api_key=api_key)
        data = r.json()
        self._cdn_cache = data
        return data

    def _raw_download(self, gallery_id, fmt, api_key=None):
        url = f"https://nhentai.net/api/v2/galleries/{gallery_id}/download"
        r = self._post(url, api_key=api_key, params={"format": fmt})
        return r.json()

    def _raw_fav_add(self, gallery_id, api_key=None):
        r = self._post(GALLERY_FAV_URL.format(id=gallery_id), api_key=api_key)
        try:
            return r.json()
        except ValueError:
            return {}

    def _raw_fav_rm(self, gallery_id, api_key=None):
        r = self._delete(GALLERY_FAV_URL.format(id=gallery_id), api_key=api_key)
        try:
            return r.json()
        except ValueError:
            return {}

    def _raw_favorites(self, page=1, api_key=None):
        r = self._get(FAVORITES_URL, api_key=api_key, params={"page": page})
        return r.json()

    def _raw_tags_search(self, tag_type, query, limit=50, api_key=None):
        if tag_type not in VALID_TAG_TYPES:
            raise ValueError("Invalid tag type. Must be one of: {}".format(", ".join(sorted(VALID_TAG_TYPES))))
        payload = {"type": tag_type, "query": query, "limit": limit}
        r = self._post(TAGS_SEARCH_URL, api_key=api_key, json=payload)
        return r.json()

    def _raw_tags_by_ids(self, ids, api_key=None):
        r = self._get(TAGS_IDS_URL, api_key=api_key, params={"ids": ",".join(str(i) for i in ids)})
        return r.json()

    def _raw_blacklist_get(self, api_key=None):
        r = self._get(BLACKLIST_URL, api_key=api_key)
        return r.json()

    def _raw_blacklist_update(self, added=None, removed=None, api_key=None):
        payload = {"added": added or [], "removed": removed or []}
        r = self._post(BLACKLIST_URL, api_key=api_key, json=payload)
        return r.json()

    def get_download_url(self, gallery_id, fmt="zip", api_key=None):
        data = self._raw_download(gallery_id, fmt, api_key=api_key)
        return {"url": data.get("url"), "expires_at": data.get("expires_at")}

    def download_gallery(self, gallery_id, fmt="zip", output_path=None, api_key=None):
        info = self.get_download_url(gallery_id, fmt, api_key=api_key)
        if output_path is None:
            output_path = f"{gallery_id}.{fmt}"
        r = self._get(info["url"], api_key=api_key, stream=True)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return output_path

    def fav_add(self, gallery_id, api_key=None):
        return self._raw_fav_add(gallery_id, api_key=api_key)

    def fav_rm(self, gallery_id, api_key=None):
        return self._raw_fav_rm(gallery_id, api_key=api_key)

    def fav_list(self, page=1, api_key=None):
        data = self._raw_favorites(page, api_key=api_key)
        raw_results = (data.get("result") or data.get("results") or [])[:25]
        cdn = self._get_cdn(api_key=api_key)
        thumb_servers = cdn.get("thumb_servers") or []
        servers = _assign_servers(thumb_servers, len(raw_results))
        results = []
        for item, base in zip(raw_results, servers):
            results.append(_format_gallery_item(item, base))
        return {"results": results, "num_pages": data.get("num_pages"), "total": data.get("total")}

    def search(self, query, sort="date", page=1, api_key=None):
        if sort not in VALID_SORTS:
            raise ValueError(f"Invalid sort: {sort}")
        if page < 1:
            raise ValueError("page must be >= 1")
        data = self._raw_search(query, sort, page, api_key=api_key)
        raw_results = (data.get("result") or data.get("results") or [])[:25]
        cdn = self._get_cdn(api_key=api_key)
        thumb_servers = cdn.get("thumb_servers") or []
        if not thumb_servers:
            raise RuntimeError("No thumb_servers returned from /cdn")
        servers = _assign_servers(thumb_servers, len(raw_results))
        results = []
        for item, base in zip(raw_results, servers):
            results.append(_format_gallery_item(item, base))
        return {"results": results, "num_pages": data.get("num_pages"), "total": data.get("total")}

    def galleries(self, page=1, per_page=25, sort="date", api_key=None):
        if page < 1:
            raise ValueError("page must be >= 1")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        if sort not in VALID_SORTS:
            raise ValueError(f"Invalid sort: {sort}")
        data = self._raw_galleries(page=page, per_page=per_page, sort=sort, api_key=api_key)
        raw_results = (data.get("result") or data.get("results") or [])[:per_page]
        cdn = self._get_cdn(api_key=api_key)
        thumb_servers = cdn.get("thumb_servers") or []
        if not thumb_servers:
            raise RuntimeError("No thumb_servers returned from /cdn")
        servers = _assign_servers(thumb_servers, len(raw_results))
        results = []
        for item, base in zip(raw_results, servers):
            results.append(_format_gallery_item(item, base))
        return {
            "results": results,
            "num_pages": data.get("num_pages"),
            "per_page": data.get("per_page"),
            "total": data.get("total"),
        }

    def tags_search(self, tag_type, query, limit=50, api_key=None):
        data = self._raw_tags_search(tag_type, query, limit, api_key=api_key)
        items = data if isinstance(data, list) else (data.get("result") or data.get("results") or [])
        return [{"id": t.get("id"), "name": t.get("name")} for t in items]

    def tags_by_ids(self, ids, api_key=None):
        if isinstance(ids, (int, str)):
            ids = [ids]
        ids = list(ids)
        if not ids:
            return []
        if len(ids) > MAX_TAGS_BY_IDS:
            raise ValueError(f"ids must contain at most {MAX_TAGS_BY_IDS} entries")
        data = self._raw_tags_by_ids(ids, api_key=api_key)
        items = data if isinstance(data, list) else (data.get("result") or data.get("results") or [])
        return [
            {
                "id": t.get("id"),
                "type": t.get("type"),
                "name": t.get("name"),
                "slug": t.get("slug"),
                "url": t.get("url"),
                "count": t.get("count"),
            }
            for t in items
        ]

    def blacklist(self, api_key=None):
        data = self._raw_blacklist_get(api_key=api_key)
        items = data.get("tags") or []
        return {
            "tags": [{"id": t.get("id"), "name": t.get("name")} for t in items],
            "count": data.get("count"),
        }

    def blacklist_update(self, added=None, removed=None, api_key=None):
        return self._raw_blacklist_update(added=added, removed=removed, api_key=api_key)

    def gallery(self, gallery_id, api_key=None):
        data = self._raw_gallery(gallery_id, include="favorite", api_key=api_key)
        title_obj = data.get("title") or {}
        pretty = title_obj.get("pretty")
        eng = title_obj.get("english")
        jp = title_obj.get("japanese")
        title = pretty if pretty not in (None, "") else (eng if eng not in (None, "") else jp)
        cdn = self._get_cdn(api_key=api_key)
        image_servers = cdn.get("image_servers") or []
        thumb_servers = cdn.get("thumb_servers") or []
        cover = data.get("cover") or {}
        thumb = data.get("thumbnail") or {}
        cover_path = (cover.get("path") or "").lstrip("/")
        thumb_path = (thumb.get("path") or "").lstrip("/")
        cover_url = f"{image_servers[0]}/{cover_path}" if image_servers and cover_path else None
        thumb_url = f"{thumb_servers[0]}/{thumb_path}" if thumb_servers and thumb_path else None
        return {
            "id": data.get("id"),
            "title": title,
            "titles": {"english": eng, "japanese": jp, "pretty": pretty},
            "is_favorited": data.get("is_favorited"),
            "upload_date": _format_date(data.get("upload_date")),
            "num_pages": data.get("num_pages"),
            "num_favorites": data.get("num_favorites"),
            "scanlator": data.get("scanlator"),
            "cover": {"url": cover_url, "width": cover.get("width"), "height": cover.get("height")},
            "thumbnail": {"url": thumb_url, "width": thumb.get("width"), "height": thumb.get("height")},
            "tags": _group_tags(data.get("tags") or []),
            "pages": _build_pages(data.get("pages") or [], image_servers, thumb_servers),
            "_image_servers": image_servers,
        }

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
