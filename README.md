# nh-api

CLI client and Python library for the nhentai v2 API.

## Install

    pip install git+https://github.com/YOUR_USER/nh-api.git

Or from a local clone:

    git clone https://github.com/YOUR_USER/nh-api.git
    cd nh-api
    pip install -e .

## CLI usage

    nh-api login nhk_YOUR_API_KEY
    nh-api search "language:english catgirl"
    nh-api search "language:english catgirl" 2
    nh-api code 1
    nh-api dl 1
    nh-api dl 1,2,3
    nh-api dl 1 -o ~/Downloads
    nh-api zip 1
    nh-api cbz 1
    nh-api torrent 1
    nh-api fav add 1
    nh-api fav list
    nh-api fav list 2
    nh-api fav rm 1
    nh-api logout

## Library usage

    from nhentai import NHentaiClient, get_api_key

    with NHentaiClient(api_key=get_api_key()) as client:
        data = client.search("catgirl", page=1)
        for r in data["results"]:
            print(r["id"], r["title"])

All methods accept an optional `api_key=` parameter that overrides the
client's session key for that single call.

## License

MIT
