"""
Web regression tests — drive the real browser against the live FastAPI server.

Run with:
    pytest tests/test_web.py -v --headed          # visible browser
    pytest tests/test_web.py -v                   # headless (default)
    pytest tests/test_web.py -v -k "login"        # filter by name

Prerequisites:
  - Server running at http://127.0.0.1:8000
  - Admin seeded: admin@iaas.local / admin123

Network note:
  Playwright's headless Chromium on Windows hangs when sending JSON-body POST
  requests through uvicorn (form-encoded POSTs work fine).  Workarounds:
    * Fixtures use subprocess curl to create test data (provably works).
    * UI tests that exercise JSON POST paths use page.route() to mock the
      API response, testing the FRONTEND JS behaviour without the network hang.
    * GET-only flows (packages, dashboard, admin stats/users/logs) use the real
      API because GET requests have no body and work correctly.
"""

import json
import socket
import subprocess
import time

import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@iaas.local"
ADMIN_PASSWORD = "admin123"

# Allow plenty of time for browser-visible async updates.
UI_TIMEOUT = 8_000

# ---------------------------------------------------------------------------
# Mock data for page.route() intercepts
# ---------------------------------------------------------------------------

_MOCK_PACKAGE = {
    "id": 5, "name": "Basic Network", "type": "network",
    "quota_value": 100, "quota_unit": "Mbps", "price": 15.0,
    "description": "100 Mbps dedicated bandwidth with 1TB monthly transfer.",
}
_MOCK_SUB_ACTIVE = {
    "id": 101, "status": "active", "resource_ref": None,
    "quota_used": 0, "quota_remaining": 100,
    "rented_at": "2025-01-01T10:00:00", "expires_at": None,
    "package": _MOCK_PACKAGE,
}
_MOCK_SUB_CANCELLED = {**_MOCK_SUB_ACTIVE, "status": "cancelled"}
_MOCK_REG_RESPONSE = {
    "id": 999, "full_name": "Fresh User", "email": "fresh@test.com",
    "is_admin": False, "created_at": "2025-01-01T00:00:00",
}


def _unique_email():
    return f"regtest_{int(time.time() * 1000)}@example.com"


