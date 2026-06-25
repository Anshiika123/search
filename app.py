from flask import Flask, render_template, request, jsonify, send_file
import requests
import re
import os
import io
import urllib.parse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
search_results = {}
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")


def parse_keywords(topic: str) -> list:
    raw = re.split(r'[\s,&+/]+', topic.strip())
    stopwords = {'and','or','the','a','an','for','with','in','on','at','to'}
    return [w.lower() for w in raw if len(w) >= 2 and w.lower() not in stopwords]


def keyword_score(text: str, keywords: list) -> int:
    t = text.lower()
    return sum(1 for kw in keywords if kw in t)


def serpapi_search(query: str, api_key: str, num: int = 10) -> list:
    """Call SerpAPI Google Search. Returns list of organic results."""
    try:
        resp = requests.get("https://serpapi.com/search", params={
            "q": query,
            "api_key": api_key,
            "engine": "google",
            "num": num,
            "hl": "en",
        }, timeout=15)
        data = resp.json()
        if "error" in data:
            print(f"SerpAPI error: {data['error']}")
            return []
        return data.get("organic_results", [])
    except Exception as e:
        print(f"SerpAPI request failed: {e}")
        return []


def parse_profile_signals(snippet: str, title: str) -> dict:
    """Extract current company, job title, open to work, seniority from snippet/title."""
    text = (title + " " + snippet).lower()
    raw  = title + " " + snippet

    open_to_work = any(p in text for p in [
        "open to work", "open to opportunities", "looking for opportunities",
        "seeking new role", "available for hire", "actively looking"
    ])

    current_company = ""
    company_patterns = [
        r'\bat\s+([A-Z][A-Za-z0-9\s&.,]{2,30}?)(?:\s*[|·\-]|\s*$)',
        r'[@·]\s*([A-Z][A-Za-z0-9\s&.,]{2,25}?)(?:\s*[|·\-]|\s*$)',
        r'-\s*([A-Z][A-Za-z0-9\s&.,]{2,25}?)\s*(?:LinkedIn|$)',
    ]
    for pat in company_patterns:
        m = re.search(pat, raw)
        if m:
            candidate = m.group(1).strip().rstrip('.,')
            if len(candidate) > 2 and candidate.lower() not in ('linkedin','the','and','for'):
                current_company = candidate
                break

    job_title = ""
    title_clean = re.sub(r'\s*\|.*', '', title).strip()
    title_clean = re.sub(r'\s*-\s*(LinkedIn|Profile).*', '', title_clean, flags=re.I).strip()
    title_clean = re.sub(r'\s+on\s+LinkedIn.*', '', title_clean, flags=re.I).strip()
    parts = re.split(r'\s*[-–|·]\s*', title_clean)
    if len(parts) >= 2:
        job_title = parts[1].strip()
    elif len(parts) == 1 and len(parts[0]) < 80:
        job_title = parts[0].strip()

    seniority_score = 0
    seniority_keywords = {
        5: ['cto','ceo','coo','ciso','chief','vp ','vice president','founder','co-founder'],
        4: ['director','head of','principal','distinguished','fellow'],
        3: ['senior','sr.','lead','staff','architect','manager'],
        2: ['mid','associate','consultant','specialist'],
        1: ['junior','jr.','intern','trainee','fresher','student'],
    }
    for score, kws in seniority_keywords.items():
        if any(kw in text for kw in kws):
            seniority_score = score
            break

    exp_years = 0
    m = re.search(r'(\d{1,2})\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)', text)
    if m:
        exp_years = int(m.group(1))
        seniority_score = max(seniority_score, min(5, exp_years // 3))

    is_active = bool(re.search(
        r'\b(\d+[hm]\s*ago|today|yesterday|just now|\d+\s*days?\s*ago|this week)\b', text
    ))

    return {
        "current_company": current_company,
        "job_title": job_title,
        "open_to_work": open_to_work,
        "seniority_score": seniority_score,
        "exp_years": exp_years,
        "is_active": is_active,
    }


SENIORITY_WORDS = {
    5: ["vp ", "vice president", "cto", "ceo", "coo", "chief", "director", "head of"],
    4: ["principal", "staff ", "distinguished", "partner"],
    3: ["senior ", "sr.", "sr ", "lead ", "manager", "architect"],
    2: ["mid ", "software engineer", "data scientist", "analyst"],
    1: ["junior", "jr.", "jr ", "associate", "intern", "fresher"],
}
OPEN_TO_WORK_SIGNALS = ["open to work", "open to opportunities", "seeking opportunities", "looking for", "available for", "#opentowork"]
CURRENT_WORK_PATTERNS = [
    r'(?:at|@)\s+([A-Z][A-Za-z0-9& ]{2,30})',
    r'([A-Z][A-Za-z0-9& ]{2,25})\s+(?:\||-)\s+LinkedIn',
]
EXP_PATTERNS = [
    r'(\d+)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)',
    r'(\d+)\s*-\s*\d+\s*(?:years?|yrs?)',
]
TITLE_PATTERNS = [
    r'(?:^|·\s*)([A-Z][A-Za-z ,&/]+?)\s+(?:at|@|\||–|-)\s+',
    r'([A-Z][A-Za-z ,&/]+?)\s+-\s+LinkedIn',
]


def parse_profile_signals(snippet: str, title: str) -> dict:
    text = (snippet + " " + title).lower()

    open_to_work = any(s in text for s in OPEN_TO_WORK_SIGNALS)

    company = ""
    for pat in CURRENT_WORK_PATTERNS:
        m = re.search(pat, title + " " + snippet)
        if m:
            company = m.group(1).strip()
            break

    exp_years = 0
    for pat in EXP_PATTERNS:
        m = re.search(pat, text)
        if m:
            exp_years = int(m.group(1))
            break

    seniority = 0
    for level, words in SENIORITY_WORDS.items():
        if any(w in text for w in words):
            seniority = level
            break

    job_title = ""
    for pat in TITLE_PATTERNS:
        m = re.search(pat, title)
        if m:
            job_title = m.group(1).strip()
            break

    is_active = any(w in text for w in ["just posted", "1h", "2h", "today", "this week"])

    return {
        "open_to_work": open_to_work,
        "current_company": company,
        "exp_years": exp_years,
        "seniority_score": seniority,
        "job_title": job_title,
        "is_active": is_active,
    }


def extract_author(url: str, title: str) -> tuple:
    author_name = "LinkedIn User"
    profile_url = ""
    clean = re.sub(r'<[^>]+>', '', title).strip()
    if " on LinkedIn" in clean:
        author_name = clean.split(" on LinkedIn")[0].strip()
    elif " - " in clean and "LinkedIn" in clean:
        author_name = clean.split(" - ")[0].strip()
    elif " | LinkedIn" in clean:
        author_name = clean.split(" | LinkedIn")[0].strip()

    slug_m = re.search(r'linkedin\.com/in/([a-zA-Z0-9][a-zA-Z0-9\-]+)', url)
    if slug_m:
        slug = re.sub(r'-\d{10,}.*$', '', slug_m.group(1)).strip('-')
        profile_url = f"https://www.linkedin.com/in/{slug}"
        if author_name == "LinkedIn User":
            author_name = slug.replace("-", " ").title()

    slug_m2 = re.search(r'linkedin\.com/posts/([a-zA-Z0-9][a-zA-Z0-9\-]+)', url)
    if slug_m2 and not profile_url:
        slug = re.sub(r'-\d{10,}.*$', '', slug_m2.group(1)).strip('-')
        profile_url = f"https://www.linkedin.com/in/{slug}"
        if author_name == "LinkedIn User":
            author_name = slug.replace("-", " ").title()

    return author_name, profile_url


def search_profiles(keywords, region, api_key, max_results):
    kw = " ".join(keywords)
    region_parts = [p for p in re.split(r'[\s,]+', region) if len(p) > 2] if region else []
    region_q = " ".join(region_parts[:2]) if region_parts else ""

    queries = []
    if region_q:
        queries += [f'site:linkedin.com/in/ "{kw}" "{region_q}"']
        queries += [f'site:linkedin.com/in/ {kw} {region_q}']
    queries += [f'site:linkedin.com/in/ {kw}']

    candidates = []
    seen = set()

    for query in queries:
        if len(candidates) >= max_results * 2:
            break
        items = serpapi_search(query, api_key, num=10)
        for item in items:
            url     = item.get("link", "")
            title   = item.get("title", "")
            snippet = item.get("snippet", "")

            if "linkedin.com/in/" not in url and "linkedin.com/in/" not in url.replace("in.linkedin","linkedin"):
                continue
            url = url.replace("https://in.linkedin.com", "https://www.linkedin.com")
            url = url.split("?")[0].rstrip("/")
            if url in seen:
                continue
            seen.add(url)

            author, profile_url = extract_author(url, title)
            full = (title + " " + snippet).lower()
            signals = parse_profile_signals(snippet, title)
            region_match = any(p.lower() in full for p in region_parts) if region_parts else False

            score = keyword_score(full, keywords)
            if region_match: score += 3
            score += signals["seniority_score"]
            if signals["exp_years"] >= 5: score += 2
            if signals["is_active"]: score += 1

            post_search = f"https://www.linkedin.com/search/results/content/?keywords={urllib.parse.quote(author)}"
            candidates.append((score, {
                "author_name": author,
                "profile_url": profile_url or url,
                "post_url": post_search,
                "post_url_label": "🔍 Find Posts",
                "context": snippet[:400],
                "matched_keywords": keyword_score(full, keywords),
                "total_keywords": len(keywords),
                "region_match": region_match,
                "verified_signal": False,
                "result_type": "profile",
                "likes": 0, "comments": 0,
                "current_company": signals["current_company"],
                "job_title": signals["job_title"],
                "open_to_work": signals["open_to_work"],
                "seniority_score": signals["seniority_score"],
                "exp_years": signals["exp_years"],
                "is_active": signals["is_active"],
            }))

    return candidates


def search_posts(keywords, region, api_key, max_results):
    kw = " ".join(keywords)
    region_parts = [p for p in re.split(r'[\s,]+', region) if len(p) > 2] if region else []

    queries = [f'site:linkedin.com/posts/ {kw}', f'site:linkedin.com/feed/update/ {kw}']

    candidates = []
    seen = set()

    for query in queries:
        if len(candidates) >= max_results * 2:
            break
        items = serpapi_search(query, api_key, num=10)
        for item in items:
            url     = item.get("link", "")
            title   = item.get("title", "")
            snippet = item.get("snippet", "")

            if "linkedin.com/posts/" not in url and "linkedin.com/feed/update/" not in url:
                continue
            url = url.replace("https://in.linkedin.com", "https://www.linkedin.com")
            url = url.split("?")[0].rstrip("/")
            if url in seen:
                continue
            seen.add(url)

            author, profile_url = extract_author(url, title)
            full = (title + " " + snippet).lower()
            signals = parse_profile_signals(snippet, title)
            region_match = any(p.lower() in full for p in region_parts) if region_parts else False

            score = keyword_score(full, keywords)
            if region_match: score += 2
            if signals["is_active"]: score += 1

            candidates.append((score, {
                "author_name": author,
                "profile_url": profile_url,
                "post_url": url,
                "post_url_label": "📄 Open Post",
                "context": snippet[:400],
                "matched_keywords": keyword_score(full, keywords),
                "total_keywords": len(keywords),
                "region_match": region_match,
                "verified_signal": False,
                "result_type": "post",
                "likes": 0, "comments": 0,
                "current_company": signals["current_company"],
                "job_title": signals["job_title"],
                "open_to_work": signals["open_to_work"],
                "seniority_score": signals["seniority_score"],
                "exp_years": signals["exp_years"],
                "is_active": signals["is_active"],
            }))

    return candidates


def search_linkedin(topic, max_results=5, region="", verified_only=False,
                    search_mode="both", api_key=""):
    api_key = api_key or SERPAPI_KEY
    if not api_key:
        return {"error": "SerpAPI key missing. Please enter it below."}

    keywords = parse_keywords(topic)
    if not keywords:
        return {"error": "Please enter a topic."}

    candidates = []
    if search_mode in ("profiles", "both"):
        candidates += search_profiles(keywords, region, api_key, max_results)
    if search_mode in ("posts", "both"):
        candidates += search_posts(keywords, region, api_key, max_results)

    if not candidates:
        return {"error": f"No results found for '{topic}'" + (f" in '{region}'" if region else "") + ". Try different keywords."}

    candidates.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    posts = []
    for _, p in candidates:
        key = p.get("profile_url") or p.get("post_url")
        if key not in seen:
            seen.add(key)
            posts.append(p)
        if len(posts) >= max_results:
            break

    return {"posts": posts, "topic": topic, "count": len(posts),
            "keywords": keywords, "region": region, "verified_only": verified_only,
            "search_mode": search_mode}


@app.route("/debug")
def debug():
    api_key = SERPAPI_KEY
    query = request.args.get("q", "site:linkedin.com/in/ python Bangalore")
    try:
        resp = requests.get("https://serpapi.com/search", params={
            "q": query, "api_key": api_key, "engine": "google", "num": 5
        }, timeout=15)
        data = resp.json()
    except Exception as e:
        return f"<pre>Error: {e}</pre>"

    if "error" in data:
        return f"<h3>Query: {query}</h3><p style='color:red'>Error: {data['error']}</p>"

    items = data.get("organic_results", [])
    out = f"<h3>Query: {query}</h3><p>Results: {len(items)}</p>"
    for i, item in enumerate(items, 1):
        out += f"<hr><b>#{i}</b> {item.get('title','')}<br>"
        out += f"<a href='{item.get('link','')}'>{ item.get('link','')}</a><br>"
        out += f"Snippet: {item.get('snippet','')}"
    return out


@app.route("/")
def index():
    return render_template("index.html", has_creds=bool(SERPAPI_KEY))


@app.route("/search", methods=["POST"])
def search():
    data = request.json
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"error": "Please enter a topic."})
    result = search_linkedin(
        topic,
        max_results=int(data.get("max_results", 5)),
        region=data.get("region", "").strip(),
        verified_only=bool(data.get("verified_only", False)),
        search_mode=data.get("search_mode", "both"),
        api_key=data.get("api_key", "").strip(),
    )
    if "posts" in result:
        search_results["last"] = result
    return jsonify(result)


