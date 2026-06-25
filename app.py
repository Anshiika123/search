from flask import Flask, render_template, request, jsonify, send_file
import time
import json
import re
import os
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

# Store results in memory
search_results = {}

def scrape_linkedin(topic, email, password):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "Playwright not installed. Run: pip install playwright && playwright install chromium"}

    posts = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        # Try saved cookies first
        cookie_file = Path(__file__).parent / "linkedin_cookies.json"
        logged_in = False

        if cookie_file.exists():
            with open(cookie_file) as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            page.goto("https://www.linkedin.com/feed/")
            time.sleep(3)
            if "feed" in page.url or "mynetwork" in page.url:
                logged_in = True

        if not logged_in:
            page.goto("https://www.linkedin.com/login")
            time.sleep(2)
            page.fill("#username", email)
            page.fill("#password", password)
            page.click("[type='submit']")
            time.sleep(4)

            if "feed" not in page.url and "mynetwork" not in page.url and "jobs" not in page.url:
                browser.close()
                return {"error": "Login failed. Check your email/password."}

            # Save cookies
            cookies = context.cookies()
            with open(cookie_file, "w") as f:
                json.dump(cookies, f)

        # Go to search
        search_url = f"https://www.linkedin.com/search/results/content/?keywords={topic.replace(' ', '%20')}&sortBy=RELEVANCE"
        page.goto(search_url)
        time.sleep(4)

        # Scroll to load posts
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 1500)")
            time.sleep(1.5)

        # Find containers
        containers = []
        for selector in [
            ".reusable-search__result-container",
            "li.reusable-search__result-container",
            ".occludable-update",
        ]:
            containers = page.query_selector_all(selector)
            if containers:
                break

        for container in containers:
            if len(posts) >= 10:
                break
            try:
                post = {}

                # Author name
                for sel in [".entity-result__title-text a span[aria-hidden='true']",
                            ".update-components-actor__name span[aria-hidden='true']",
                            ".app-aware-link span[aria-hidden='true']"]:
                    el = container.query_selector(sel)
                    if el:
                        post["author_name"] = el.inner_text().strip()
                        break

                # Profile URL
                for sel in [".entity-result__title-text a", ".update-components-actor__meta a"]:
                    el = container.query_selector(sel)
                    if el:
                        href = el.get_attribute("href") or ""
                        if "/in/" in href or "/company/" in href:
                            post["profile_url"] = href.split("?")[0]
                            break

                # Post URL
                for sel in ["a[href*='/posts/']", "a[href*='/feed/update/']"]:
                    el = container.query_selector(sel)
                    if el:
                        href = el.get_attribute("href") or ""
                        if href:
                            clean = href.split("?")[0]
                            post["post_url"] = clean if clean.startswith("http") else f"https://www.linkedin.com{clean}"
                            break

                # Context
                for sel in [".feed-shared-update-v2__description",
                            ".update-components-text",
                            ".entity-result__summary",
                            "span[dir='ltr']"]:
                    el = container.query_selector(sel)
                    if el:
                        text = el.inner_text().strip()
                        if len(text) > 20:
                            post["context"] = text[:400] + ("..." if len(text) > 400 else "")
                            break

                if post.get("post_url") and post["post_url"] not in seen_urls:
                    seen_urls.add(post["post_url"])
                    post.setdefault("author_name", "Unknown")
                    post.setdefault("profile_url", "")
                    post.setdefault("context", "No context found")
                    posts.append(post)
            except:
                pass

        browser.close()

    return {"posts": posts, "topic": topic, "count": len(posts)}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    data = request.json
    topic = data.get("topic", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not topic:
        return jsonify({"error": "Topic is required"})
    if not email or not password:
        # Check if cookies exist (already logged in)
        cookie_file = Path(__file__).parent / "linkedin_cookies.json"
        if not cookie_file.exists():
            return jsonify({"error": "Email and password required for first login"})

    result = scrape_linkedin(topic, email, password)
    if "posts" in result:
        search_results["last"] = result
    return jsonify(result)


@app.route("/export")
def export():
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        return "openpyxl not installed", 500

    data = search_results.get("last")
    if not data:
        return "No results to export", 400

    posts = data["posts"]
    topic = data["topic"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LinkedIn Posts"

    header_fill = PatternFill("solid", fgColor="0A66C2")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Title
    ws.merge_cells("A1:E1")
    ws["A1"].value = f'LinkedIn Search: "{topic}" — Top {len(posts)} Posts'
    ws["A1"].font = Font(bold=True, size=13, color="0A66C2")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:E2")
    ws["A2"].value = f"Generated: {datetime.now().strftime('%d %B %Y, %I:%M %p')}"
    ws["A2"].font = Font(italic=True, color="888888", size=10)
    ws["A2"].alignment = Alignment(horizontal="center")

    headers = ["#", "Author", "Profile Link", "Post Link", "Context"]
    widths = [5, 22, 38, 38, 55]
    for col, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=3, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[3].height = 22

    for i, post in enumerate(posts, 1):
        row = i + 3
        alt = PatternFill("solid", fgColor="EBF3FB") if i % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        for col, val in enumerate([i, post.get("author_name",""), post.get("profile_url",""), post.get("post_url",""), post.get("context","")], 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.fill = alt
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if col in (3, 4) and val:
                cell.font = Font(color="0A66C2", underline="single")
        ws.row_dimensions[row].height = 55

    ws.freeze_panes = "A4"

    safe = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
    filename = f"LinkedIn_{safe}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    filepath = Path(__file__).parent / filename
    wb.save(filepath)
    return send_file(filepath, as_attachment=True, download_name=filename)


if __name__ == "__main__":
    print("\n🚀 LinkedIn Search App running at: http://localhost:5000\n")
    app.run(debug=True, port=5000)
