import os
import re
import json
import anthropic
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")


def refine_query_with_claude(topic: str) -> str:
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=256,
        system=(
            "You craft Google search queries to find LinkedIn posts. "
            "Given a topic, return ONLY the search query string — no explanation, no quotes around it. "
            "Do NOT include 'site:linkedin.com' — that is added automatically. "
            "Focus on keywords that appear in professional LinkedIn post content about that topic."
        ),
        messages=[{
            "role": "user",
            "content": f"Topic: {topic}"
        }]
    )
    return response.content[0].text.strip()


def search_linkedin_posts(refined_query: str) -> list[dict]:
    url = "https://www.googleapis.com/customsearch/v1"
    full_query = f"site:linkedin.com/posts/ {refined_query}"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": full_query,
        "num": 10,
    }
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        return []

    items = resp.json().get("items", [])
    results = []
    for item in items:
        post_url = item.get("link", "")
        results.append({
            "post_url": post_url,
            "profile_url": _extract_profile_url(post_url),
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def _extract_profile_url(post_url: str) -> str:
    # LinkedIn post URL: https://www.linkedin.com/posts/username_activity-...
    try:
        after_posts = post_url.split("/posts/")[1]
        # username is everything before the first underscore
        username = after_posts.split("_")[0]
        if username:
            return f"https://www.linkedin.com/in/{username}/"
    except (IndexError, AttributeError):
        pass
    return ""


def rank_and_summarize(topic: str, raw_results: list[dict]) -> list[dict]:
    numbered = ""
    for i, r in enumerate(raw_results, 1):
        numbered += (
            f"\n[{i}] Title: {r['title']}\n"
            f"    Post URL: {r['post_url']}\n"
            f"    Profile URL: {r['profile_url']}\n"
            f"    Snippet: {r['snippet']}\n"
        )

    prompt = (
        f"Topic: {topic}\n\n"
        f"LinkedIn search results:{numbered}\n\n"
        "Rank these results by relevance to the topic. "
        "Return a JSON array (no markdown fences) where each object has:\n"
        "  rank (int), post_url (str), profile_url (str), context (2-3 sentence summary of what the post discusses), relevance_score (1-10 int)\n"
        "Use the exact URLs from the input. Output ONLY valid JSON."
    )

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        system="You are an expert LinkedIn content analyst. Respond only with valid JSON.",
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    # Strip optional markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        ranked = json.loads(text)
        # Ensure profile_url is populated if Claude omitted it
        url_to_profile = {r["post_url"]: r["profile_url"] for r in raw_results}
        for item in ranked:
            if not item.get("profile_url"):
                item["profile_url"] = url_to_profile.get(item.get("post_url", ""), "")
        return ranked
    except json.JSONDecodeError:
        # Fallback: return raw results with snippet as context
        return [
            {
                "rank": i,
                "post_url": r["post_url"],
                "profile_url": r["profile_url"],
                "context": r["snippet"],
                "relevance_score": 10 - i,
            }
            for i, r in enumerate(raw_results[:10], 1)
        ]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()

    if not topic:
        return jsonify({"error": "Topic is required"}), 400

    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return jsonify({"error": "Google API credentials not configured"}), 500

    refined_query = refine_query_with_claude(topic)
    raw_results = search_linkedin_posts(refined_query)

    if not raw_results:
        return jsonify({
            "topic": topic,
            "refined_query": refined_query,
            "results": [],
            "message": "No LinkedIn posts found. Try a different topic."
        })

    ranked = rank_and_summarize(topic, raw_results)

    return jsonify({
        "topic": topic,
        "refined_query": refined_query,
        "results": ranked,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
