"""The panel in a real browser: logging in for the first time, setting it up, and clicking
through every page. Run by tests/panel/run.sh, which starts the panel and the fake services; in
the ordinary run of the unit tests this file is skipped.

The tests run in the order they are written, in one browser page: each goes on where the one
before it stopped, as someone using the panel would."""
import os
import re

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

PANEL = os.environ.get("PANEL_URL", "")
FAKES = os.environ.get("FAKES_URL", "")
pytestmark = pytest.mark.skipif(not PANEL, reason="needs a running panel: see tests/panel/run.sh")

USER = "tester"
PASSWORD = "panel test " + os.urandom(4).hex()  # chosen at the first login, only for this run
# Every page of the menu, and something that has to be on it.
PAGES = {
    "games": "#gamelist", "queue": "#queue", "history": "#history", "blocklist": "#blocklist",
    "wanted": "#list", "choice": "#list", "settings": "#extra .overview", "media": "#config",
    "indexers": "#extra .cards", "clients": "#extra .cards", "connect": "#extra .cards",
    "general": "#config", "ui": "#config", "status": "#status", "tasks": "#tasks", "backup": "#backups",
    "updates": "#updates", "log": "#log", "logfiles": "#logfiles",
}


@pytest.fixture(scope="module")
def page():
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(15000)
        page.problems = []
        page.on("pageerror", lambda error: page.problems.append(f"script error: {error}"))
        # A picture the library does not have is a 404 of the cover, which the page deals with.
        page.on("console", lambda message: page.problems.append(f"console: {message.text}")
                if message.type == "error" and "Failed to load resource" not in message.text else None)
        yield page
        browser.close()


def tool(page, name):
    """A button of the toolbar, by the name under its drawing."""
    return page.locator("#toolbar .tool", has_text=re.compile(rf"^{re.escape(name)}"))


def go(page, name):
    page.goto(f"{PANEL}/#{name}")
    page.reload()
    expect(page.locator("#app")).to_be_visible()


def menu(page, group, child=None):
    page.locator("#nav button.parent", has_text=group).click()
    if child:
        page.locator("#nav button.child", has_text=re.compile(rf"^{re.escape(child)}")).click()


def no_problems(page):
    problems, page.problems[:] = list(page.problems), []
    assert not problems, problems


def test_the_first_login_asks_for_a_password_of_your_own(page):
    page.goto(PANEL)
    expect(page.locator("#authform")).to_be_visible()
    page.fill("#auth-user", "admin")
    page.fill("#auth-password", "not the password")
    page.click("#authgo")
    expect(page.locator("#autherror")).to_contain_text("Wrong username or password")
    page.fill("#auth-password", os.environ["FIRST_PASSWORD"])
    page.click("#authgo")
    # Logged in with the made-up password: nothing works but choosing one.
    expect(page.locator("#authtitle")).to_have_text("Choose your own password")
    page.fill("#auth-user", USER)
    page.fill("#auth-password", PASSWORD)
    page.fill("#auth-repeat", "something else")
    page.click("#authgo")
    expect(page.locator("#autherror")).to_contain_text("not the same")
    page.fill("#auth-repeat", PASSWORD)
    page.click("#authgo")
    expect(page.locator("#app")).to_be_visible()
    # Nothing is set up yet: the panel opens where that is done, and says what is missing.
    expect(page).to_have_title("Connect - NSWHunter")
    expect(page.locator("#notice")).to_contain_text("not set up yet")
    no_problems(page)


def test_setting_up_the_library_an_indexer_and_a_download_client(page):
    # The library, with a Test before saving.
    page.locator(".pcard", has_text="Switch-library-manager-web").click()
    page.fill("#e-SLM_URL", FAKES)
    page.fill("#e-SLM_API_KEY", "wrong key")
    page.get_by_role("button", name="Test", exact=True).click()
    expect(page.locator("#editor .testresult")).to_have_class(re.compile("bad"))
    # What was typed is still there after the test; only the key is replaced.
    expect(page.locator("#e-SLM_URL")).to_have_value(FAKES)
    page.fill("#e-SLM_API_KEY", "slm_test")
    page.get_by_role("button", name="Test", exact=True).click()
    expect(page.locator("#editor .testresult")).to_contain_text("games in the library")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#modal")).to_be_hidden()

    menu(page, "Settings", "Indexers")
    page.locator(".pcard.add").click()
    page.locator(".pcard.pick", has_text="Prowlarr").click()
    page.fill("#e-url", FAKES)
    page.fill("#e-api_key", "prowlarr_test")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#modal")).to_be_hidden()
    expect(page.locator("#extra .pcard", has_text="Prowlarr")).to_be_visible()

    menu(page, "Settings", "Download Clients")
    page.locator(".pcard.add").click()
    page.locator(".pcard.pick", has_text="NZBGet").click()
    page.fill("#e-url", FAKES)
    page.fill("#e-username", "nzbget")
    page.fill("#e-password", "tegen")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator("#modal")).to_be_hidden()
    expect(page.locator("#notice")).not_to_contain_text("not set up yet")

    # Missing DLC is searched too, through the form of Media Management and its Save Changes.
    menu(page, "Settings", "Media Management")
    expect(tool(page, "No Changes")).to_be_disabled()
    page.check("#f-INCLUDE_DLC")
    tool(page, "Save Changes").click()
    expect(page.locator("#toast")).to_contain_text("Settings saved")
    no_problems(page)


