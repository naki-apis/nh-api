import argparse
import json
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from .client import NHentaiClient
from .config import get_api_key, set_api_key, delete_api_key


def _require_api(api_key):
    if not api_key:
        print("Error: API key required. Use nh-api login nhk_... first.", file=sys.stderr)
        sys.exit(1)


def _print_search_results(data, as_json, header=None):
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if header:
        print(header)
    for r in data["results"]:
        print("[{}] {} ({}p)".format(r["id"], r["title"], r["num_pages"]))
        if r["thumbnail"]["url"]:
            print("    " + r["thumbnail"]["url"])
    print()
    print("Page: {} pages | Total: {} results".format(data.get("num_pages"), data.get("total")))


def _print_gallery(data, as_json):
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print("[{}] {}".format(data["id"], data["title"]))
    titles = data.get("titles") or {}
    if titles.get("english") and titles.get("english") != data["title"]:
        print("English: {}".format(titles["english"]))
    if titles.get("japanese"):
        print("Japanese: {}".format(titles["japanese"]))
    fav = data.get("is_favorited")
    if fav is True:
        print("Favorited: yes")
    elif fav is False:
        print("Favorited: no")
    print("Date: {}".format(data["upload_date"]))
    print("Pages: {} | Favorites: {}".format(data["num_pages"], data["num_favorites"]))
    if data.get("scanlator"):
        print("Scanlator: {}".format(data["scanlator"]))
    print("Cover: {}".format(data["cover"]["url"]))
    print("Thumb: {}".format(data["thumbnail"]["url"]))
    print()
    print("Tags:")
    for ttype, items in data["tags"].items():
        names = ", ".join("{}({})".format(t["name"], t["id"]) for t in items)
        print("  {}: {}".format(ttype, names))
    print()
    print("Pages:")
    for pg in data["pages"]:
        print("  #{}: {}".format(pg["number"], pg["image"]["url"]))


def _do_search(args, api_key):
    query = args.query
    page = args.page if args.page is not None else 1
    with NHentaiClient(api_key=api_key) as client:
        data = client.search(query, sort="date", page=page)
    _print_search_results(data, args.json)


def _do_gallery(args, api_key):
    with NHentaiClient(api_key=api_key) as client:
        data = client.gallery(args.gallery_id)
    _print_gallery(data, args.json)


def _do_zip(args, api_key):
    _require_api(api_key)
    with NHentaiClient(api_key=api_key) as client:
        info = client.get_download_url(args.gallery_id, "zip")
    print(json.dumps(info, indent=2, ensure_ascii=False))


def _do_cbz(args, api_key):
    _require_api(api_key)
    with NHentaiClient(api_key=api_key) as client:
        info = client.get_download_url(args.gallery_id, "cbz")
    print(json.dumps(info, indent=2, ensure_ascii=False))


def _do_torrent(args, api_key):
    _require_api(api_key)
    with NHentaiClient(api_key=api_key) as client:
        info = client.get_download_url(args.gallery_id, "torrent")
    print(json.dumps(info, indent=2, ensure_ascii=False))


def _do_fav_add(args, api_key):
    _require_api(api_key)
    with NHentaiClient(api_key=api_key) as client:
        client.fav_add(args.gallery_id)
    print("Favorited: {}".format(args.gallery_id))


def _do_fav_rm(args, api_key):
    _require_api(api_key)
    with NHentaiClient(api_key=api_key) as client:
        client.fav_rm(args.gallery_id)
    print("Unfavorited: {}".format(args.gallery_id))


def _do_fav_list(args, api_key):
    _require_api(api_key)
    page = args.page if args.page is not None else 1
    with NHentaiClient(api_key=api_key) as client:
        data = client.fav_list(page=page)
    _print_search_results(data, args.json, header="Favorites (page {})".format(page))


def _swap_cdn(url, image_servers, attempt):
    for srv in image_servers:
        if srv in url:
            idx = image_servers.index(srv)
            new_idx = (idx + attempt) % len(image_servers)
            return url.replace(srv, image_servers[new_idx])
    return url


