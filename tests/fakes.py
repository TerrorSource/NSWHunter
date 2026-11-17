"""Stand-ins for switch-library-manager-web, Prowlarr, a Newznab and a Torznab indexer, NZBGet,
SABnzbd, Telegram and a Discord webhook, in one small web app.

Used by the tests, and runnable by itself to try the panel without the real services:
    python tests/fakes.py            (listens on port 9000)
"""
import base64
import struct
import zlib

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


# What the fake Newznab indexer has: (title, date as an RSS feed writes it, size, categories).
NEWZNAB = [
    ("Hades.Update.v131072.NSW-NABGRP", "Tue, 02 Mar 2021 10:00:00 +0000", 151000000, [1000, 1090]),
    ("Hades.Update.v131072.PS4-NABGRP", "Tue, 02 Mar 2021 11:00:00 +0000", 151000000, [1000, 1180]),
    ("Hollow Knight Update v131072 NSW-NABGRP", "Mon, 01 Feb 2021 09:30:00 +0100", 90000000, [1090]),
]
# ... and the fake Torznab indexer: (title, date, size, seeders, "file" or "magnet").
TORZNAB = [
    ("Hades Update v131072 NSW-TORGRP", "Wed, 03 Mar 2021 10:00:00 +0000", 150000000, 12, "file"),
    ("Hollow Knight Update v131072 NSW-TORGRP", "Tue, 02 Feb 2021 10:00:00 +0000", 90000000, 0, "magnet"),
]
MAGNET = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a&dn=Hollow+Knight"
RSS = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" '
       'xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" '
       'xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel><title>Fake</title>{}</channel></rss>')