def test_a_round_finds_what_the_library_misses(page):
    menu(page, "Games")
    tool(page, "Update All").click()
    menu(page, "Wanted")
    expect(page.locator("#list tbody tr")).to_have_count(6, timeout=60000)
    expect(page.locator("#list .total")).to_have_text("Total records: 6")
    expect(page.locator("#list tbody tr", has_text="Alan Wake Remastered")).to_contain_text("Awaiting Choice")
    # The Filter menu narrows the list; Awaiting Choice is a page of its own in the menu.
    tool(page, "Filter").click()
    page.locator("#toolbar .menu button", has_text="DLC Missing").click()
    expect(page.locator("#list tbody tr")).to_have_count(2)
    tool(page, "Filter").click()
    page.locator("#toolbar .menu button", has_text=re.compile("^All")).click()
    expect(page.locator("#list tbody tr")).to_have_count(6)
    no_problems(page)


def test_every_page_opens(page):
    for name, landmark in PAGES.items():
        go(page, name)
        expect(page.locator(landmark).first).to_be_visible()
        expect(page.locator("#page-" + page.evaluate("SECTION(page)"))).to_be_visible()
        assert page.evaluate("page") == name
        no_problems(page)
    go(page, "updates")
    expect(page.locator("#updates .update").first).to_contain_text("Currently Installed")
    go(page, "status")
    expect(page.locator("#status")).to_contain_text("No issues with your configuration")
    expect(page.locator("#status .facts")).to_contain_text(USER)


def test_from_wanted_to_the_queue_and_out_of_the_download_client(page):
    go(page, "wanted")
    # Two games are ticked: one with a release to send, one that nothing was found for.
    page.locator("#list tbody tr", has_text="Scarlet").locator("input[type=checkbox]").check()
    page.locator("#list tbody tr", has_text="Hollow Knight").locator("input[type=checkbox]").check()
    expect(tool(page, "Download Selected")).to_be_enabled()
    tool(page, "Download Selected").click()
    expect(page.locator("#toast")).to_contain_text("1 game sent to the download client; 1 had no release to send")
    expect(page.locator("#list tbody tr", has_text="Scarlet")).to_contain_text("In Queue")
    menu(page, "Activity", "Queue")
    expect(page.locator("#queue tbody tr")).to_have_count(1)
    expect(page.locator("#queue tbody tr")).to_contain_text("NZBGet")
    # Removing asks what to do; the download leaves the download client too.
    page.locator("#queue tbody tr button[title='Remove from the queue']").click()
    expect(page.locator(".dialog")).to_contain_text("Remove from Download Client")
    expect(page.locator("#rm-client")).to_be_checked()
    page.check("#rm-block")
    page.locator(".mfoot button", has_text="Remove").click()
    expect(page.locator("#toast")).to_contain_text("1 release removed from the queue")
    expect(page.locator("#queue")).to_contain_text("Queue is empty")
    menu(page, "Activity", "History")
    expect(page.locator("#history tbody tr")).to_have_count(1)
    page.locator("#history button[title=Details]").click()
    expect(page.locator(".dialog .facts")).to_contain_text("NZBGet")
    page.keyboard.press("Escape")
    expect(page.locator("#modal")).to_be_hidden()
    # The release went on the blocklist; taking it off offers it again.
    menu(page, "Activity", "Blocklist")
    expect(page.locator("#blocklist tbody tr")).to_have_count(1)
    page.locator("#blocklist thead input[type=checkbox]").check()
    tool(page, "Remove Selected").click()
    expect(page.locator("#blocklist")).to_contain_text("No history blocklist")
    go(page, "log")
    expect(page.locator("#log")).to_contain_text("Removed from the queue and from NZBGet")
    no_problems(page)