@app.route("/save_creds", methods=["POST"])
def save_creds():
    data = request.json
    key  = data.get("api_key", "").strip()
    if not key:
        return jsonify({"error": "Key required."})
    env_path = Path(__file__).parent / ".env"
    env_path.write_text(f"SERPAPI_KEY={key}\n")
    global SERPAPI_KEY
    SERPAPI_KEY = key
    return jsonify({"ok": True})


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

    posts  = data["posts"]
    topic  = data["topic"]
    region = data.get("region", "")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LinkedIn Results"
    hf = PatternFill("solid", fgColor="0A66C2")
    hfont = Font(color="FFFFFF", bold=True, size=11)
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    title_val = f'LinkedIn: "{topic}"' + (f' | {region}' if region else '') + f' — {len(posts)} results'
    ws.merge_cells("A1:G1")
    ws["A1"].value = title_val
    ws["A1"].font  = Font(bold=True, size=13, color="0A66C2")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    ws.merge_cells("A2:G2")
    ws["A2"].value = f"Generated: {datetime.now().strftime('%d %B %Y, %I:%M %p')}"
    ws["A2"].font  = Font(italic=True, color="888888", size=10)
    ws["A2"].alignment = Alignment(horizontal="center")

    cols   = ["#","Type","Author","Profile Link","Post / Search Link","Snippet","Region Match"]
    widths = [5, 10, 22, 40, 42, 55, 14]
    for c,(h,w) in enumerate(zip(cols,widths),1):
        cell = ws.cell(row=3, column=c, value=h)
        cell.fill=hf; cell.font=hfont; cell.border=border
        cell.alignment=Alignment(horizontal="center",vertical="center")
        ws.column_dimensions[cell.column_letter].width=w
    ws.row_dimensions[3].height=20

    for i,post in enumerate(posts,1):
        row=i+3
        alt=PatternFill("solid",fgColor="EBF3FB" if i%2==0 else "FFFFFF")
        vals=[i,
              "Profile" if post.get("result_type")=="profile" else "Post",
              post.get("author_name",""),
              post.get("profile_url",""),
              post.get("post_url",""),
              post.get("context",""),
              "✓" if post.get("region_match") else "—"]
        for c,v in enumerate(vals,1):
            cell=ws.cell(row=row,column=c,value=v)
            cell.fill=alt; cell.border=border
            cell.alignment=Alignment(vertical="top",wrap_text=True)
            if c in(4,5) and v: cell.font=Font(color="0A66C2",underline="single")
        ws.row_dimensions[row].height=55

    ws.freeze_panes="A4"
    safe=re.sub(r'[^\w\s-]','',topic).strip().replace(' ','_')
    fname=f"LinkedIn_{safe}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    buf=io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\nLinkedIn Search App → http://localhost:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port)
