# nh-api

CLI client and Python library for the nhentai v2 API.

## Install

    pip install git+https://github.com/naki-apis/nh-api.git

Or from a local clone:

    git clone https://github.com/naki-apis/nh-api.git
    cd nh-api
    pip install -e .

For PDF output support, install the optional dependency:

    pip install Pillow

## CLI usage

### Authentication

    nh-api login nhk_YOUR_API_KEY
    nh-api login YOUR_USER_SESSION_TOKEN
    nh-api logout

Tokens are stored locally. Both API keys (`nhk_...`) and user session tokens
(from your browser cookies) are accepted; the client auto-detects which one
it is.

### Search

    nh-api search catgirl
    nh-api search "language:english catgirl"
    nh-api search -q "pages:>150 language:english"
    nh-api search catgirl -p 2
    nh-api search catgirl -i
    nh-api search catgirl --anon
    nh-api search catgirl --api nhk_xxxxxxxx

Options:

- `-q, --query` — pass the whole query as a single string. Useful when the
  query contains shell operators like `<`, `>`, or spaces that would
  otherwise be split by the shell.
- `-p, --page` — page of results to fetch (default: `1`). Each page
  contains up to 25 results.
- `-i, --image-links` — also print the thumbnail URL of each result,
  in addition to the ID and title.
- `--anon` — ignore the saved token and run the search anonymously. Useful
  to check what results look like without your account's blacklist or
  favorites context.
- `--api TOKEN` — use this token for this single call only, without
  touching the saved token. Accepts an API key (`nhk_...`) or a user
  session token.


### Gallery info

    nh-api code 12345
    nh-api code 12345 -i
    nh-api code 12345 -txt

### Downloads

The `download` command (alias `dl`) does not require an API key and defaults
to CBZ output. You can combine any of `--raw`, `--pdf`, `--zip` and `--cbz`
to produce multiple outputs from a single download. You need install Pillow for use PDF download. You can use --keepthumb (-KT) for save the thumb picture.

    nh-api dl 12345
    nh-api dl 12345 --raw
    nh-api dl 12345 --pdf
    nh-api dl 12345 --raw --pdf
    nh-api dl 12345 --pdf --cbz
    nh-api dl 1,2,3 -o ~/Downloads
    nh-api dl 1 2 3 -o ~/Downloads
    nh-api dl 12345 --keepthumb

The CBZ and ZIP outputs embed a `ComicInfo.xml` file with metadata (title,
writer, genre, year/month/day, page count, source URL). The PDF output
embeds the same metadata as native PDF document properties.

### Direct download URLs (requires auth)

    nh-api zip 1,2,3
    nh-api zip 1,2,3 -d ~/Downloads
    nh-api zip 1,2,3 -d
    nh-api cbz 1 2 3 -d ~/Downloads
    nh-api torrent 1,2,3 -d

Without `-d`, the command prints the temporary download URL. With `-d DIR`
(or just `-d` for the current directory), it downloads the file directly.

### Favorites (requires auth)

    nh-api fav add 12345
    nh-api fav rm 12345
    nh-api fav list
    nh-api fav list 2
    nh-api fav list -i

## Library usage

### Client

    from nhentai import NHentaiClient, get_api_key

    with NHentaiClient(api_key=get_api_key()) as client:
        data = client.search("catgirl", page=1)
        for r in data["results"]:
            print(r["id"], r["title"])

All client methods accept an optional `api_key=` parameter that overrides the
client's session key for that single call.

### Module-level helpers

The package exposes convenience functions that create a client, run the
call, and close it automatically. Every helper accepts `api_key=` and
`anon=` keyword arguments. Use `anon=True` to ignore the saved token and run
the call anonymously, or `api_key=` to override the token for that single
call.

    from nhentai import search, gallery, fav_add, fav_list

    data = search("catgirl", page=1)
    info = gallery(12345)
    fav_add(12345, api_key="nhk_xxxxxxxx")
    favorites = fav_list(page=1)

