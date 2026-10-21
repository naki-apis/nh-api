from .client import (
    NHentaiClient,
    user,
    user_update,
    user_avatar_upload,
    user_keys,
    search,
    gallery,
    galleries,
    galleries_by_tag,
    popular_galleries,
    random_gallery,
    related_galleries,
    tags_search,
    tags_by_ids,
    blacklist,
    blacklist_update,
    get_download_url,
    download_gallery,
    fav_add,
    fav_rm,
    fav_list,
    fav_random,
    check_fav,
    set_api_key as _set_api_key_client,
    close_client,
)
from .config import get_api_key, set_api_key, delete_api_key

__all__ = [
    "NHentaiClient",
    "get_api_key",
    "set_api_key",
    "delete_api_key",
    "user",
    "user_update",
    "user_avatar_upload",
    "user_keys",
    "search",
    "gallery",
    "galleries",
    "galleries_by_tag",
    "popular_galleries",
    "random_gallery",
    "related_galleries",
    "tags_search",
    "tags_by_ids",
    "blacklist",
    "blacklist_update",
    "get_download_url",
    "download_gallery",
    "fav_add",
    "fav_rm",
    "fav_list",
    "fav_random",
    "check_fav",
    "close_client",
]


def _resolve_key(api_key: str = None, anon: bool = False) -> str:
    if anon:
        return None
    return api_key or get_api_key()


def user(api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.user()


def user_update(username=None, email=None, about=None,
                favorite_tags=None, theme=None,
                current_password=None, new_password=None,
                default_avatar=None,
                api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.user_update(
            username=username, email=email, about=about,
            favorite_tags=favorite_tags, theme=theme,
            current_password=current_password, new_password=new_password,
            default_avatar=default_avatar,
        )


def user_avatar_upload(file, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.user_avatar_upload(file)


def user_keys(api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.user_keys()


def search(query: str, sort: str = "date", page: int = 1, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.search(query, sort=sort, page=page)


def gallery(gallery_id: int, include: str = None, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.gallery(gallery_id, include=include)


def galleries(page: int = 1, per_page: int = 25, sort: str = "date", api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.galleries(page=page, per_page=per_page, sort=sort)


def galleries_by_tag(tag_id: int, page: int = 1, per_page: int = 25, sort: str = "date",
                     api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.galleries_by_tag(tag_id, page=page, per_page=per_page, sort=sort)


def popular_galleries(api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.popular_galleries()


def random_gallery(api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.random_gallery()


def related_galleries(gallery_id: int, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.related_galleries(gallery_id)


def tags_search(tag_type: str, query: str, limit: int = 50, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.tags_search(tag_type, query, limit=limit)


def tags_by_ids(ids, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.tags_by_ids(ids)


def blacklist(api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.blacklist()


def blacklist_update(added=None, removed=None, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.blacklist_update(added=added, removed=removed)


def get_download_url(gallery_id: int, fmt: str = "zip", api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.get_download_url(gallery_id, fmt=fmt)


def download_gallery(gallery_id: int, fmt: str = "zip", output_path: str = None, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.download_gallery(gallery_id, fmt=fmt, output_path=output_path)


def fav_add(gallery_id: int, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.fav_add(gallery_id)


def fav_rm(gallery_id: int, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.fav_rm(gallery_id)


def check_fav(gallery_id: int, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.check_fav(gallery_id)


def fav_list(page: int = 1, api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.fav_list(page=page)


def fav_random(api_key: str = None, anon: bool = False):
    with NHentaiClient(api_key=_resolve_key(api_key, anon)) as client:
        return client.fav_random()
