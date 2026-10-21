import requests
import time
import threading
import atexit
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union
from urllib.parse import urlparse

BASE_URL = "https://nhentai.net/api/v2/search"
GALLERIES_URL = "https://nhentai.net/api/v2/galleries"
GALLERIES_TAGGED_URL = "https://nhentai.net/api/v2/galleries/tagged"
GALLERIES_POPULAR_URL = "https://nhentai.net/api/v2/galleries/popular"
GALLERIES_RANDOM_URL = "https://nhentai.net/api/v2/galleries/random"
GALLERY_URL = "https://nhentai.net/api/v2/galleries/{id}"
GALLERY_RELATED_URL = "https://nhentai.net/api/v2/galleries/{id}/related"
GALLERY_FAV_URL = "https://nhentai.net/api/v2/galleries/{id}/favorite"
GALLERY_FAV_CHECK_URL = "https://nhentai.net/api/v2/galleries/{id}/favorite"
GALLERY_DOWNLOAD_URL = "https://nhentai.net/api/v2/galleries/{id}/download"
FAVORITES_URL = "https://nhentai.net/api/v2/favorites"
FAVORITES_RANDOM_URL = "https://nhentai.net/api/v2/favorites/random"
TAGS_SEARCH_URL = "https://nhentai.net/api/v2/tags/search"
TAGS_IDS_URL = "https://nhentai.net/api/v2/tags/ids"
BLACKLIST_URL = "https://nhentai.net/api/v2/blacklist"
CDN_URL = "https://nhentai.net/api/v2/cdn"
USER_URL = "https://nhentai.net/api/v2/user"
USER_AVATAR_URL = "https://nhentai.net/api/v2/user/avatar"
USER_KEYS_URL = "https://nhentai.net/api/v2/user/keys"

VALID_SORTS = {"date", "popular", "popular-today", "popular-week", "popular-month"}
VALID_TAG_TYPES = {"artist", "category", "character", "group", "language", "parody", "tag"}
MAX_TAGS_BY_IDS = 100

RATE_LIMITS = {
    "galleries":         {"anon": (15, 60), "user": (30, 60), "api": (30, 60)},
    "gallery":           {"anon": (20, 60), "user": (45, 60), "api": (45, 60)},
    "gallery_related":   {"anon": (12, 60), "user": (30, 60), "api": (30, 60)},
    "galleries_tagged":  {"anon": (15, 60), "user": (30, 60), "api": (30, 60)},
    "galleries_popular": {"anon": (8, 60),  "user": (8, 60),  "api": (8, 60)},
    "galleries_random":  {"anon": (20, 60), "user": (30, 60), "api": (30, 60)},
    "favorite":          {"anon": (15, 60), "user": (15, 60), "api": (15, 60)},
    "favorite_check":    {"user": (15, 60), "api": (15, 60)},
    "tags_ids":          {"anon": (15, 60), "user": (15, 60), "api": (15, 60)},
    "tags_search":       {"anon": (30, 60), "user": (30, 60), "api": (30, 60)},
    "search":            {"anon": (10, 60), "user": (20, 60), "api": (20, 60)},
    "blacklist":         {"anon": (15, 60), "user": (15, 60), "api": (15, 60)},
    "favorites":         {"anon": (15, 60), "user": (15, 60), "api": (15, 60)},
    "favorites_random":  {"user": (15, 60), "api": (15, 60)},
    "user":              {"anon": (15, 60), "user": (15, 60), "api": (15, 60)},
    "user_avatar":       {"user": (5, 60)},
    "user_keys":         {"user": (30, 60)},
}

DOWNLOAD_RATE_LIMITS = {
    "torrent": {"ip": (5, 60),  "user": (10, 300), "api": (5, 60)},
    "zip":     {"ip": (10, 300), "user": (7, 300),  "api": (10, 300)},
}