def png(red, green, blue, side=40):
    """A small square picture in one colour: a real PNG, so a browser shows it."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    row = b"\x00" + bytes((red, green, blue)) * side
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * side)) + chunk(b"IEND", b""))


PNG = png(200, 40, 60)


def bencode(value):
    """Enough of bencode to make a small torrent file."""
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, str):
        return bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    return b"d" + b"".join(bencode(k) + bencode(v) for k, v in sorted(value.items())) + b"e"


TORRENT = bencode({"announce": "http://tracker.invalid/announce",
                   "info": {"name": "Hades Update", "length": 150000000, "piece length": 262144, "pieces": b"x" * 20}})


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
    app["discord"] = []  # what was posted to the Discord webhook
    app["covers"] = []  # pictures of games that were asked for
    app["fetched"] = []  # download links of the direct indexers that were followed
    app["indexer_ids"] = []
    app["sab"] = {}  # SABnzbd: id -> "queue", or a history status like "Completed"
    # Every removal a download client was asked for, also of what it does not have:
    # ("nzbget", the command, id) and ("sabnzbd", "queue" or "history", id, with the files or not).
    app["removed"] = []

    async def export(request):
        if request.headers.get("Authorization") != "Bearer slm_test":
            return web.Response(status=401)
        return web.json_response(app["library"])

    async def titles(request):
        """As the API of switch-library-manager-web: every game with where its pictures are. One
        picture is its own, one is on another server, one game has none."""
        if request.headers.get("Authorization") != "Bearer slm_test":
            return web.Response(status=401)
        # The same stand-in under another name: to NSWHunter that is another server.
        elsewhere = f"{request.scheme}://localhost:{request.url.port}/elsewhere/hades.png"
        return web.json_response({
            "0100623017A58000": {"iconUrl": "/covers/big.jpg", "thumbnailUrl": "/covers/0100623017A58000.jpg"},
            "0100aaaa0000a000": {"iconUrl": elsewhere},
            "0100BBBB0000B000": {"iconUrl": ""},
            "0100DDDD0000D000": {"thumbnailUrl": "/covers/not-a-picture"}})

    async def cover(request):
        app["covers"].append((request.path, request.headers.get("Authorization")))
        if request.path.startswith("/covers/") and request.headers.get("Authorization") != "Bearer slm_test":
            return web.Response(status=401)
        if request.path.endswith("not-a-picture"):
            return web.Response(text="<html>login</html>", content_type="text/html")
        return web.Response(body=PNG, content_type="image/png")

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
        # Prowlarr has a torrent indexer too. Asked for usenet only (-1) the real one leaves it
        # out; this one does not, so the tests see that NSWHunter does not take it either.
        found.append({"guid": "torrent", "title": "Hades Update v131072", "protocol": "torrent", "seeders": 5,
                      "indexer": "Tracker", "indexerId": 3, "size": 150000000, "publishDate": "2021-03-05T10:00:00Z",
                      "downloadUrl": f"{request.scheme}://{request.host}/tor/get/file"})
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
        if body["method"] == "editqueue":
            # (command, text, ids), or with an offset after the command as before NZBGet 18.
            command, ids = body["params"][0], body["params"][-1]
            if command not in ("GroupDelete", "GroupFinalDelete", "HistoryDelete", "HistoryFinalDelete"):
                return web.json_response({"error": {"name": "JSONRPCError", "code": 3, "message": "Invalid action"}})
            done = False
            for found in map(str, ids):
                app["removed"].append(("nzbget", command, found))
                where = app["downloads"].get(found)
                if command.startswith("Group") and where == "queue":
                    done = True
                    if command == "GroupDelete":
                        app["downloads"][found] = "DELETED/MANUAL"  # it moves to the history
                    else:
                        del app["downloads"][found]
                elif command.startswith("History") and where not in (None, "queue"):
                    done = True
                    del app["downloads"][found]
            return web.json_response({"result": done})  # false: none of the ids was there
        name, content, category = body["params"][:3]
        app["sent"].append((name, category, base64.b64decode(content)))
        app["downloads"][str(len(app["sent"]))] = "queue"
        return web.json_response({"result": len(app["sent"])})

    async def sabnzbd(request):
        """As the API of SABnzbd, as far as following and removing a download go."""
        form = await request.post()
        if form.get("apikey") != "sab_test":
            return web.json_response({"status": False, "error": "API Key Incorrect"}, status=403)
        mode, jobs = form.get("mode"), app["sab"]
        if mode in ("queue", "history") and form.get("name") == "delete":
            files, removed = form.get("del_files") == "1", []
            for found in form.get("value", "").split(","):
                app["removed"].append(("sabnzbd", mode, found, files))
                if found in jobs and (jobs[found] == "queue") == (mode == "queue"):
                    del jobs[found]
                    removed.append(found)
            # The queue tells what it removed, and says false if that is nothing. The history
            # says true whatever it found.
            if mode == "queue":
                return web.json_response({"status": bool(removed), "nzo_ids": removed})
            return web.json_response({"status": True})
        if mode == "queue":
            return web.json_response({"queue": {"slots": [
                {"nzo_id": i, "status": "Downloading", "percentage": "0"} for i, s in jobs.items() if s == "queue"]}})
        if mode == "history":
            return web.json_response({"history": {"slots": [
                {"nzo_id": i, "status": s} for i, s in jobs.items() if s != "queue"]}})
        return web.json_response({"status": False, "error": "not implemented"})

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

    def feed(request, items):
        """Like a Newznab indexer: the capabilities for everyone, a search only with the key."""
        if request.query.get("t") == "caps":
            return web.Response(text='<caps><server title="FakeNab" version="1.0"/></caps>', content_type="application/xml")
        if request.query.get("apikey") != "nab_test":
            return web.Response(text='<error code="100" description="Incorrect user credentials"/>', content_type="application/xml")
        words = request.query.get("q", "").lower().split()
        found = [i for i in items if all(w in i[0].lower().replace(".", " ") for w in words)]
        return web.Response(text=RSS.format("".join(i[-1] for i in found)), content_type="application/rss+xml")

    async def newznab(request):
        base = f"{request.scheme}://{request.host}"
        items = [(title, f"""<item><title>{title}</title><guid isPermaLink="true">{base}/nab/details/{n}</guid>
            <link>{base}/nab/get/{n}</link><comments>{base}/nab/details/{n}#comments</comments><pubDate>{date}</pubDate>
            <enclosure url="{base}/nab/get/{n}" length="{size}" type="application/x-nzb"/>
            {"".join(f'<newznab:attr name="category" value="{c}"/>' for c in categories)}
            <newznab:attr name="size" value="{size}"/><newznab:attr name="grabs" value="{n + 3}"/></item>""")
                 for n, (title, date, size, categories) in enumerate(NEWZNAB)]
        return feed(request, items)

    async def torznab(request):
        base = f"{request.scheme}://{request.host}"
        items = [(title, f"""<item><title>{title}</title><guid>tor-{n}</guid><pubDate>{date}</pubDate>
            <enclosure url="/tor/get/{how}" length="{size}" type="application/x-bittorrent"/>
            <torznab:attr name="category" value="1090"/><torznab:attr name="seeders" value="{seeders}"/>
            <torznab:attr name="peers" value="{seeders + 2}"/></item>""")
                 for n, (title, date, size, seeders, how) in enumerate(TORZNAB)]
        return feed(request, items)

    async def nab_get(request):
        app["fetched"].append(request.path)
        return web.Response(body=NZB, content_type="application/x-nzb")

    async def tor_get(request):
        app["fetched"].append(request.path)
        if request.match_info["how"] == "magnet":
            raise web.HTTPFound(MAGNET)  # as many indexers do: the link leads on to a magnet link
        return web.Response(body=TORRENT, content_type="application/x-bittorrent")

    async def discord(request):
        if request.match_info["token"] != "good":
            return web.json_response({"message": "Unknown Webhook"}, status=404)
        app["discord"].append((await request.json())["content"])
        return web.Response(status=204)

    app.add_routes([
        web.get("/nab/api", newznab),
        web.get("/tor/api", torznab),
        web.get("/nab/get/{n}", nab_get),
        web.get("/tor/get/{how}", tor_get),
        web.post("/discord/{token}", discord),
        web.get("/export/library.json", export),
        web.get("/api/titles", titles),
        web.get("/covers/{name}", cover),
        web.get("/elsewhere/{name}", cover),
        web.get("/api/v1/system/status", keyed(status)),
        web.get("/api/v1/search", search),
        web.get("/api/v1/indexer", keyed(indexers)),
        web.get("/api/v1/downloadclient", keyed(download_clients)),
        web.post("/api/v1/search", keyed(grab)),
        web.get("/1/download", download),
        web.post("/jsonrpc", nzbget),
        web.post("/api", sabnzbd),
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