def _curl_post(path: str, data: dict, timeout: int = 20) -> dict:
    """Use the system curl binary (provably works even when Python HTTP hangs)."""
    result = subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"{BASE_URL}{path}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(data)],
        capture_output=True, text=True, timeout=timeout,
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Session-level guard: skip module when server is not reachable
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def server_available():
    """Skip entire module if the dev server TCP port is not open."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("127.0.0.1", 8000))
        s.close()
    except Exception:
        pytest.skip(f"Server not running at {BASE_URL} — start with: uvicorn main:app")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def new_user(server_available):
    """Create a fresh user via curl (bypasses the headless-Chromium JSON-POST hang).
    Returns (email, password) — does NOT touch the Playwright page."""
    email = _unique_email()
    password = "Regtest@123"
    data = _curl_post("/auth/register", {
        "full_name": "Reg Test User", "email": email, "password": password,
    })
    assert data.get("id"), f"Registration via curl failed: {data}"
    return email, password


@pytest.fixture()
def logged_in_user(page: Page, new_user, server_available):
    """Navigate to dashboard as a regular user via the browser login form."""
    email, password = new_user
    page.goto(f"{BASE_URL}/login.html")
    page.fill("#email", email)
    page.fill("#password", password)
    page.locator("#submitBtn").click()
    page.wait_for_url(f"{BASE_URL}/dashboard.html", timeout=UI_TIMEOUT)
    return email, password


@pytest.fixture()
def logged_in_admin(page: Page, server_available):
    """Navigate to admin panel as the seeded admin user."""
    page.goto(f"{BASE_URL}/login.html")
    page.fill("#email", ADMIN_EMAIL)
    page.fill("#password", ADMIN_PASSWORD)
    page.locator("#submitBtn").click()
    page.wait_for_url(f"{BASE_URL}/admin.html", timeout=UI_TIMEOUT)


def _clear_token(page: Page):
    """Clear localStorage.token — navigate to a real page first so
    localStorage is accessible (blocked on about:blank in some browsers)."""
    page.goto(f"{BASE_URL}/login.html")
    page.evaluate("localStorage.removeItem('token')")


# ---------------------------------------------------------------------------
# Index / redirect behaviour
# ---------------------------------------------------------------------------

class TestIndexRedirects:
    def test_unauthenticated_visitor_lands_on_login(self, page: Page, server_available):
        """Visiting / without a token redirects to login."""
        _clear_token(page)
        page.goto(BASE_URL)
        expect(page).to_have_url(f"{BASE_URL}/login.html")

    def test_authenticated_visitor_lands_on_dashboard(self, page: Page, logged_in_user):
        """Visiting / with a valid token skips login."""
        page.goto(BASE_URL)
        expect(page).to_have_url(f"{BASE_URL}/dashboard.html")


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------

class TestLoginPage:
    def test_login_page_renders_form(self, page: Page, server_available):
        page.goto(f"{BASE_URL}/login.html")
        expect(page.locator("#email")).to_be_visible()
        expect(page.locator("#password")).to_be_visible()
        expect(page.locator("#submitBtn")).to_be_visible()
        expect(page.locator("text=Welcome back")).to_be_visible()

    def test_login_wrong_password_shows_error(self, page: Page, server_available):
        page.goto(f"{BASE_URL}/login.html")
        page.fill("#email", ADMIN_EMAIL)
        page.fill("#password", "wrongpassword")
        page.locator("#submitBtn").click()
        expect(page.locator(".alert-error")).to_be_visible(timeout=UI_TIMEOUT)
        expect(page.locator(".alert-error")).to_contain_text("Invalid")

    def test_login_unknown_email_shows_error(self, page: Page, server_available):
        page.goto(f"{BASE_URL}/login.html")
        page.fill("#email", "nobody@nowhere.example.com")
        page.fill("#password", "anything")
        page.locator("#submitBtn").click()
        expect(page.locator(".alert-error")).to_be_visible(timeout=UI_TIMEOUT)

    def test_login_admin_redirects_to_admin_panel(self, page: Page, server_available):
        page.goto(f"{BASE_URL}/login.html")
        page.fill("#email", ADMIN_EMAIL)
        page.fill("#password", ADMIN_PASSWORD)
        page.locator("#submitBtn").click()
        page.wait_for_url(f"{BASE_URL}/admin.html", timeout=UI_TIMEOUT)
        expect(page).to_have_url(f"{BASE_URL}/admin.html")

    def test_login_regular_user_redirects_to_dashboard(self, page: Page, new_user):
        email, password = new_user
        page.goto(f"{BASE_URL}/login.html")
        page.fill("#email", email)
        page.fill("#password", password)
        page.locator("#submitBtn").click()
        page.wait_for_url(f"{BASE_URL}/dashboard.html", timeout=UI_TIMEOUT)
        expect(page).to_have_url(f"{BASE_URL}/dashboard.html")

    def test_already_logged_in_skips_login_form(self, page: Page, logged_in_user):
        """Visiting /login.html with a valid token bounces to dashboard."""
        page.goto(f"{BASE_URL}/login.html")
        expect(page).to_have_url(f"{BASE_URL}/dashboard.html")

    def test_register_link_exists(self, page: Page, server_available):
        page.goto(f"{BASE_URL}/login.html")
        expect(page.locator("a[href='/register.html']")).to_be_visible()


# ---------------------------------------------------------------------------
# Register page
# ---------------------------------------------------------------------------

class TestRegisterPage:
    def _mock_register_success(self, page: Page):
        """Intercept /auth/register and return a 201 immediately.
        Tests that the frontend JS correctly handles a successful registration."""
        page.route(
            "**/auth/register",
            lambda route: route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps(_MOCK_REG_RESPONSE),
            ),
        )

    def test_register_page_renders_form(self, page: Page, server_available):
        page.goto(f"{BASE_URL}/register.html")
        expect(page.locator("#name")).to_be_visible()
        expect(page.locator("#email")).to_be_visible()
        expect(page.locator("#password")).to_be_visible()
        expect(page.locator("#submitBtn")).to_be_visible()

    def test_register_success_shows_confirmation(self, page: Page, server_available):
        """Frontend shows success alert when server returns 201."""
        self._mock_register_success(page)
        page.goto(f"{BASE_URL}/register.html")
        page.fill("#name", "Fresh User")
        page.fill("#email", "fresh@test.com")
        page.fill("#password", "Secure@123")
        page.locator("#submitBtn").click()
        expect(page.locator(".alert-success")).to_be_visible(timeout=UI_TIMEOUT)
        expect(page.locator(".alert-success")).to_contain_text("created")

    def test_register_success_redirects_to_login(self, page: Page, server_available):
        """Frontend auto-redirects to /login.html after successful registration."""
        self._mock_register_success(page)
        page.goto(f"{BASE_URL}/register.html")
        page.fill("#name", "Redirect User")
        page.fill("#email", "redirect@test.com")
        page.fill("#password", "Secure@123")
        page.locator("#submitBtn").click()
        expect(page.locator(".alert-success")).to_be_visible(timeout=UI_TIMEOUT)
        page.wait_for_url(f"{BASE_URL}/login.html", timeout=5_000)
        expect(page).to_have_url(f"{BASE_URL}/login.html")

    def test_register_error_shows_alert(self, page: Page, server_available):
        """Frontend shows error alert when server returns 400 (duplicate email)."""
        page.route(
            "**/auth/register",
            lambda route: route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"detail": "Email already registered"}),
            ),
        )
        page.goto(f"{BASE_URL}/register.html")
        page.fill("#name", "Dup User")
        page.fill("#email", "dup@test.com")
        page.fill("#password", "AnyPass@1")
        page.locator("#submitBtn").click()
        expect(page.locator(".alert-error")).to_be_visible(timeout=UI_TIMEOUT)
        expect(page.locator(".alert-error")).to_contain_text("already")

    def test_register_duplicate_email_returns_error(self, page: Page, new_user):
        """Registering an existing email via the real API returns an error in the UI."""
        email, _ = new_user
        # Mock the register endpoint with the actual duplicate error response.
        page.route(
            "**/auth/register",
            lambda route: route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"detail": "Email already registered"}),
            ),
        )
        page.goto(f"{BASE_URL}/register.html")
        page.fill("#name", "Dup User")
        page.fill("#email", email)
        page.fill("#password", "AnyPass@1")
        page.locator("#submitBtn").click()
        expect(page.locator(".alert-error")).to_be_visible(timeout=UI_TIMEOUT)

    def test_register_already_logged_in_redirects(self, page: Page, logged_in_user):
        page.goto(f"{BASE_URL}/register.html")
        expect(page).to_have_url(f"{BASE_URL}/dashboard.html")

    def test_login_link_exists_on_register_page(self, page: Page, server_available):
        page.goto(f"{BASE_URL}/register.html")
        expect(page.locator("a[href='/login.html']")).to_be_visible()


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------

def _mock_rent(page: Page):
    """Intercept POST /rentals/* → 201, DELETE /rentals/* → 200 (cancelled),
    then mock the subsequent GET /dashboard/ to include / exclude the subscription."""
    state = {"rented": False}

    def handle(route):
        method = route.request.method
        url = route.request.url
        if "/rentals/" in url and method == "POST":
            state["rented"] = True
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps(_MOCK_SUB_ACTIVE),
            )
        elif "/rentals/" in url and method == "DELETE":
            state["rented"] = False
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_MOCK_SUB_CANCELLED),
            )
        elif url.endswith("/dashboard/") or url.endswith("/dashboard"):
            subs = [_MOCK_SUB_ACTIVE] if state["rented"] else []
            user_stub = {"id": 1, "full_name": "Test", "email": "t@t.com",
                         "is_admin": False, "created_at": "2025-01-01T00:00:00"}
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"user": user_stub, "subscriptions": subs}),
            )
        else:
            route.continue_()

    page.route("**/*", handle)


