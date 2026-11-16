"""Stand-ins for switch-library-manager-web, Prowlarr and NZBGet, in one small web app.

Used by the tests, and runnable by itself to try the panel without the real services:
    python tests/fakes.py            (listens on port 9000)
"""
import base64

from aiohttp import web

NZB = b'<?xml version="1.0"?><nzb xmlns="http://www.newzbin.com/DTD/2003/nzb"></nzb>'


def title(game_id, name, local, latest, version=None, dlc=()):
    return {
        "id": game_id, "name": name, "version": version, "localUpdate": local, "latestUpdate": latest,
        "updateMissing": local < latest, "dlcOwned": 0,
        "dlcMissing": sum(1 for d in dlc if d["status"] == "missing"), "size": 1, "files": [], "dlc": list(dlc),
    }


LIBRARY = [
    title("0100623017A58000", "Alan Wake Remastered", 65536, 196608, "1.0.1",
          dlc=[{"id": "0100623017A59001", "name": "Alan Wake Remastered - Bonus Pack", "status": "missing"}]),
    title("0100AAAA0000A000", "Hades", 0, 131072, "1.0.0"),
    title("0100BBBB0000B000", "Pokémon™ Scarlet", 196608, 262144, "2.0.1"),
    title("0100CCCC0000C000", "Stardew Valley", 131072, 131072, "1.6.9"),
    title("0100DDDD0000D000", "Hollow Knight", 65536, 131072, "1.4.3"),
]

RELEASES = [
    ("Alan Wake Remastered [0100623017A58800][v196608].nsz", "2023-06-03", 412000000),
    ("Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM", "2023-06-02", 398000000),
    ("[NSW] Alan Wake Remastered (Update v131072) (EUR)", "2023-02-02", 301000000),
    ("Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]", "2023-06-10", 12900000000),
    ("Alan Wake Remastered [0100623017A59001][v0] DLC", "2022-11-02", 5000000),
    ("Alan Wake 2 Update v1.0.5 NSW", "2024-01-01", 1),
    ("Hades_Update_v1.0.2_NSW-GRP", "2021-03-01", 150000000),
    ("Hades II Update v65536", "2025-01-01", 1),
    ("Pokemon.Scarlet.Update.v3.0.1.NSW-BigBlueBox", "2023-12-15", 2900000000),
    ("Pokemon Scarlet The Hidden Treasure Update v262144", "2023-12-14", 2900000000),
    ("Stardew Valley Update v131072", "2024-11-05", 90000000),
    ("Some Unrelated Game Update v65536 NSW", "2024-01-01", 1),
]


def make_fakes():
    app = web.Application()
    app["library"] = [dict(t) for t in LIBRARY]
    app["sent"] = []  # what reached the download client: (filename, category, nzb bytes)
    app["grabbed"] = []  # what Prowlarr was asked to grab itself
    app["queries"] = []

    async def export(request):
        if request.headers.get("Authorization") != "Bearer slm_test":
            return web.Response(status=401)
        return web.json_response(app["library"])

    async def status(request):
        return web.json_response({"version": "2.0.0"})

    async def search(request):
        if request.headers.get("X-Api-Key") != "prowlarr_test":
            return web.Response(status=401)
        query = request.query.get("query", "").lower()
        app["queries"].append(query)
        words = query.split()
        found = []
        for n, (name, published, size) in enumerate(RELEASES):
            text = name.lower().replace(".", " ").replace("_", " ")
            if all(w in text for w in words):
                found.append({
                    "guid": f"guid-{n}", "title": name, "size": size, "indexer": "FakeIndexer",
                    "indexerId": 1, "publishDate": published + "T10:00:00Z", "protocol": "usenet",
                    "downloadUrl": f"http://elsewhere.invalid/1/download?apikey=secret&link={n}",
                    "infoUrl": f"https://indexer.example/details/{n}", "grabs": n,
                })
        found.append({"guid": "torrent", "title": "Hades Update v131072", "protocol": "torrent"})
        return web.json_response(found)

    async def grab(request):
        app["grabbed"].append(await request.json())
        return web.json_response({})

    async def download(request):
        return web.Response(body=NZB, content_type="application/x-nzb")

    async def nzbget(request):
        # "nzbget:tegen" in base64, the login the tests configure.
        if request.headers.get("Authorization") != "Basic bnpiZ2V0OnRlZ2Vu":
            return web.Response(status=401)
        body = await request.json()
        if body["method"] == "version":
            return web.json_response({"result": "24.5"})
        name, content, category = body["params"][:3]
        app["sent"].append((name, category, base64.b64decode(content)))
        return web.json_response({"result": len(app["sent"])})

    async def versions(request):
        return web.json_response({
            "0100623017a58000": {"65536": "2022-11-01", "131072": "2023-02-01", "196608": "2023-06-01"},
            "0100aaaa0000a000": {"65536": "2020-10-01", "131072": "2021-02-25"},
            "0100bbbb0000b000": {"196608": "2023-09-13", "262144": "2023-12-14"},
        })

    app.add_routes([
        web.get("/export/library.json", export),
        web.get("/api/v1/system/status", status),
        web.get("/api/v1/search", search),
        web.post("/api/v1/search", grab),
        web.get("/1/download", download),
        web.post("/jsonrpc", nzbget),
        web.get("/versions.json", versions),
    ])
    return app


if __name__ == "__main__":
    web.run_app(make_fakes(), port=9000)