USER_UPDATE_RATE_LIMITS = {
    "user":    (30, 900),
    "ip_user": (30, 900),
}


def _credential_kind(token: Optional[str]) -> str:
    if not token:
        return "anon"
    if token.startswith("nhk_"):
        return "api"
    return "user"


def _auth_header_value(token: Optional[str]) -> Optional[str]:
    kind = _credential_kind(token)
    if kind == "anon":
        return None
    if kind == "api":
        return f"Key {token}"
    return f"User {token}"


class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._buckets = {}

    def _key_for(self, url, token):
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path
        endpoint = "default"
        for name, prefix in [
            ("download", "/api/v2/galleries/"),
            ("favorite_check", "/favorite"),
            ("favorite", "/favorite"),
            ("favorites_random", "/api/v2/favorites/random"),
            ("favorites", "/api/v2/favorites"),
            ("user_avatar", "/api/v2/user/avatar"),
            ("user_keys", "/api/v2/user/keys"),
            ("user_update", "/api/v2/user"),
            ("user", "/api/v2/user"),
            ("tags_ids", "/api/v2/tags/ids"),
            ("tags_search", "/api/v2/tags/search"),
            ("search", "/api/v2/search"),
            ("blacklist", "/api/v2/blacklist"),
            ("galleries_popular", "/api/v2/galleries/popular"),
            ("galleries_random", "/api/v2/galleries/random"),
            ("galleries_tagged", "/api/v2/galleries/tagged"),
            ("gallery_related", "/api/v2/galleries/"),
            ("galleries", "/api/v2/galleries"),
            ("gallery", "/api/v2/galleries/"),
        ]:
            if path.startswith(prefix) or prefix in path:
                endpoint = name
                break
        mode = _credential_kind(token)
        return (host, endpoint, mode)

    def wait(self, url, token=None, extra_key: Optional[str] = None):
        key = self._key_for(url, token)
        host, endpoint, mode = key
        if extra_key:
            if extra_key.startswith("favorite_"):
                endpoint = extra_key
                key = (host, endpoint, mode)
            else:
                key = (host, endpoint + ":" + extra_key, mode)

        limits = RATE_LIMITS.get(endpoint)
        if not limits:
            count, window = (30, 60)
        else:
            count, window = limits.get(mode, (30, 60))

        interval = window / max(count, 1)
        with self._lock:
            now = time.monotonic()
            next_allowed = self._buckets.get(key, 0.0)
            if now < next_allowed:
                time.sleep(next_allowed - now)
                now = time.monotonic()
            self._buckets[key] = now + interval

    def wait_download(self, url, fmt, token=None):
        fmt = "torrent" if fmt == "torrent" else "zip"
        limits = DOWNLOAD_RATE_LIMITS[fmt]
        parsed = urlparse(url)
        host = parsed.netloc
        kind = _credential_kind(token)

        buckets = [("ip", limits["ip"])]
        if kind == "user":
            buckets.append(("user", limits["user"]))
        elif kind == "api":
            buckets.append(("api", limits["api"]))
        else:
            buckets.append(("anon", limits["ip"]))

        with self._lock:
            now = time.monotonic()
            wait_until = now
            keys = []
            for name, (count, window) in buckets:
                interval = window / max(count, 1)
                key = (host, "download", fmt, name)
                keys.append((key, interval))
                nxt = self._buckets.get(key, 0.0)
                if nxt > wait_until:
                    wait_until = nxt

            if now < wait_until:
                time.sleep(wait_until - now)
                now = time.monotonic()

            for key, interval in keys:
                self._buckets[key] = now + interval

    def wait_update(self, url, token=None, ip: Optional[str] = None):
        parsed = urlparse(url)
        host = parsed.netloc
        ip_key = ip or "local"
        with self._lock:
            now = time.monotonic()
            keys = []
            wait_until = now
            for name, (count, window), suffix in (
                ("user", USER_UPDATE_RATE_LIMITS["user"], ""),
                ("ip_user", USER_UPDATE_RATE_LIMITS["ip_user"], f":{ip_key}"),
            ):
                interval = window / max(count, 1)
                key = (host, "user_update", name, suffix)
                keys.append((key, interval))
                nxt = self._buckets.get(key, 0.0)
                if nxt > wait_until:
                    wait_until = nxt
            if now < wait_until:
                time.sleep(wait_until - now)
                now = time.monotonic()
            for key, interval in keys:
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


