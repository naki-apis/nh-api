import argparse
import json
import os
import re
import sys
import time
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from .client import NHentaiClient, _rate_limiter
from .config import get_api_key, set_api_key, delete_api_key


def _require_auth(api_key):
    if not api_key:
        print(
            "Error: authentication required. Use 'nh-api login nhk_...' (API key) "
            "or 'nh-api login <user_token>' (session token), or pass --api <token>.",
            file=sys.stderr,
        )
        sys.exit(1)


def _print_search_results(data, as_json, header=None, show_links=False):
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if header:
        print(header)
    for i, r in enumerate(data["results"]):
        if i > 0:
            print()
        print("{} {} ({}p)".format(r["id"], r["title"], r.get("num_pages", "?")))
        if show_links:
            thumb = r.get("thumbnail") or {}
            url = thumb.get("url")
            if url:
                print("    " + url)
    print()
    print("Page: {} pages | Total: {} results".format(data.get("num_pages"), data.get("total")))


def _print_gallery(data, as_json, show_links=False):
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    print("{} {}".format(data["id"], data["title"]))
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
    print()
    print("Tags:")
    for ttype, items in data["tags"].items():
        names = ", ".join("{}({})".format(t["name"], t["id"]) for t in items)
        print("  {}: {}".format(ttype, names))
    if show_links:
        thumb = data.get("thumbnail") or {}
        if thumb.get("url"):
            print()
            print("Thumb: {}".format(thumb["url"]))
        print()
        print("Image links:")
        for pg in data["pages"]:
            print(pg["image"]["url"])


def _do_search(args, api_key):
    if args.query_opt:
        query = args.query_opt.strip()
    else:
        query = " ".join(args.query or []).strip()
    if not query:
        print("Error: empty query.", file=sys.stderr)
        sys.exit(1)
    page = args.page if args.page is not None else 1
    key = None if args.anon else (args.api or api_key)
    with NHentaiClient() as client:
        data = client.search(query, sort="date", page=page, api_key=key)
    _print_search_results(data, args.json, show_links=args.image_links)


def _do_gallery(args, api_key):
    key = args.api or api_key
    with NHentaiClient() as client:
        data = client.gallery(args.gallery_id, api_key=key)
    if args.txt:
        base = _build_output_base(".", data["id"], data["title"] or "gallery_{}".format(data["id"]), data.get("tags"))
        out = base + ".txt"
        with open(out, "w", encoding="utf-8") as f:
            for pg in data["pages"]:
                f.write(pg["image"]["url"] + "\n")
        print("Saved: {}".format(out))
        return
    _print_gallery(data, args.json, show_links=args.image_links)


def _download_file(session, url, path):
    attempt = 0
    while True:
        _rate_limiter.wait_host(url)
        try:
            r = session.get(url, stream=True, timeout=60)
            if r.status_code == 443:
                time.sleep(61)
                attempt += 1
                continue
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 61
                time.sleep(wait)
                attempt += 1
                continue
            if r.status_code == 503:
                time.sleep(61)
                attempt += 1
                continue
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return path
        except Exception:
            time.sleep(61)
            attempt += 1


def _do_download_url(args, api_key, fmt):
    key = args.api or api_key
    _require_auth(key)
    ids = _parse_ids(args.gallery_id)
    out_dir = args.download if args.download is not None else None
    if out_dir == "":
        out_dir = "."
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with NHentaiClient() as client:
        for gid in ids:
            info = client.get_download_url(gid, fmt, api_key=key)
            if not out_dir:
                print(json.dumps(info, indent=2, ensure_ascii=False))
                continue
            url = info.get("url")
            if not url:
                print("Error: no URL returned for {}".format(gid), file=sys.stderr)
                continue
            ext = fmt if fmt in ("zip", "cbz", "torrent") else "bin"
            if ext == "cbz":
                ext = "cbz"
            path = os.path.join(out_dir, "{}.{}".format(gid, ext))
            _download_file(client.session, url, path)
            print("Saved: {}".format(path))


