from .client import NHentaiClient
from .config import get_api_key, set_api_key, delete_api_key

__all__ = ["NHentaiClient", "get_api_key", "set_api_key", "delete_api_key"]


def search(query: str, sort: str = "date", page: int = 1, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.search(query, sort=sort, page=page)


def gallery(gallery_id: int, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.gallery(gallery_id)


def galleries(page: int = 1, per_page: int = 25, sort: str = "date", api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.galleries(page=page, per_page=per_page, sort=sort)


def tags_search(tag_type: str, query: str, limit: int = 50, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.tags_search(tag_type, query, limit=limit)


def tags_by_ids(ids, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.tags_by_ids(ids)


def blacklist(api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.blacklist()


def blacklist_update(added=None, removed=None, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.blacklist_update(added=added, removed=removed)


def get_download_url(gallery_id: int, fmt: str = "zip", api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.get_download_url(gallery_id, fmt=fmt)


def download_gallery(gallery_id: int, fmt: str = "zip", output_path: str = None, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.download_gallery(gallery_id, fmt=fmt, output_path=output_path)


def fav_add(gallery_id: int, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.fav_add(gallery_id)


def fav_rm(gallery_id: int, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.fav_rm(gallery_id)


def fav_list(page: int = 1, api_key: str = None, anon: bool = False):
    key = None if anon else (api_key or get_api_key())
    with NHentaiClient(api_key=key) as client:
        return client.fav_list(page=page)