def test_the_page_of_a_game_and_interactive_search(page):
    go(page, "games")
    expect(page.locator("#gamelist tbody tr")).to_have_count(7)
    page.locator("#gamelist button.linkish", has_text="Alan Wake Remastered").click()
    expect(page).to_have_title("Alan Wake Remastered - NSWHunter")
    expect(page.locator("#game h1")).to_have_text("Alan Wake Remastered")
    expect(page.locator("#game")).to_contain_text("Update Missing")
    tool(page, "Interactive Search").click()
    expect(page.locator(".mhead")).to_contain_text("Interactive Search - Alan Wake Remastered")
    releases = page.locator("#modal .cand:not(.th)")
    before = releases.count()
    assert before >= 3
    # Rejecting takes a release out of the list, and the window stays open.
    releases.nth(1).locator("button[title^=Reject]").click()
    expect(releases).to_have_count(before - 1)
    # Words of your own are searched as they are.
    page.fill("#ownwords", "alan wake remastered update")
    page.locator(".mfoot button", has_text="Search").click()
    expect(page.locator("#toast")).to_contain_text(re.compile("found"))
    expect(page.locator("#ownwords")).to_have_value("alan wake remastered update")
    page.locator(".mhead button").click()
    # The Back button of the browser goes back to the games.
    page.go_back()
    expect(page).to_have_title("Games - NSWHunter")
    no_problems(page)


def test_posters_and_table_options(page):
    go(page, "games")
    tool(page, "View").click()
    page.locator("#toolbar .menu button", has_text="Posters").click()
    expect(page.locator("#gamelist .poster")).to_have_count(7)
    expect(tool(page, "Options")).to_have_count(0)
    tool(page, "View").click()
    page.locator("#toolbar .menu button", has_text="Table").click()
    expect(page.locator("#gamelist th", has_text="Title ID")).to_be_visible()
    tool(page, "Options").click()
    page.locator(".dialog label", has_text="Title ID").locator("input").uncheck()
    page.locator(".mhead button").click()
    expect(page.locator("#gamelist th", has_text="Title ID")).to_have_count(0)
    # The search box on top finds a game from any page.
    go(page, "status")
    page.fill("#find", "hades")
    expect(page).to_have_title("Games - NSWHunter")
    expect(page.locator("#gamelist tbody tr")).to_have_count(1)
    page.fill("#find", "")
    no_problems(page)


def test_leaving_a_form_with_changes_asks_first(page):
    go(page, "ui")
    page.select_option("#f-UI_THEME", "light")
    expect(tool(page, "Save Changes")).to_be_enabled()
    menu(page, "Games")
    expect(page.locator(".mhead")).to_contain_text("Unsaved Changes")
    page.locator(".mfoot button", has_text="Stay").click()
    expect(page).to_have_title("UI - NSWHunter")
    menu(page, "Games")
    page.locator(".mfoot button", has_text="Discard").click()
    expect(page).to_have_title("Games - NSWHunter")
    go(page, "ui")
    expect(page.locator("#f-UI_THEME")).to_have_value("auto")  # it was not saved
    no_problems(page)


def test_tasks_backups_and_sessions(page):
    go(page, "tasks")
    page.locator("#tasks tr", has_text="Rss Sync").locator("button").click()
    expect(page.locator("#toast")).to_contain_text("Done")
    expect(page.locator("#tasks h2", has_text="Queue")).to_be_visible()
    go(page, "backup")
    count = page.locator("#backups tbody tr").count()
    tool(page, "Backup Now").click()
    expect(page.locator("#backups tbody tr")).to_have_count(count + 1)
    go(page, "general")
    expect(page.locator("#extra")).to_contain_text("this browser")
    expect(page.locator("#extra .label.wide")).to_have_text("Off")  # two-step login is optional
    no_problems(page)


def test_a_phone_has_no_sideways_scrolling(page):
    page.set_viewport_size({"width": 375, "height": 812})
    try:
        for name in PAGES:
            go(page, name)
            wide, screen = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert wide <= screen, f"{name} is {wide} wide on a screen of {screen}"
        go(page, "wanted")
        page.click("#menu")
        expect(page.locator("#side")).to_be_visible()
        no_problems(page)
    finally:
        page.set_viewport_size({"width": 1440, "height": 900})


def test_logging_out_and_in_again(page):
    go(page, "games")
    page.click("#topright button")
    page.locator("#topright .menu button", has_text="Log out").click()
    expect(page.locator("#authform")).to_be_visible()
    expect(page.locator("#app")).to_be_hidden()
    page.fill("#auth-user", USER)
    page.fill("#auth-password", PASSWORD)
    page.click("#authgo")
    expect(page.locator("#app")).to_be_visible()
    no_problems(page)