def _do_zip(args, api_key):
    _do_download_url(args, api_key, "zip")


def _do_cbz(args, api_key):
    _do_download_url(args, api_key, "cbz")


def _do_torrent(args, api_key):
    _do_download_url(args, api_key, "torrent")


def _do_fav_add(args, api_key):
    key = args.api or api_key
    _require_auth(key)
    with NHentaiClient() as client:
        client.fav_add(args.gallery_id, api_key=key)
    print("Favorited: {}".format(args.gallery_id))


def _do_fav_rm(args, api_key):
    key = args.api or api_key
    _require_auth(key)
    with NHentaiClient() as client:
        client.fav_rm(args.gallery_id, api_key=key)
    print("Unfavorited: {}".format(args.gallery_id))


def _do_fav_list(args, api_key):
    key = args.api or api_key
    _require_auth(key)
    page = args.page if args.page is not None else 1
    with NHentaiClient() as client:
        data = client.fav_list(page=page, api_key=key)
    _print_search_results(data, args.json, header="Favorites (page {})".format(page), show_links=args.image_links)


def _swap_cdn(url, image_servers, attempt):
    for srv in image_servers:
        if srv in url:
            idx = image_servers.index(srv)
            new_idx = (idx + attempt) % len(image_servers)
            return url.replace(srv, image_servers[new_idx])
    return url


def _fetch_image(session, url, image_servers):
    attempt = 0
    while True:
        current = _swap_cdn(url, image_servers, attempt) if attempt else url
        _rate_limiter.wait_host(current)
        try:
            r = session.get(current, timeout=30)
            if r.status_code == 443:
                time.sleep(61)
                attempt += 1
                continue
            if r.status_code == 429:
                time.sleep(61)
                attempt += 1
                continue
            if r.status_code == 503:
                time.sleep(61)
                attempt += 1
                continue
            r.raise_for_status()
            return r.content
        except Exception:
            time.sleep(61)
            attempt += 1


def _parse_ids(raw):
    ids = []
    for token in raw:
        if isinstance(token, int):
            ids.append(token)
            continue
        for part in str(token).split(","):
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


def _build_output_base(output_dir, gid, title, tags):
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
        base = "{} - {} {}".format(cat_str, gid, safe_title)
    else:
        base = "{} - {}".format(gid, safe_title)
    if len(base) > 180:
        base = base[:180]
    return os.path.join(output_dir, base)


def _check_pillow():
    try:
        from PIL import Image  # noqa
        return True
    except Exception:
        return False


def _build_comicinfo_xml(title, authors, subject, keywords, upload_date, gid, page_count):
    import xml.etree.ElementTree as ET
    root = ET.Element("ComicInfo")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
    if title:
        ET.SubElement(root, "Title").text = title
    if authors:
        ET.SubElement(root, "Writer").text = ", ".join(authors)
    if subject:
        ET.SubElement(root, "Genre").text = subject
    if keywords:
        ET.SubElement(root, "Tags").text = keywords
    if upload_date:
        ET.SubElement(root, "Year").text = upload_date[:4]
        ET.SubElement(root, "Month").text = upload_date[5:7]
        ET.SubElement(root, "Day").text = upload_date[8:10]
    ET.SubElement(root, "PageCount").text = str(page_count)
    ET.SubElement(root, "Web").text = "https://nhentai.net/g/{}".format(gid)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _write_cbz(output, results, title=None, authors=None, subject=None, keywords=None, upload_date=None, gid=None):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for num in sorted(results.keys()):
            zf.writestr("{:03d}.jpg".format(num), results[num])
        if title or authors or subject or keywords:
            xml = _build_comicinfo_xml(
                title, authors, subject, keywords, upload_date,
                gid, len(results)
            )
            zf.writestr("ComicInfo.xml", xml)