#### User

    from nhentai import user, user_update, user_avatar_upload, user_keys

    me = user()
    user_update(username="new_name", about="hello", theme="dark")
    user_avatar_upload(open("avatar.png", "rb"))
    keys = user_keys()

- `user()` returns the authenticated user's profile.
- `user_update(...)` updates profile fields (`username`, `email`, `about`,
  `favorite_tags`, `theme`, `current_password`, `new_password`,
  `default_avatar`). Only pass the fields you want to change.
- `user_avatar_upload(file)` uploads a new avatar from a file-like object.
- `user_keys()` lists the API keys associated with the account.

#### Search and browse

    from nhentai import (
        search, gallery, galleries, galleries_by_tag,
        popular_galleries, random_gallery, related_galleries,
    )

    results = search("catgirl", sort="date", page=1)
    info = gallery(12345)
    listing = galleries(page=1, per_page=25, sort="date")
    by_tag = galleries_by_tag(1234, page=1)
    popular = popular_galleries()
    rand = random_gallery()
    related = related_galleries(12345)

- `search(query, sort="date", page=1)` runs a text search.
  Valid `sort` values: `date`, `popular`, `popular-today`, `popular-week`, `popular-month`. Default: `date`.
- `gallery(gallery_id, include=None)` returns full gallery info. Pass
  `include` as a list of extra fields to request from the API. Valid values:
  `comments`, `related`, `favorite`, `suggestions`.
- `galleries(page, per_page, sort)` lists galleries with pagination.
  `per_page` must be between `1` and `100`; values above `100` raise
  `ValueError`. `sort` accepts the same values as `search`.
- `galleries_by_tag(tag_id, page, per_page, sort)` lists galleries for a tag.
  Same `per_page` (`1–100`) and `sort` constraints as `galleries`.

#### Tags

    from nhentai import tags_search, tags_by_ids

    found = tags_search("tag", "catgirl", limit=50)
    tags = tags_by_ids([1234, 5678])

- `tags_search(tag_type, query, limit=50)` searches tags of a given type
  (`tag`, `artist`, `group`, `parody`, `character`, `category`, `language`).
- `tags_by_ids(ids)` resolves a list of tag IDs to tag objects.

#### Blacklist

    from nhentai import blacklist, blacklist_update

    current = blacklist()
    blacklist_update(added=[1234], removed=[5678])

- `blacklist()` returns the current blacklist.
- `blacklist_update(added=None, removed=None)` adds and/or removes tag IDs.

#### Downloads

    from nhentai import get_download_url, download_gallery

    url = get_download_url(12345, fmt="cbz")
    path = download_gallery(12345, fmt="zip", output_path="~/Downloads")

- `get_download_url(gallery_id, fmt="zip")` returns the temporary download
  URL. `fmt` can be `zip`, `cbz`, or `torrent`.
- `download_gallery(gallery_id, fmt="zip", output_path=None)` downloads the
  file directly and returns the local path.

#### Favorites

    from nhentai import fav_add, fav_rm, fav_list, fav_random, check_fav

    fav_add(12345)
    fav_rm(12345)
    favorites = fav_list(page=1)
    one_random = fav_random()
    is_fav = check_fav(12345)

- `fav_add(gallery_id)` marks a gallery as favorite.
- `fav_rm(gallery_id)` removes it from favorites.
- `fav_list(page=1)` lists favorites with pagination.
- `fav_random()` returns a random favorite.
- `check_fav(gallery_id)` returns whether the gallery is favorited.

#### Token management

    from nhentai import get_api_key, set_api_key, delete_api_key

    set_api_key("nhk_xxxxxxxx")
    key = get_api_key()
    delete_api_key()

- `set_api_key(token)` stores a token locally.
- `get_api_key()` returns the stored token (or `None`).
- `delete_api_key()` removes the stored token and returns `True` if one
  existed.

## License

MIT