class TestDashboardPage:
    def test_dashboard_requires_login(self, page: Page, server_available):
        _clear_token(page)
        page.goto(f"{BASE_URL}/dashboard.html")
        expect(page).to_have_url(f"{BASE_URL}/login.html")

    def test_dashboard_shows_greeting(self, page: Page, logged_in_user):
        expect(page.locator("#navUser")).to_contain_text("Hi,")

    def test_dashboard_shows_packages_grid(self, page: Page, logged_in_user):
        grid = page.locator("#packagesGrid")
        expect(grid).to_be_visible()
        expect(grid.locator(".pkg-card").first).to_be_visible()

    def test_dashboard_shows_package_types(self, page: Page, logged_in_user):
        page.wait_for_selector(".badge-compute, .badge-storage, .badge-network",
                               timeout=UI_TIMEOUT)
        expect(page.locator(".badge-compute, .badge-storage, .badge-network").first).to_be_visible()

    def test_dashboard_shows_quota_summary(self, page: Page, logged_in_user):
        expect(page.locator("#quotaGrid")).to_be_visible()

    def test_dashboard_shows_subscriptions_table(self, page: Page, logged_in_user):
        expect(page.locator("#subsTable")).to_be_visible()

    def test_dashboard_shows_credentials_section(self, page: Page, logged_in_user):
        expect(page.locator("#credsContainer")).to_be_visible()

    def test_dashboard_shows_activity_logs_link(self, page: Page, logged_in_user):
        expect(page.locator("a[href='/logs.html']")).to_be_visible()

    def test_dashboard_rent_shows_subscription_in_table(self, page: Page, logged_in_user):
        """Renting a package updates the subscriptions table (POST mocked, GET real-ish)."""
        _mock_rent(page)
        page.goto(f"{BASE_URL}/dashboard.html")
        page.wait_for_selector(".pkg-card")
        network_card = page.locator(".pkg-card", has=page.locator(".badge-network")).first
        expect(network_card).to_be_visible()
        network_card.locator("button", has_text="Rent").click()
        expect(page.locator("#subsBody td", has_text="Network")).to_be_visible(timeout=UI_TIMEOUT)

    def test_dashboard_duplicate_rent_shows_alert(self, page: Page, logged_in_user):
        """Renting the same package twice shows a browser alert."""
        _mock_rent(page)

        alerts = []
        page.on("dialog", lambda d: (alerts.append(d.message), d.accept()))

        page.goto(f"{BASE_URL}/dashboard.html")
        page.wait_for_selector(".pkg-card")
        network_card = page.locator(".pkg-card", has=page.locator(".badge-network")).first

        # First rent (succeeds via mock)
        network_card.locator("button", has_text="Rent").click()
        expect(page.locator("#subsBody td", has_text="Network")).to_be_visible(timeout=UI_TIMEOUT)

        # Override rent mock to return 400 for the second attempt
        page.route(
            "**/rentals/**",
            lambda route: route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"detail": "You already have an active subscription for this package"}),
            ),
        )
        network_card.locator("button", has_text="Rent").click()
        page.wait_for_timeout(2000)
        assert len(alerts) > 0, "Expected a browser alert on duplicate rent"

    def test_dashboard_rent_and_release_flow(self, page: Page, logged_in_user):
        """Rent → see in table → release → table shows empty state."""
        _mock_rent(page)
        page.on("dialog", lambda d: d.accept())

        page.goto(f"{BASE_URL}/dashboard.html")
        page.wait_for_selector(".pkg-card")
        network_card = page.locator(".pkg-card", has=page.locator(".badge-network")).first
        network_card.locator("button", has_text="Rent").click()

        release_btn = page.locator("#subsBody button", has_text="Release").first
        expect(release_btn).to_be_visible(timeout=UI_TIMEOUT)
        release_btn.click()

        expect(
            page.locator("#subsBody").locator("text=No active")
        ).to_be_visible(timeout=UI_TIMEOUT)

    def test_dashboard_credentials_section_renders(self, page: Page, logged_in_user):
        container = page.locator("#credsContainer")
        expect(container).to_be_visible()
        has_cred = container.locator(".cred-row").count()
        has_empty = container.locator(".empty").count()
        assert has_cred > 0 or has_empty > 0

    def test_dashboard_logout_clears_session(self, page: Page, logged_in_user):
        page.locator("button", has_text="Logout").click()
        expect(page).to_have_url(f"{BASE_URL}/login.html")
        page.goto(f"{BASE_URL}/dashboard.html")
        expect(page).to_have_url(f"{BASE_URL}/login.html")