def _write_raw(output_dir, results):
    os.makedirs(output_dir, exist_ok=True)
    for num in sorted(results.keys()):
        path = os.path.join(output_dir, "{:03d}.jpg".format(num))
        with open(path, "wb") as f:
            f.write(results[num])


def _write_pdf(output, results, title=None, authors=None, subject=None, keywords=None, upload_date=None):
    from PIL import Image
    import io as _io
    from datetime import datetime, timezone
    images = []
    for num in sorted(results.keys()):
        data = results[num]
        try:
            img = Image.open(_io.BytesIO(data))
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)
        except Exception:
            continue
    if not images:
        raise RuntimeError("No valid images to build the PDF")
    meta = {}
    if title:
        meta["title"] = title
    if authors:
        meta["author"] = ", ".join(authors)
    if subject:
        meta["subject"] = subject
    if keywords:
        meta["keywords"] = keywords
    if upload_date:
        try:
            dt = datetime.strptime(upload_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            meta["creationDate"] = dt.strftime("D:%Y%m%d")
            meta["modDate"] = dt.strftime("D:%Y%m%d")
        except Exception:
            pass
    first, rest = images[0], images[1:]
    first.save(output, "PDF", save_all=True, append_images=rest, **meta)


def _resolve_formats(args):
    requested = []
    if args.raw:
        requested.append("raw")
    if args.pdf:
        requested.append("pdf")
    if args.zip:
        requested.append("zip")
    if args.cbz:
        requested.append("cbz")
    if not requested:
        return ["cbz"]
    return requested


class _DownloadQueue:
    def __init__(self):
        self.total = 0
        self.done = 0
        self.failed = 0

    def add(self, n=1):
        self.total += n

    def mark_done(self):
        self.done += 1
        self._print()

    def mark_failed(self):
        self.failed += 1
        self._print()

    def _print(self):
        pct = int(self.done * 100 / self.total) if self.total else 0
        bar = "#" * (pct // 4) + "-" * (25 - pct // 4)
        sys.stdout.write("\r[{}] {}%  ({}/{} links)  failed: {}".format(bar, pct, self.done, self.total, self.failed))
        sys.stdout.flush()


def _save_keepthumb(base, results):
    if 1 in results:
        path = base + ".jpg"
        with open(path, "wb") as f:
            f.write(results[1])
        print("\n[+] Thumb saved: {}".format(path))
    else:
        print("\n[!] -KT: page 001 not downloaded, no thumb saved.", file=sys.stderr)


def _download_one(client, gallery_id, output_dir, formats, queue, keepthumb=False):
    gallery = client.gallery(gallery_id)
    gid = gallery["id"]
    titles = gallery.get("titles") or {}
    title = titles.get("pretty") or titles.get("english") or titles.get("japanese") or gallery.get("title") or "gallery_{}".format(gid)
    base = _build_output_base(output_dir, gid, title, gallery.get("tags"))
    tags = gallery.get("tags") or {}
    authors = [t.get("name") for t in tags.get("artist", []) if t.get("name")]
    subject_tags = []
    keyword_tags = []
    for ttype, items in tags.items():
        for t in items:
            name = t.get("name")
            if not name:
                continue
            if ttype == "tag":
                keyword_tags.append(name)
            if ttype in ("category", "group", "parody", "character", "language"):
                subject_tags.append(name)
    subject = ", ".join(subject_tags) if subject_tags else None
    keywords = ", ".join(keyword_tags) if keyword_tags else None
    pages = gallery["pages"]
    image_servers = gallery.get("_image_servers") or ["https://i1.nhentai.net", "https://i2.nhentai.net", "https://i3.nhentai.net", "https://i4.nhentai.net"]
    print("[*] [{}] {} ({} pages)".format(gid, title, len(pages)))
    queue.add(len(pages))
    results = {}
    with ThreadPoolExecutor(max_workers=min(50, max(1, len(pages)))) as executor:
        futures = {}
        for pg in pages:
            url = pg["image"]["url"]
            if not url:
                queue.mark_failed()
                continue
            futures[executor.submit(_fetch_image, client.session, url, image_servers)] = pg["number"]
        for future in as_completed(futures):
            num = futures[future]
            try:
                data = future.result()
                if data:
                    results[num] = data
                    queue.mark_done()
                else:
                    queue.mark_failed()
            except Exception:
                queue.mark_failed()
    for fmt in formats:
        if fmt == "cbz":
            output = base + ".cbz"
            _write_cbz(
                output, results,
                title=title,
                authors=authors,
                subject=subject,
                keywords=keywords,
                upload_date=gallery.get("upload_date"),
                gid=gid,
            )
            print("\n[+] Saved: {}  ({}/{} images)".format(output, len(results), len(pages)))
        elif fmt == "raw":
            _write_raw(base, results)
            print("\n[+] Saved: {}/  ({}/{} images)".format(base, len(results), len(pages)))
        elif fmt == "pdf":
            output = base + ".pdf"
            _write_pdf(
                output, results,
                title=title,
                authors=authors,
                subject=subject,
                keywords=keywords,
                upload_date=gallery.get("upload_date"),
            )
            print("\n[+] Saved: {}  ({}/{} images)".format(output, len(results), len(pages)))
        elif fmt == "zip":
            output = base + ".zip"
            _write_cbz(
                output, results,
                title=title,
                authors=authors,
                subject=subject,
                keywords=keywords,
                upload_date=gallery.get("upload_date"),
                gid=gid,
            )
            print("\n[+] Saved: {}  ({}/{} images)".format(output, len(results), len(pages)))
    if keepthumb:
        _save_keepthumb(base, results)


def _do_download(args, api_key):
    ids = _parse_ids(args.gallery_id)
    output_dir = args.output or "."
    os.makedirs(output_dir, exist_ok=True)
    formats = _resolve_formats(args)
    if "pdf" in formats and not _check_pillow():
        print("Error: Pillow is required for PDF output. Install it with: pip install Pillow", file=sys.stderr)
        sys.exit(1)
    queue = _DownloadQueue()
    with NHentaiClient() as client:
        for gid in ids:
            try:
                _download_one(client, gid, output_dir, formats, queue, keepthumb=args.keepthumb)
            except Exception as e:
                print("\n[!] Error with {}: {}".format(gid, e), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        prog="nh-api",
        description="CLI client for the nhentai v2 API. Search, view galleries, manage favorites and download CBZ/PDF/RAW files.",
        epilog="Examples:\n"
               "  nh-api login nhk_xxxxxxxx\n"
               "  nh-api login <user_token_from_cookies>\n"
               "  nh-api search language:english catgirl\n"
               "  nh-api search -q 'pages:<5 inuboshi'\n"
               "  nh-api search \"language:english catgirl\"\n"
               "  nh-api search catgirl -p 2\n"
               "  nh-api search catgirl -i\n"
               "  nh-api search catgirl --anon\n"
               "  nh-api search catgirl --api nhk_xxxxxxxx\n"
               "  nh-api code 12345\n"
               "  nh-api code 12345 -i\n"
               "  nh-api code 12345 -txt\n"
               "  nh-api dl 12345\n"
               "  nh-api dl 12345 --raw\n"
               "  nh-api dl 12345 --pdf\n"
               "  nh-api dl 12345 --raw --pdf\n"
               "  nh-api dl 12345 --pdf --cbz\n"
               "  nh-api dl 1,2,3 -o ~/Downloads\n"
               "  nh-api dl 1 2 3 -o ~/Downloads\n"
               "  nh-api zip 1,2,3 -d ~/Downloads\n"
               "  nh-api zip 1,2,3 -d\n"
               "  nh-api cbz 1 2 3 -d ~/Downloads\n"
               "  nh-api torrent 1,2,3 -d\n"
               "  nh-api fav add 12345\n"
               "  nh-api fav list\n"
               "  nh-api logout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_search = sub.add_parser(
        "search",
        aliases=["s"],
        help="Search galleries by query",
        description="Search nhentai using one or more query terms. Use -q/--query to pass the query as a single string (recommended when using operators like pages:<5). Use -p to select the page. Use -i to also print the thumbnail of each result.",
    )
    p_search.add_argument("query", nargs="*", help="One or more search terms (no quotes needed unless using shell operators)")
    p_search.add_argument("-q", "--query", dest="query_opt", default=None, help="Full query as a single string (e.g. 'pages:<5 inuboshi')")
    p_search.add_argument("-p", "--page", type=int, default=None, help="Page of results (default: 1)")
    p_search.add_argument("-i", "--image-links", action="store_true", dest="image_links", help="Also print the thumbnail of each result")
    p_search.add_argument("--anon", action="store_true", help="Ignore the saved token and run the search anonymously")
    p_search.add_argument("--api", default=None, help="Token to use for this call only (nhk_... API key or user session token)")
    p_search.set_defaults(func=_do_search)

    p_code = sub.add_parser(
        "code",
        aliases=["g"],
        help="Show gallery info by ID",
        description="Fetch and display info for a gallery by its numeric ID. Use -i to also print the thumbnail and the image links, or -txt to save the links to a .txt file.",
    )
    p_code.add_argument("gallery_id", type=int, help="Gallery numeric ID (e.g. 12345)")
    p_code.add_argument("-i", "--image-links", action="store_true", dest="image_links", help="Also print the thumbnail and the image links")
    p_code.add_argument("-txt", "--txt", action="store_true", dest="txt", help="Save the image links to a .txt file (same naming format as 'dl')")
    p_code.add_argument("--api", default=None, help="Token to use for this call only")
    p_code.set_defaults(func=_do_gallery)

    p_zip = sub.add_parser(
        "zip",
        aliases=["z"],
        help="Get or download a ZIP (requires auth)",
        description="Ask the API for a temporary ZIP URL, or download the ZIP directly with -d DIR. Accepts one or more IDs (comma-separated or space-separated).",
    )
    p_zip.add_argument("gallery_id", nargs="+", help="One or more gallery IDs (e.g. 12345 or 1,2,3 or 1 2 3)")
    p_zip.add_argument(
        "-d", "--download",
        nargs="?",
        const=".",
        default=None,
        help="Download the file(s) to this directory. If no value is given, uses the current directory. Without -d, prints the URL.",
    )
    p_zip.add_argument("--api", default=None, help="Token to use for this call only")
    p_zip.set_defaults(func=_do_zip)

    p_cbz = sub.add_parser(
        "cbz",
        aliases=["c"],
        help="Get or download a CBZ (requires auth)",
        description="Ask the API for a temporary CBZ URL, or download the CBZ directly with -d DIR. Accepts one or more IDs (comma-separated or space-separated).",
    )
    p_cbz.add_argument("gallery_id", nargs="+", help="One or more gallery IDs (e.g. 12345 or 1,2,3 or 1 2 3)")
    p_cbz.add_argument(
        "-d", "--download",
        nargs="?",
        const=".",
        default=None,
        help="Download the file(s) to this directory. If no value is given, uses the current directory. Without -d, prints the URL.",
    )
    p_cbz.add_argument("--api", default=None, help="Token to use for this call only")
    p_cbz.set_defaults(func=_do_cbz)

    p_torrent = sub.add_parser(
        "torrent",
        aliases=["t"],
        help="Get or download a torrent (requires auth)",
        description="Ask the API for a temporary torrent URL, or download the .torrent directly with -d DIR. Accepts one or more IDs (comma-separated or space-separated).",
    )
    p_torrent.add_argument("gallery_id", nargs="+", help="One or more gallery IDs (e.g. 12345 or 1,2,3 or 1 2 3)")
    p_torrent.add_argument(
        "-d", "--download",
        nargs="?",
        const=".",
        default=None,
        help="Download the file(s) to this directory. If no value is given, uses the current directory. Without -d, prints the URL.",
    )
    p_torrent.add_argument("--api", default=None, help="Token to use for this call only")
    p_torrent.set_defaults(func=_do_torrent)

    p_dl = sub.add_parser(
        "download",
        aliases=["dl"],
        help="Download galleries (no API key required)",
        description="Download one or more galleries. Default output is .cbz. You can combine any of --raw, --pdf, --zip and --cbz to produce multiple outputs from a single download. If any format flag is used, --cbz is no longer implicit unless you also pass --cbz explicitly. Accepts a single ID, a comma-separated list, or space-separated IDs.",
    )
    p_dl.add_argument("gallery_id", nargs="+", help="One or more gallery IDs (e.g. 12345 or 1,2,3 or 1 2 3)")
    p_dl.add_argument("-o", "--output", default=None, help="Output directory (default: current directory)")
    p_dl.add_argument("--raw", action="store_true", help="Save individual images into a folder instead of a CBZ")
    p_dl.add_argument("--pdf", action="store_true", help="Build a PDF using Pillow (must be installed)")
    p_dl.add_argument("--zip", action="store_true", help="Save a ZIP archive")
    p_dl.add_argument("--cbz", action="store_true", help="Save a CBZ archive (default if no other format is used)")
    p_dl.add_argument("--keepthumb", "-KT", action="store_true", dest="keepthumb", help=argparse.SUPPRESS)
    p_dl.set_defaults(func=_do_download)

    p_fav = sub.add_parser(
        "fav",
        aliases=["f"],
        help="Manage favorites (requires auth)",
        description="Add, remove or list favorites. Requires a token saved with 'nh-api login' (API key or user session) or passed with --api.",
    )
    fav_sub = p_fav.add_subparsers(dest="fav_cmd", metavar="<subcommand>")

    p_fav_add = fav_sub.add_parser(
        "add",
        aliases=["a"],
        help="Add a gallery to favorites",
        description="Mark a gallery as favorite. Requires a token saved with 'nh-api login' or passed with --api.",
    )
    p_fav_add.add_argument("gallery_id", type=int, help="Gallery numeric ID")
    p_fav_add.add_argument("--api", default=None, help="Token to use for this call only")
    p_fav_add.set_defaults(func=_do_fav_add)

    p_fav_rm = fav_sub.add_parser(
        "rm",
        aliases=["r"],
        help="Remove a gallery from favorites",
        description="Remove a gallery from your favorites. Requires a token saved with 'nh-api login' or passed with --api.",
    )
    p_fav_rm.add_argument("gallery_id", type=int, help="Gallery numeric ID")
    p_fav_rm.add_argument("--api", default=None, help="Token to use for this call only")
    p_fav_rm.set_defaults(func=_do_fav_rm)

    p_fav_list = fav_sub.add_parser(
        "list",
        aliases=["l"],
        help="List your favorites",
        description="List favorites page by page. Use -i to also print the thumbnail of each result. Requires auth.",
    )
    p_fav_list.add_argument("page", nargs="?", type=int, default=None, help="Page number (default: 1)")
    p_fav_list.add_argument("-i", "--image-links", action="store_true", dest="image_links", help="Also print the thumbnail of each result")
    p_fav_list.add_argument("--api", default=None, help="Token to use for this call only")
    p_fav_list.set_defaults(func=_do_fav_list)

    p_login = sub.add_parser(
        "login",
        help="Save an auth token",
        description="Store an nhentai token locally. Accepts an API key (nhk_...) or a user session token from your browser cookies. The client auto-detects which one it is.",
    )
    p_login.add_argument("api_key", help="API key (nhk_...) or user session token")
    p_login.set_defaults(func=lambda a, k: (set_api_key(a.api_key), print("Token saved.")))

    p_logout = sub.add_parser(
        "logout",
        help="Remove the saved token",
        description="Delete the locally stored token.",
    )
    p_logout.set_defaults(func=lambda a, k: print("Token removed." if delete_api_key() else "No token stored."))

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
