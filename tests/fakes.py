"""Stand-ins for switch-library-manager-web, Prowlarr and NZBGet, in one small web app.

Used by the tests, and runnable by itself to try the panel without the real services:
    python tests/fakes.py            (listens on port 9000)
"""
import base64

from aiohttp import web

NZB = b'<?xml version="1.0"?><nzb xmlns="http://www.newzbin.com/DTD/2003/nzb"></nzb>'


def title(game_id, name, local, latest, version=None, dlc=(), files=()):
    return {
        "id": game_id, "name": name, "version": version, "localUpdate": local, "latestUpdate": latest,
        "updateMissing": local < latest, "dlcOwned": 0,
        "dlcMissing": sum(1 for d in dlc if d["status"] == "missing"), "size": 1, "files": list(files),
        "dlc": list(dlc),
    }


LIBRARY = [
    title("0100623017A58000", "Alan Wake Remastered", 65536, 196608, "1.0.1",
          dlc=[{"id": "0100623017A59001", "name": "Alan Wake Remastered - Bonus Pack", "status": "missing"}],
          files=[{"type": "NSP", "path": "/mnt/roms/a.nsp", "size": 12_000_000_000, "version": 0},
                 {"type": "UPD", "path": "/mnt/roms/a-upd.nsp", "size": 380_000_000, "version": 65536}]),
    title("0100AAAA0000A000", "Hades", 0, 131072, "1.0.0"),
    title("0100BBBB0000B000", "Pokémon™ Scarlet", 196608, 262144, "2.0.1"),
    title("0100CCCC0000C000", "Stardew Valley", 131072, 131072, "1.6.9"),
    title("0100DDDD0000D000", "Hollow Knight", 65536, 131072, "1.4.3"),
    # A Switch 2 title (ID starts with 04): never searched, never downloaded.
    title("0400AAAA0000A000", "Hades", 0, 131072, "1.0.0"),
    title("0100EEEE0000E000", "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS", 655360, 720896, "1.7.0"),
    # Up to date, but with DLCs that differ in one word, as in the user's library.
    title("0100FFFF0000F000", "EA SPORTS FC™ 25", 65536, 65536, "1.0.1", dlc=[
        {"id": "0100FFFF0000F001", "name": "EA SPORTS FC™ 25 In-Game Commentary - Dutch", "status": "missing"},
        {"id": "0100FFFF0000F002", "name": "EA SPORTS FC™ 25 In-Game Commentary - Spanish", "status": "missing"},
        {"id": "0100FFFF0000F003", "name": "EA SPORTS FC™ 25 In-Game Commentary - Latin American Spanish",
         "status": "owned"}]),
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
    ("EA SPORTS FC 25 In-Game Commentary Dutch DLC NSW-VENOM", "2024-09-20", 1600000000),
    ("EA.SPORTS.FC.25.In-Game.Commentary.Dutch.DLC.NSW-VENOM", "2024-09-20", 1600000000),
    ("EA SPORTS FC 25 In-Game Commentary Spanish DLC NSW-VENOM", "2024-09-20", 1300000000),
    ("EA SPORTS FC 25 In-Game Commentary Latin American Spanish DLC NSW-VENOM", "2024-09-20", 1500000000),
    # The same name as the Switch update, but posted in PC > Games (4050): not for the Switch.
    ("Hades.Update.v131072-PCGROUP", "2021-03-02", 150000000, [4000, 4050]),
    # The user's real case: Console also holds other consoles. One filed under PS4 (1180), one
    # filed under Console/Other with the platform only in its name.
    ("Hades.Update.v131072.incl.DLC-PSGROUP", "2021-03-03", 36400000000, [1000, 1180]),
    ("Hades.v1.38.incl.DLC.PS4-CUSA34119", "2021-03-04", 36400000000, [1000, 1090]),
    # Real names from the user's Prowlarr: three language variants per update.
    ("NARUTO X BORUTO ULTIMATE NINJA STORM CONNECTIONS Update v1.7.1 MULTI6 NSW-SUXXORS", "2026-09-30", 4290000000),
    ("NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 MULTI4 NSW-SUXXORS", "2026-09-30", 4190000000),
    ("NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS", "2026-09-30", 1720000000),
    ("NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.0 MULTI4 NSW-SUXXORS", "2026-08-20", 4190000000),
    ("NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.0 NSW-SUXXORS", "2026-08-20", 1720000000),
]