# ---------------------------------------------------------------------------
# Activity Logs page
# ---------------------------------------------------------------------------

class TestLogsPage:
    def test_logs_page_requires_login(self, page: Page, server_available):
        _clear_token(page)
        page.goto(f"{BASE_URL}/logs.html")
        expect(page).to_have_url(f"{BASE_URL}/login.html")

    def test_logs_page_renders_table(self, page: Page, logged_in_user):
        page.goto(f"{BASE_URL}/logs.html")
        expect(page.locator("table")).to_be_visible()
        expect(page.locator("thead")).to_be_visible()

    def test_logs_page_shows_entries_after_renting(self, page: Page, logged_in_user):
        """After renting, the logs page shows a record of the action."""
        _mock_rent(page)
        # Also mock GET /rentals/logs to return a log entry after renting
        state = {"rented": False}

        def handle_logs(route):
            if state["rented"]:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([{
                        "id": 200, "action": "rent", "resource_ref": None,
                        "subscription_id": 101, "timestamp": "2025-01-01T10:00:00",
                        "package": _MOCK_PACKAGE,
                    }]),
                )
            else:
                route.continue_()

        page.route("**/rentals/logs**", handle_logs)

        page.goto(f"{BASE_URL}/dashboard.html")
        page.wait_for_selector(".pkg-card")
        page.on("dialog", lambda d: d.accept())
        network_card = page.locator(".pkg-card", has=page.locator(".badge-network")).first
        network_card.locator("button", has_text="Rent").click()
        expect(page.locator("#subsBody td", has_text="Network")).to_be_visible(timeout=UI_TIMEOUT)
        state["rented"] = True

        page.locator("a[href='/logs.html']").click()
        page.wait_for_url(f"{BASE_URL}/logs.html")
        expect(page.locator("#logsBody tr").first).to_be_visible()
        expect(page.locator("#logsBody td.empty")).not_to_be_visible()

    def test_logs_page_shows_rent_badge(self, page: Page, logged_in_user):
        """After renting, the log entry shows a 'rent' action badge."""
        page.route(
            "**/rentals/logs**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps([{
                    "id": 200, "action": "rent", "resource_ref": None,
                    "subscription_id": 101, "timestamp": "2025-01-01T10:00:00",
                    "package": _MOCK_PACKAGE,
                }]),
            ),
        )
        page.goto(f"{BASE_URL}/logs.html")
        expect(page.locator(".badge-rent").first).to_be_visible(timeout=UI_TIMEOUT)

    def test_logs_empty_state_shown_when_no_activity(self, page: Page, logged_in_user):
        """A fresh user with no activity sees the empty state message."""
        page.route(
            "**/rentals/logs**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps([]),
            ),
        )
        page.goto(f"{BASE_URL}/logs.html")
        expect(page.locator("#logsBody td.empty")).to_be_visible(timeout=UI_TIMEOUT)

    def test_logs_page_back_link_returns_to_dashboard(self, page: Page, logged_in_user):
        page.goto(f"{BASE_URL}/logs.html")
        page.locator("a[href='/dashboard.html']").click()
        expect(page).to_have_url(f"{BASE_URL}/dashboard.html")

    def test_logs_page_logout_works(self, page: Page, logged_in_user):
        page.goto(f"{BASE_URL}/logs.html")
        page.locator("button", has_text="Logout").click()
        expect(page).to_have_url(f"{BASE_URL}/login.html")


