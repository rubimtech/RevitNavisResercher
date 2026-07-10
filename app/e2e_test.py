from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:3000"

def test_main_layout(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # App root exists
    app_root = page.locator("#app-root")
    assert app_root.is_visible()

    # Sidebar container is present (hidden on mobile by default)
    sidebar = page.locator("#sidebar-container")
    assert sidebar.is_visible()

    # Sidebar header with branding
    header = page.locator("#sidebar-header")
    assert header.is_visible()
    assert "Revit Researcher" in header.text_content()

    # Main navigation bar
    nav = page.locator("#main-nav")
    assert nav.is_visible()

    # Tab switcher buttons
    tab_chat = page.locator("#tab-chat")
    tab_search = page.locator("#tab-search")
    assert tab_chat.is_visible()
    assert tab_search.is_visible()
    assert "Expert Chat" in tab_chat.text_content()

    # Default active tab is "chat"
    chat_form = page.locator("#chat-form")
    assert chat_form.is_visible()

    # Chat input
    chat_input = page.locator("#chat-input")
    assert chat_input.is_visible()
    assert chat_input.is_enabled()

    # Send button
    send_btn = page.locator("#btn-send-message")
    assert send_btn.is_visible()
    assert send_btn.is_disabled()  # disabled when input is empty

    # Suggested prompt cards on first load
    for i in range(4):
        card = page.locator(f"#suggested-prompt-{i}")
        assert card.is_visible()

    # Settings button
    settings_btn = page.locator("#btn-open-settings")
    assert settings_btn.is_visible()


def test_welcome_message(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Welcome message from the assistant
    welcome = page.locator("text=эксперт-ассистент по")
    assert welcome.is_visible()


def test_tab_switch(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Switch to search tab
    search_tab = page.locator("#tab-search")
    search_tab.click()
    page.wait_for_timeout(500)

    # Direct search form should be visible
    search_form = page.locator("#direct-search-form")
    assert search_form.is_visible()

    search_input = page.locator("#direct-search-input")
    assert search_input.is_visible()

    search_btn = page.locator("#btn-direct-search")
    assert search_btn.is_visible()
    assert search_btn.is_disabled()

    # Switch back to chat tab
    chat_tab = page.locator("#tab-chat")
    chat_tab.click()
    page.wait_for_timeout(500)

    chat_form = page.locator("#chat-form")
    assert chat_form.is_visible()


def test_chat_input_enables_send(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    send_btn = page.locator("#btn-send-message")
    assert send_btn.is_disabled()

    chat_input = page.locator("#chat-input")
    chat_input.fill("Hello, how do I create a transaction?")
    page.wait_for_timeout(200)

    assert send_btn.is_enabled()


def test_sidebar_toggle(page):
    page.set_viewport_size({"width": 375, "height": 812})  # mobile viewport
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # On mobile, sidebar starts hidden (translate-x-full)
    sidebar = page.locator("#sidebar-container")
    sidebar_class = sidebar.get_attribute("class")
    assert "-translate-x-full" in sidebar_class

    # Open sidebar via toggle button
    sidebar_toggle = page.locator("#sidebar-toggle")
    sidebar_toggle.click()
    page.wait_for_timeout(500)

    sidebar_class_after = sidebar.get_attribute("class")
    assert "-translate-x-full" not in sidebar_class_after

    # Close sidebar
    close_btn = page.locator("#btn-close-sidebar")
    close_btn.click()
    page.wait_for_timeout(500)


def test_settings_modal(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    settings_btn = page.locator("#btn-open-settings")
    settings_btn.click()
    page.wait_for_timeout(500)

    # Settings modal header
    settings_header = page.locator("text=Параметры системы")
    assert settings_header.is_visible()

    # Close settings
    close_btn = page.locator("button:has-text('✕')")
    close_btn.click()
    page.wait_for_timeout(500)


def test_new_chat_session(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Click "New Research Thread"
    new_chat_btn = page.locator("#btn-new-chat")
    new_chat_btn.click()
    page.wait_for_timeout(500)

    # New session title should be visible
    new_session = page.locator("text=New Research")
    assert new_session.is_visible()


def test_collections_toggle(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")

    # Click on a collection to toggle it off
    collection_btn = page.locator("#collection-revit_api_knowledge")
    collection_btn.click()
    page.wait_for_timeout(300)

    # Click again to toggle back on
    collection_btn.click()
    page.wait_for_timeout(300)


if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        results = {}
        tests = [
            test_main_layout,
            test_welcome_message,
            test_tab_switch,
            test_chat_input_enables_send,
            test_sidebar_toggle,
            test_settings_modal,
            test_new_chat_session,
            test_collections_toggle,
        ]
        for test in tests:
            try:
                test(page)
                results[test.__name__] = "PASS"
                print(f"  PASS: {test.__name__}")
            except Exception as e:
                results[test.__name__] = f"FAIL: {e}"
                print(f"  FAIL: {test.__name__}: {e}")

        browser.close()

        print("\n" + "=" * 50)
        print("RESULTS SUMMARY")
        print("=" * 50)
        passed = sum(1 for v in results.values() if v == "PASS")
        failed = sum(1 for v in results.values() if v != "PASS")
        for name, status in results.items():
            status_str = "PASS" if status == "PASS" else f"FAIL: {status}"
            print(f"  {name}: {status_str}")
        print(f"\n  Total: {len(tests)} | Passed: {passed} | Failed: {failed}")
        exit(0 if failed == 0 else 1)