def make_fakes():
    app = web.Application()
    app["library"] = [dict(t) for t in LIBRARY]
    app["sent"] = []  # what reached the download client: (filename, category, nzb bytes)
    app["grabbed"] = []  # what Prowlarr was asked to grab itself
    app["queries"] = []
    app["downloads"] = {}  # NZBGet: id -> "queue", or a history status like "SUCCESS/ALL"
    app["rescans"] = []  # one entry for every time the library was asked to scan
    app["telegram"] = []  # messages the bot sent
    app["buttons"] = []  # the buttons under each of those messages (None if it had none)
    app["updates"] = []  # what getUpdates has to hand out: presses on those buttons
    app["answers"] = []  # the small confirmations after a press
    app["edits"] = []  # messages that were rewritten after a press
    app["progress"] = {}  # NZBGet: id -> (MB in total, MB left) of what is in the queue
    app["indexer_ids"] = []

    async def export(request):
        if request.headers.get("Authorization") != "Bearer slm_test":
            return web.Response(status=401)
        return web.json_response(app["library"])

    def keyed(handler):
        """Like Prowlarr: nothing without the API key."""
        async def checked(request):
            if request.headers.get("X-Api-Key") != "prowlarr_test":
                return web.Response(status=401)
            return await handler(request)
        return checked

    async def status(request):
        return web.json_response({"version": "2.0.0"})

    async def search(request):
        if request.headers.get("X-Api-Key") != "prowlarr_test":
            return web.Response(status=401)
        query = request.query.get("query", "").lower()
        app["queries"].append(query)
        app["indexer_ids"].append(request.query.getall("indexerIds", []))
        # As in Prowlarr: -1 is every usenet indexer, -2 every torrent indexer, else an indexer id.
        if not {"-1", "1"} & set(request.query.getall("indexerIds", ["-1"])):
            return web.json_response([])
        words = query.split()
        found = []
        for n, (name, published, size, *category) in enumerate(RELEASES):
            text = name.lower().replace(".", " ").replace("_", " ")
            if all(w in text for w in words):
                found.append({
                    "categories": [{"id": c} for c in (category[0] if category else [1000, 1090])],
                    "guid": f"guid-{n}", "title": name, "size": size, "indexer": "FakeIndexer",
                    "indexerId": 1, "publishDate": published + "T10:00:00Z", "protocol": "usenet",
                    "downloadUrl": f"http://elsewhere.invalid/1/download?apikey=secret&link={n}",
                    "infoUrl": f"https://indexer.example/details/{n}", "grabs": n,
                })
        found.append({"guid": "torrent", "title": "Hades Update v131072", "protocol": "torrent"})
        return web.json_response(found)

    async def indexers(request):
        return web.json_response([
            {"id": 1, "name": "FakeIndexer", "protocol": "usenet", "enable": True, "priority": 10},
            {"id": 2, "name": "Off", "protocol": "usenet", "enable": False},
            {"id": 3, "name": "Tracker", "protocol": "torrent", "enable": True}])

    async def download_clients(request):
        return web.json_response([{"id": 1, "name": "NZBGet", "enable": True}])

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
        if body["method"] == "history":
            return web.json_response({"result": [
                {"NZBID": int(i), "Status": s} for i, s in app["downloads"].items() if s != "queue"]})
        if body["method"] == "listgroups":
            return web.json_response({"result": [
                {"NZBID": int(i), "Status": "DOWNLOADING", "FileSizeMB": app["progress"].get(i, (0, 0))[0],
                 "RemainingSizeMB": app["progress"].get(i, (0, 0))[1]}
                for i, s in app["downloads"].items() if s == "queue"]})
        name, content, category = body["params"][:3]
        app["sent"].append((name, category, base64.b64decode(content)))
        app["downloads"][str(len(app["sent"]))] = "queue"
        return web.json_response({"result": len(app["sent"])})

    async def rescan(request):
        app["rescans"].append(1)
        return web.Response(status=202)

    async def telegram(request):
        # Like Telegram: an unknown token is 401, an unknown chat is 400 with a description.
        if request.match_info["token"] != "TESTTOKEN":
            return web.json_response({"ok": False, "description": "Unauthorized"}, status=401)
        body = await request.json()
        if str(body.get("chat_id")) != "42":
            return web.json_response({"ok": False, "description": "Bad Request: chat not found"}, status=400)
        app["telegram"].append(body["text"])
        app["buttons"].append(body.get("reply_markup"))
        return web.json_response({"ok": True, "result": {"message_id": len(app["telegram"])}})

    async def telegram_updates(request):
        if request.match_info["token"] != "TESTTOKEN":
            return web.json_response({"ok": False, "description": "Unauthorized"}, status=401)
        body = await request.json()
        return web.json_response({"ok": True, "result": [
            u for u in app["updates"] if u["update_id"] >= body.get("offset", 0)]})

    async def telegram_answer(request):
        app["answers"].append((await request.json())["text"])
        return web.json_response({"ok": True, "result": True})

    async def telegram_edit(request):
        app["edits"].append(await request.json())
        return web.json_response({"ok": True, "result": {}})

    async def versions(request):
        return web.json_response({
            "0100623017a58000": {"65536": "2022-11-01", "131072": "2023-02-01", "196608": "2023-06-01"},
            "0100aaaa0000a000": {"65536": "2020-10-01", "131072": "2021-02-25"},
            "0100bbbb0000b000": {"196608": "2023-09-13", "262144": "2023-12-14"},
            "0100eeee0000e000": {"589824": "2025-02-03", "655360": "2026-08-19", "720896": "2026-10-21"},
        })

    app.add_routes([
        web.get("/export/library.json", export),
        web.get("/api/v1/system/status", keyed(status)),
        web.get("/api/v1/search", search),
        web.get("/api/v1/indexer", keyed(indexers)),
        web.get("/api/v1/downloadclient", keyed(download_clients)),
        web.post("/api/v1/search", keyed(grab)),
        web.get("/1/download", download),
        web.post("/jsonrpc", nzbget),
        web.post("/sync", rescan),
        web.post("/bot{token}/sendMessage", telegram),
        web.post("/bot{token}/getUpdates", telegram_updates),
        web.post("/bot{token}/answerCallbackQuery", telegram_answer),
        web.post("/bot{token}/editMessageText", telegram_edit),
        web.get("/versions.json", versions),
    ])
    return app


if __name__ == "__main__":
    web.run_app(make_fakes(), port=9000)