def _format_user(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": data.get("id"),
        "username": data.get("username"),
        "slug": data.get("slug"),
        "avatar_url": data.get("avatar_url"),
        "theme": data.get("theme"),
        "is_staff": data.get("is_staff"),
        "is_superuser": data.get("is_superuser"),
        "roles": data.get("roles") or [],
        "permissions": data.get("permissions") or [],
        "about": data.get("about"),
        "favorite_tags": data.get("favorite_tags"),
        "email": data.get("email"),
    }


def _format_api_key(k: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": k.get("id"),
        "key_prefix": k.get("key_prefix"),
        "name": k.get("name"),
        "created_at": k.get("created_at"),
        "last_used_at": k.get("last_used_at"),
    }


class NHentaiClient:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        headers = {"accept": "*/*"}
        auth = _auth_header_value(self.api_key)
        if auth:
            headers["Authorization"] = auth
        self.session.headers.update(headers)
        self._cdn_cache = None

    def _headers_for(self, token: Optional[str], anon: bool = False):
        if anon:
            return {"Authorization": None}
        if token is None or token == self.api_key:
            return None
        auth = _auth_header_value(token)
        return {"Authorization": auth} if auth else {"Authorization": None}

    def _request(self, method, url, api_key=None, anon=False, rate_key=None, **kwargs):
        headers = kwargs.pop("headers", None)
        extra = self._headers_for(api_key, anon=anon)
        if extra:
            headers = dict(headers or {})
            headers.update(extra)
        kwargs.setdefault("timeout", self.timeout)
        effective_token = None if anon else (api_key or self.api_key)
        while True:
            if rate_key == "user_update":
                _rate_limiter.wait_update(url, effective_token)
            elif rate_key in ("zip", "torrent"):
                _rate_limiter.wait_download(url, rate_key, effective_token)
            else:
                _rate_limiter.wait(url, effective_token, extra_key=rate_key)
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

    def _get(self, url, api_key=None, anon=False, rate_key=None, **kwargs):
        return self._request("GET", url, api_key=api_key, anon=anon, rate_key=rate_key, **kwargs)

    def _post(self, url, api_key=None, anon=False, rate_key=None, **kwargs):
        return self._request("POST", url, api_key=api_key, anon=anon, rate_key=rate_key, **kwargs)

    def _patch(self, url, api_key=None, anon=False, rate_key=None, **kwargs):
        return self._request("PATCH", url, api_key=api_key, anon=anon, rate_key=rate_key, **kwargs)

    def _delete(self, url, api_key=None, anon=False, rate_key=None, **kwargs):
        return self._request("DELETE", url, api_key=api_key, anon=anon, rate_key=rate_key, **kwargs)

    def _raw_search(self, query, sort, page, api_key=None, anon=False):
        r = self._get(BASE_URL, api_key=api_key, anon=anon,
                      params={"query": query, "sort": sort, "page": page})
        return r.json()

    def _raw_galleries(self, page=1, per_page=25, sort=None, api_key=None, anon=False):
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        r = self._get(GALLERIES_URL, api_key=api_key, anon=anon, params=params)
        return r.json()

    def _raw_galleries_by_tag(self, tag_id, page=1, per_page=25, sort=None, api_key=None, anon=False):
        params = {"tag_id": tag_id, "page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        r = self._get(GALLERIES_TAGGED_URL, api_key=api_key, anon=anon, params=params)
        return r.json()

    def _raw_galleries_popular(self, api_key=None, anon=False):
        r = self._get(GALLERIES_POPULAR_URL, api_key=api_key, anon=anon)
        return r.json()

    def _raw_galleries_random(self, api_key=None, anon=False):
        r = self._get(GALLERIES_RANDOM_URL, api_key=api_key, anon=anon)
        return r.json()

    def _raw_gallery(self, gallery_id, include=None, api_key=None, anon=False):
        params = {}
        if include:
            params["include"] = include
        r = self._get(GALLERY_URL.format(id=gallery_id), api_key=api_key, anon=anon,
                      params=params or None)
        return r.json()

    def _raw_gallery_related(self, gallery_id, api_key=None, anon=False):
        r = self._get(GALLERY_RELATED_URL.format(id=gallery_id),
                      api_key=api_key, anon=anon)
        return r.json()

    def _get_cdn(self, api_key=None, anon=False):
        if self._cdn_cache is not None:
            return self._cdn_cache
        r = self._get(CDN_URL, api_key=api_key, anon=anon)
        data = r.json()
        self._cdn_cache = data
        return data

    def _raw_download(self, gallery_id, fmt, api_key=None, anon=False):
        if anon or not (api_key or self.api_key):
            raise ValueError(
                "The /download endpoint requires authentication "
                "(a 'User' session token or a 'Key' API key)."
            )
        fmt_norm = "torrent" if fmt == "torrent" else "zip"
        r = self._post(
            GALLERY_DOWNLOAD_URL.format(id=gallery_id),
            api_key=api_key, anon=anon,
            rate_key=fmt_norm,
            params={"format": fmt},
        )
        return r.json()

    def _raw_user(self, api_key=None, anon=False):
        r = self._get(USER_URL, api_key=api_key, anon=anon)
        return r.json()

    def _raw_user_update(self, payload, api_key=None, anon=False):
        token = None if anon else (api_key or self.api_key)
        if _credential_kind(token) != "user":
            raise ValueError(
                "The PATCH /api/v2/user endpoint requires a 'User' session "
                "token (not an API key and not anonymous)."
            )
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        body = {k: payload[k] for k in self._USER_UPDATE_FIELDS if k in payload}
        if not body:
            raise ValueError(
                "payload must contain at least one of: "
                + ", ".join(self._USER_UPDATE_FIELDS)
            )
        r = self._patch(USER_URL, api_key=api_key, anon=anon,
                        rate_key="user_update", json=body)
        try:
            return r.json()
        except ValueError:
            return {}

    def _raw_user_avatar_upload(self, file, api_key=None, anon=False):
        token = None if anon else (api_key or self.api_key)
        if _credential_kind(token) != "user":
            raise ValueError(
                "The /api/v2/user/avatar endpoint requires a 'User' session "
                "token (not an API key and not anonymous)."
            )

        if isinstance(file, (bytes, bytearray)):
            filename, payload = "avatar.png", bytes(file)
        elif isinstance(file, str):
            filename = file.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "avatar.png"
            with open(file, "rb") as fh:
                payload = fh.read()
        elif hasattr(file, "read"):
            filename = getattr(file, "name", None)
            filename = (filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                        if isinstance(filename, str) else "avatar.png")
            payload = file.read()
        else:
            raise TypeError("`file` must be bytes, a path, or a file-like object")

        r = self._post(
            USER_AVATAR_URL,
            api_key=api_key, anon=anon,
            files={"avatar": (filename, payload)},
        )
        try:
            return r.json()
        except ValueError:
            return {}

    def _raw_user_keys(self, api_key=None, anon=False):
        token = None if anon else (api_key or self.api_key)
        if _credential_kind(token) != "user":
            raise ValueError(
                "The /api/v2/user/keys endpoint requires a 'User' session "
                "token (not an API key and not anonymous)."
            )
        r = self._get(USER_KEYS_URL, api_key=api_key, anon=anon)
        return r.json()

    def _raw_fav_add(self, gallery_id, api_key=None, anon=False):
        r = self._post(GALLERY_FAV_URL.format(id=gallery_id), api_key=api_key, anon=anon)
        try:
            return r.json()
        except ValueError:
            return {}

    def _raw_fav_rm(self, gallery_id, api_key=None, anon=False):
        r = self._delete(GALLERY_FAV_URL.format(id=gallery_id), api_key=api_key, anon=anon)
        try:
            return r.json()
        except ValueError:
            return {}

    def _raw_fav_check(self, gallery_id, api_key=None, anon=False):
        token = None if anon else (api_key or self.api_key)
        if _credential_kind(token) == "anon":
            raise ValueError(
                "The /api/v2/galleries/{id}/favorite endpoint requires authentication "
                "(a 'User' session token or a 'Key' API key)."
            )
        r = self._get(
            GALLERY_FAV_CHECK_URL.format(id=gallery_id),
            api_key=api_key, anon=anon,
            rate_key="favorite_check",
        )
        return r.json()

    def _raw_favorites(self, page=1, api_key=None, anon=False):
        r = self._get(FAVORITES_URL, api_key=api_key, anon=anon, params={"page": page})
        return r.json()

    def _raw_favorites_random(self, api_key=None, anon=False):
        token = None if anon else (api_key or self.api_key)
        if _credential_kind(token) == "anon":
            raise ValueError(
                "The /api/v2/favorites/random endpoint requires authentication "
                "(a 'User' session token or a 'Key' API key)."
            )
        r = self._get(FAVORITES_RANDOM_URL, api_key=api_key, anon=anon)
        return r.json()

    def _raw_tags_search(self, tag_type, query, limit=50, api_key=None, anon=False):
        if tag_type not in VALID_TAG_TYPES:
            raise ValueError("Invalid tag type. Must be one of: {}".format(", ".join(sorted(VALID_TAG_TYPES))))
        payload = {"type": tag_type, "query": query, "limit": limit}
        r = self._post(TAGS_SEARCH_URL, api_key=api_key, anon=anon, json=payload)
        return r.json()

    def _raw_tags_by_ids(self, ids, api_key=None, anon=False):
        r = self._get(TAGS_IDS_URL, api_key=api_key, anon=anon,
                      params={"ids": ",".join(str(i) for i in ids)})
        return r.json()

    def _raw_blacklist_get(self, api_key=None, anon=False):
        r = self._get(BLACKLIST_URL, api_key=api_key, anon=anon)
        return r.json()

    def _raw_blacklist_update(self, added=None, removed=None, api_key=None, anon=False):
        payload = {"added": added or [], "removed": removed or []}
        r = self._post(BLACKLIST_URL, api_key=api_key, anon=anon, json=payload)
        return r.json()

    def user(self, api_key=None, anon=False):
        return _format_user(self._raw_user(api_key=api_key, anon=anon))

    def user_update(self, username=None, email=None, about=None,
                    favorite_tags=None, theme=None,
                    current_password=None, new_password=None,
                    default_avatar=None, api_key=None, anon=False):
        payload = {
            "username": username,
            "email": email,
            "about": about,
            "favorite_tags": favorite_tags,
            "theme": theme,
            "current_password": current_password,
            "new_password": new_password,
            "default_avatar": default_avatar,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        data = self._raw_user_update(payload, api_key=api_key, anon=anon)
        return _format_user(data) if isinstance(data, dict) else data

    def user_avatar_upload(self, file, api_key=None, anon=False):
        return self._raw_user_avatar_upload(file, api_key=api_key, anon=anon)

    def user_keys(self, api_key=None, anon=False):
        data = self._raw_user_keys(api_key=api_key, anon=anon)
        items = data if isinstance(data, list) else (data.get("result") or data.get("results") or [])
        return [_format_api_key(k) for k in items]

    def get_download_url(self, gallery_id, fmt="zip", api_key=None, anon=False):
        data = self._raw_download(gallery_id, fmt, api_key=api_key, anon=anon)
        return {"url": data.get("url"), "expires_at": data.get("expires_at")}

    def download_gallery(self, gallery_id, fmt="zip", output_path=None, api_key=None, anon=False):
        info = self.get_download_url(gallery_id, fmt, api_key=api_key, anon=anon)
        if output_path is None:
            output_path = f"{gallery_id}.{fmt}"
        r = self._get(info["url"], api_key=api_key, anon=anon, stream=True)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return output_path

    def fav_add(self, gallery_id, api_key=None, anon=False):
        return self._raw_fav_add(gallery_id, api_key=api_key, anon=anon)

    def fav_rm(self, gallery_id, api_key=None, anon=False):
        return self._raw_fav_rm(gallery_id, api_key=api_key, anon=anon)

    def check_fav(self, gallery_id, api_key=None, anon=False):
        data = self._raw_fav_check(gallery_id, api_key=api_key, anon=anon)
        return {
            "favorited": data.get("favorited"),
            "num_favorites": data.get("num_favorites"),
        }

    def fav_list(self, page=1, api_key=None, anon=False):
        data = self._raw_favorites(page, api_key=api_key, anon=anon)
        raw_results = (data.get("result") or data.get("results") or [])[:25]
        cdn = self._get_cdn(api_key=api_key, anon=anon)
        thumb_servers = cdn.get("thumb_servers") or []
        servers = _assign_servers(thumb_servers, len(raw_results))
        results = [_format_gallery_item(item, base) for item, base in zip(raw_results, servers)]
        return {"results": results, "num_pages": data.get("num_pages"), "total": data.get("total")}

    def fav_random(self, api_key=None, anon=False):
        data = self._raw_favorites_random(api_key=api_key, anon=anon)
        return {"id": data.get("id")}

    def search(self, query, sort="date", page=1, api_key=None, anon=False):
        if sort not in VALID_SORTS:
            raise ValueError(f"Invalid sort: {sort}")
        if page < 1:
            raise ValueError("page must be >= 1")
        data = self._raw_search(query, sort, page, api_key=api_key, anon=anon)
        raw_results = (data.get("result") or data.get("results") or [])[:25]
        cdn = self._get_cdn(api_key=api_key, anon=anon)
        thumb_servers = cdn.get("thumb_servers") or []
        if not thumb_servers:
            raise RuntimeError("No thumb_servers returned from /cdn")
        servers = _assign_servers(thumb_servers, len(raw_results))
        results = [_format_gallery_item(item, base) for item, base in zip(raw_results, servers)]
        return {"results": results, "num_pages": data.get("num_pages"), "total": data.get("total")}

    def galleries(self, page=1, per_page=25, sort="date", api_key=None, anon=False):
        if page < 1:
            raise ValueError("page must be >= 1")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        if sort not in VALID_SORTS:
            raise ValueError(f"Invalid sort: {sort}")
        data = self._raw_galleries(page=page, per_page=per_page, sort=sort, api_key=api_key, anon=anon)
        raw_results = (data.get("result") or data.get("results") or [])[:per_page]
        cdn = self._get_cdn(api_key=api_key, anon=anon)
        thumb_servers = cdn.get("thumb_servers") or []
        if not thumb_servers:
            raise RuntimeError("No thumb_servers returned from /cdn")
        servers = _assign_servers(thumb_servers, len(raw_results))
        results = [_format_gallery_item(item, base) for item, base in zip(raw_results, servers)]
        return {
            "results": results,
            "num_pages": data.get("num_pages"),
            "per_page": data.get("per_page"),
            "total": data.get("total"),
        }

    def galleries_by_tag(self, tag_id, page=1, per_page=25, sort="date", api_key=None, anon=False):
        if not isinstance(tag_id, int) or isinstance(tag_id, bool):
            raise ValueError("tag_id must be an int")
        if page < 1:
            raise ValueError("page must be >= 1")
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        if sort not in VALID_SORTS:
            raise ValueError(f"Invalid sort: {sort}")
        data = self._raw_galleries_by_tag(tag_id, page=page, per_page=per_page,
                                          sort=sort, api_key=api_key, anon=anon)
        raw_results = (data.get("result") or data.get("results") or [])[:per_page]
        cdn = self._get_cdn(api_key=api_key, anon=anon)
        thumb_servers = cdn.get("thumb_servers") or []
        if not thumb_servers:
            raise RuntimeError("No thumb_servers returned from /cdn")
        servers = _assign_servers(thumb_servers, len(raw_results))
        results = [_format_gallery_item(item, base) for item, base in zip(raw_results, servers)]
        return {
            "results": results,
            "num_pages": data.get("num_pages"),
            "per_page": data.get("per_page"),
            "total": data.get("total"),
        }

    def popular_galleries(self, api_key=None, anon=False):
        data = self._raw_galleries_popular(api_key=api_key, anon=anon)
        items = data if isinstance(data, list) else (data.get("result") or data.get("results") or [])
        cdn = self._get_cdn(api_key=api_key, anon=anon)
        thumb_servers = cdn.get("thumb_servers") or []
        servers = _assign_servers(thumb_servers, len(items))
        return [_format_gallery_item(item, base) for item, base in zip(items, servers)]

    def random_gallery(self, api_key=None, anon=False):
        data = self._raw_galleries_random(api_key=api_key, anon=anon)
        return {"id": data.get("id")}

    def related_galleries(self, gallery_id, api_key=None, anon=False):
        data = self._raw_gallery_related(gallery_id, api_key=api_key, anon=anon)
        raw_results = data.get("result") or data.get("results") or []
        cdn = self._get_cdn(api_key=api_key, anon=anon)
        thumb_servers = cdn.get("thumb_servers") or []
        servers = _assign_servers(thumb_servers, len(raw_results))
        return [_format_gallery_item(item, base) for item, base in zip(raw_results, servers)]

    def tags_search(self, tag_type, query, limit=50, api_key=None, anon=False):
        data = self._raw_tags_search(tag_type, query, limit, api_key=api_key, anon=anon)
        items = data if isinstance(data, list) else (data.get("result") or data.get("results") or [])
        return [{"id": t.get("id"), "name": t.get("name")} for t in items]

    def tags_by_ids(self, ids, api_key=None, anon=False):
        if isinstance(ids, (int, str)):
            ids = [ids]
        ids = list(ids)
        if not ids:
            return []
        if len(ids) > MAX_TAGS_BY_IDS:
            raise ValueError(f"ids must contain at most {MAX_TAGS_BY_IDS} entries")
        data = self._raw_tags_by_ids(ids, api_key=api_key, anon=anon)
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

    def blacklist(self, api_key=None, anon=False):
        data = self._raw_blacklist_get(api_key=api_key, anon=anon)
        items = data.get("tags") or []
        return {
            "tags": [{"id": t.get("id"), "name": t.get("name")} for t in items],
            "count": data.get("count"),
        }

    def blacklist_update(self, added=None, removed=None, api_key=None, anon=False):
        return self._raw_blacklist_update(added=added, removed=removed, api_key=api_key, anon=anon)

    def gallery(self, gallery_id, include=None, api_key=None, anon=False):
        inc = include if include is not None else "favorite"
        data = self._raw_gallery(gallery_id, include=inc, api_key=api_key, anon=anon)
        title_obj = data.get("title") or {}
        pretty = title_obj.get("pretty")
        eng = title_obj.get("english")
        jp = title_obj.get("japanese")
        title = pretty if pretty not in (None, "") else (eng if eng not in (None, "") else jp)
        cdn = self._get_cdn(api_key=api_key, anon=anon)
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


NHentaiClient._USER_UPDATE_FIELDS = (
    "username", "email", "about", "favorite_tags", "theme",
    "current_password", "new_password", "default_avatar",
)


_default_client: Optional[NHentaiClient] = None
_default_client_lock = threading.Lock()


def _get_default_client() -> NHentaiClient:
    global _default_client
    if _default_client is None:
        with _default_client_lock:
            if _default_client is None:
                _default_client = NHentaiClient()
    return _default_client


def set_api_key(api_key: Optional[str]) -> None:
    global _default_client
    with _default_client_lock:
        if _default_client is not None:
            _default_client.close()
        _default_client = NHentaiClient(api_key=api_key)


def close_client() -> None:
    global _default_client
    with _default_client_lock:
        if _default_client is not None:
            _default_client.close()
            _default_client = None


atexit.register(close_client)


def search(query: str, sort: str = "date", page: int = 1, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().search(query, sort=sort, page=page, api_key=api_key, anon=anon)


def galleries(page: int = 1, per_page: int = 25, sort: str = "date", api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().galleries(page=page, per_page=per_page, sort=sort, api_key=api_key, anon=anon)


def galleries_by_tag(tag_id: int, page: int = 1, per_page: int = 25, sort: str = "date",
                     api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().galleries_by_tag(
        tag_id, page=page, per_page=per_page, sort=sort, api_key=api_key, anon=anon
    )


def popular_galleries(api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().popular_galleries(api_key=api_key, anon=anon)


def random_gallery(api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().random_gallery(api_key=api_key, anon=anon)


def related_galleries(gallery_id, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().related_galleries(gallery_id, api_key=api_key, anon=anon)


def gallery(gallery_id, include: Optional[str] = None, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().gallery(gallery_id, include=include, api_key=api_key, anon=anon)


def user(api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().user(api_key=api_key, anon=anon)


def user_update(username=None, email=None, about=None,
                favorite_tags=None, theme=None,
                current_password=None, new_password=None,
                default_avatar=None,
                api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().user_update(
        username=username, email=email, about=about,
        favorite_tags=favorite_tags, theme=theme,
        current_password=current_password, new_password=new_password,
        default_avatar=default_avatar,
        api_key=api_key, anon=anon,
    )


def user_avatar_upload(file, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().user_avatar_upload(file, api_key=api_key, anon=anon)


def user_keys(api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().user_keys(api_key=api_key, anon=anon)


def get_download_url(gallery_id, fmt: str = "zip", api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().get_download_url(gallery_id, fmt=fmt, api_key=api_key, anon=anon)


def download_gallery(gallery_id, fmt: str = "zip", output_path: Optional[str] = None, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().download_gallery(gallery_id, fmt=fmt, output_path=output_path, api_key=api_key, anon=anon)


def fav_add(gallery_id, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().fav_add(gallery_id, api_key=api_key, anon=anon)


def fav_rm(gallery_id, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().fav_rm(gallery_id, api_key=api_key, anon=anon)


def check_fav(gallery_id, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().check_fav(gallery_id, api_key=api_key, anon=anon)


def fav_list(page: int = 1, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().fav_list(page=page, api_key=api_key, anon=anon)


def fav_random(api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().fav_random(api_key=api_key, anon=anon)


def tags_search(tag_type: str, query: str, limit: int = 50, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().tags_search(tag_type, query, limit=limit, api_key=api_key, anon=anon)


def tags_by_ids(ids, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().tags_by_ids(ids, api_key=api_key, anon=anon)


def blacklist(api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().blacklist(api_key=api_key, anon=anon)


def blacklist_update(added=None, removed=None, api_key: Optional[str] = None, anon: bool = False):
    return _get_default_client().blacklist_update(added=added, removed=removed, api_key=api_key, anon=anon)