def _download_single_page(session, url, image_servers, retries=4):
    last_err = None
    for attempt in range(retries):
        current = _swap_cdn(url, image_servers, attempt) if attempt else url
        try:
            r = session.get(current, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    raise last_err


def _parse_ids(raw):
    ids = []
    for token in raw:
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                raise ValueError("Invalid ID: {}".format(part))
    return ids


def _safe_filename(title, gid):
    safe = re.sub(r"[\x00-\x1f/\\\\:*?\"<>|]", "_", title)
    safe = safe.strip().rstrip(".")
    if not safe:
        safe = "gallery_{}".format(gid)
    return safe


def _build_output_path(output_dir, gid, title, tags, ext=".cbz"):
    tags = tags or {}
    artists = [t.get("name") for t in tags.get("artist", []) if t.get("name")]
    groups = [t.get("name") for t in tags.get("group", []) if t.get("name")]
    if not artists or len(artists) > 5:
        chosen = groups if groups else artists
    else:
        chosen = artists
    seen = []
    for name in chosen:
        if name and name not in seen:
            seen.append(name)
    cat_str = "-".join(seen)
    safe_title = _safe_filename(title, gid)
    if cat_str:
        base = "{} - {} {}".format(gid, cat_str, safe_title)
    else:
        base = "{} - {}".format(gid, safe_title)
    if len(base) > 180:
        base = base[:180]
    return os.path.join(output_dir, base + ext)


def _download_one(client, gallery_id, output_dir):
    gallery = client.gallery(gallery_id)
    gid = gallery["id"]
    title = gallery["title"] or "gallery_{}".format(gid)
    output = _build_output_path(output_dir, gid, title, gallery.get("tags"))
    pages = gallery["pages"]
    image_servers = gallery.get("_image_servers") or ["https://i1.nhentai.net", "https://i2.nhentai.net", "https://i3.nhentai.net", "https://i4.nhentai.net"]
    total = len(pages)
    results = {}
    failed = []
    completed = 0
    print("[*] [{}] {} ({} pages)".format(gid, title, total))
    with ThreadPoolExecutor(max_workers=min(50, total)) as executor:
        futures = {}
        for pg in pages:
            futures[executor.submit(_download_single_page, client.session, pg["image"]["url"], image_servers)] = pg["number"]
        for future in as_completed(futures):
            num = futures[future]
            try:
                results[num] = future.result()
            except Exception as e:
                failed.append((num, str(e)))
            completed += 1
            pct = int(completed * 100 / total)
            bar = "#" * (pct // 4) + "-" * (25 - pct // 4)
            sys.stdout.write("\r[{}] {}%  ({}/{})  failed: {}".format(bar, pct, completed, total, len(failed)))
            sys.stdout.flush()
    sys.stdout.write("\n")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for num in sorted(results.keys()):
            zf.writestr("{:03d}.jpg".format(num), results[num])
    print("[+] Saved: {}  ({}/{} images)".format(output, len(results), total))
    if failed:
        print("[!] Failed {} pages: {}".format(len(failed), ", ".join(str(n) for n, _ in failed)))
    return output, len(results), len(failed)


def _do_download(args, api_key):
    ids = _parse_ids(args.gallery_id)
    output_dir = args.output or "."
    os.makedirs(output_dir, exist_ok=True)
    with NHentaiClient(api_key=api_key) as client:
        for gid in ids:
            try:
                _download_one(client, gid, output_dir)
            except Exception as e:
                print("[!] Error with {}: {}".format(gid, e), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(prog="nh-api")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p_search = sub.add_parser("search")
    p_search.add_argument("query", type=str, help="Search query (use quotes)")
    p_search.add_argument("page", nargs="?", type=int, default=None, help="Page number")
    p_search.set_defaults(func=_do_search)

    p_code = sub.add_parser("code")
    p_code.add_argument("gallery_id", type=int)
    p_code.set_defaults(func=_do_gallery)

    p_zip = sub.add_parser("zip")
    p_zip.add_argument("gallery_id", type=int)
    p_zip.set_defaults(func=_do_zip)

    p_cbz = sub.add_parser("cbz")
    p_cbz.add_argument("gallery_id", type=int)
    p_cbz.set_defaults(func=_do_cbz)

    p_torrent = sub.add_parser("torrent")
    p_torrent.add_argument("gallery_id", type=int)
    p_torrent.set_defaults(func=_do_torrent)

    p_dl = sub.add_parser("download")
    p_dl.add_argument("gallery_id", nargs="+")
    p_dl.add_argument("-o", "--output", default=None)
    p_dl.set_defaults(func=_do_download)

    p_dl2 = sub.add_parser("dl")
    p_dl2.add_argument("gallery_id", nargs="+")
    p_dl2.add_argument("-o", "--output", default=None)
    p_dl2.set_defaults(func=_do_download)

    p_fav = sub.add_parser("fav")
    fav_sub = p_fav.add_subparsers(dest="fav_cmd")

    p_fav_add = fav_sub.add_parser("add")
    p_fav_add.add_argument("gallery_id", type=int)
    p_fav_add.set_defaults(func=_do_fav_add)

    p_fav_rm = fav_sub.add_parser("rm")
    p_fav_rm.add_argument("gallery_id", type=int)
    p_fav_rm.set_defaults(func=_do_fav_rm)

    p_fav_list = fav_sub.add_parser("list")
    p_fav_list.add_argument("page", nargs="?", type=int, default=None)
    p_fav_list.set_defaults(func=_do_fav_list)

    p_login = sub.add_parser("login")
    p_login.add_argument("api_key")
    p_login.set_defaults(func=lambda a, k: (set_api_key(a.api_key), print("API key saved.")))

    p_logout = sub.add_parser("logout")
    p_logout.set_defaults(func=lambda a, k: print("API key removed." if delete_api_key() else "No API key stored."))

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    if args.command == "fav" and not getattr(args, "fav_cmd", None):
        p_fav.print_help()
        sys.exit(1)
    api_key = get_api_key()
    try:
        args.func(args, api_key)
    except Exception as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