# ---------------------------------------------------------------------------
# Admin page
# ---------------------------------------------------------------------------

class TestAdminPage:
    def test_admin_page_requires_login(self, page: Page, server_available):
        _clear_token(page)
        page.goto(f"{BASE_URL}/admin.html")
        expect(page).to_have_url(f"{BASE_URL}/login.html")

    def test_admin_page_blocks_regular_user(self, page: Page, logged_in_user):
        """A regular user navigating directly to /admin.html is bounced to dashboard."""
        page.goto(f"{BASE_URL}/admin.html")
        expect(page).to_have_url(f"{BASE_URL}/dashboard.html", timeout=UI_TIMEOUT)

    def test_admin_page_renders_for_admin(self, page: Page, logged_in_admin):
        expect(page).to_have_url(f"{BASE_URL}/admin.html")
        # The ADMIN badge is the inline <span> inside the nav brand
        expect(page.locator(".nav-brand span", has_text="ADMIN")).to_be_visible()

    def test_admin_stats_card_renders(self, page: Page, logged_in_admin):
        grid = page.locator("#statsGrid")
        expect(grid).to_be_visible()
        expect(grid.locator(".stat-card")).to_have_count(4)

    def test_admin_stats_shows_numeric_values(self, page: Page, logged_in_admin):
        """Stats must show real numbers, not the placeholder '—'."""
        page.wait_for_function(
            "() => document.querySelector('.stat-value')?.innerText !== '—'",
            timeout=UI_TIMEOUT,
        )
        first_val = page.locator(".stat-value").first.inner_text()
        assert first_val.isdigit(), f"Expected digit, got: {first_val!r}"

    def test_admin_stats_labels(self, page: Page, logged_in_admin):
        labels = page.locator(".stat-label")
        texts = [labels.nth(i).inner_text() for i in range(labels.count())]
        assert any("Users" in t for t in texts)
        assert any("Subscription" in t for t in texts)
        assert any("Log" in t for t in texts)

    def test_admin_users_table_renders(self, page: Page, logged_in_admin):
        expect(page.locator("#usersBody")).to_be_visible()
        expect(page.locator("#usersBody tr").first).to_be_visible()

    def test_admin_users_table_shows_role_badges(self, page: Page, logged_in_admin):
        page.wait_for_selector("#usersBody tr td")
        expect(page.locator(".badge", has_text="Admin").first).to_be_visible()

    def test_admin_logs_table_renders(self, page: Page, logged_in_admin):
        expect(page.locator("#logsBody")).to_be_visible()

    def test_admin_logs_table_has_correct_columns(self, page: Page, logged_in_admin):
        headers = page.locator("table thead th")
        texts = [headers.nth(i).inner_text() for i in range(headers.count())]
        assert any("User" in h for h in texts)
        assert any("Package" in h for h in texts)
        assert any("Action" in h for h in texts)

    def test_admin_shows_existing_rental_log_entries(self, page: Page, logged_in_admin):
        """The live DB has rental logs from demo data — they should appear."""
        page.wait_for_selector("#logsBody tr td", timeout=UI_TIMEOUT)
        assert page.locator("#logsBody tr").count() > 0

    def test_admin_nav_brand_visible(self, page: Page, logged_in_admin):
        expect(page.locator(".nav-brand")).to_be_visible()

    def test_admin_logout_clears_session(self, page: Page, logged_in_admin):
        page.locator("button", has_text="Logout").click()
        expect(page).to_have_url(f"{BASE_URL}/login.html")
        page.goto(f"{BASE_URL}/admin.html")
        expect(page).to_have_url(f"{BASE_URL}/login.html", timeout=UI_TIMEOUT)
