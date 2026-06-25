const topicInput = document.getElementById("topicInput");
const searchBtn  = document.getElementById("searchBtn");
const btnText    = document.getElementById("btnText");
const btnSpinner = document.getElementById("btnSpinner");

topicInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const topic = topicInput.value.trim();
  if (!topic) { topicInput.focus(); return; }

  setLoading(true);
  clearUI();

  try {
    const res  = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });
    const data = await res.json();

    if (!res.ok) {
      showError(data.error || "Something went wrong. Please try again.");
      return;
    }

    if (data.refined_query) showRefinedQuery(data.refined_query);

    if (!data.results || data.results.length === 0) {
      document.getElementById("emptyState").classList.remove("hidden");
    } else {
      renderResults(data.results);
    }
  } catch (err) {
    showError("Network error — is the server running?");
  } finally {
    setLoading(false);
  }
}

function setLoading(on) {
  searchBtn.disabled = on;
  btnText.textContent = on ? "Searching…" : "Search";
  btnSpinner.classList.toggle("hidden", !on);
}

function clearUI() {
  document.getElementById("refinedQuery").classList.add("hidden");
  document.getElementById("errorBox").classList.add("hidden");
  document.getElementById("results").classList.add("hidden");
  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("cardGrid").innerHTML = "";
}

function showRefinedQuery(q) {
  document.getElementById("queryText").textContent = q;
  document.getElementById("refinedQuery").classList.remove("hidden");
}

function showError(msg) {
  const box = document.getElementById("errorBox");
  box.textContent = msg;
  box.classList.remove("hidden");
}

function renderResults(results) {
  const grid  = document.getElementById("cardGrid");
  const wrap  = document.getElementById("results");
  const count = document.getElementById("resultsCount");

  count.textContent = `${results.length} posts found`;
  grid.className = "card-grid";

  results.forEach(item => {
    const card = document.createElement("div");
    card.className = "card";

    const rank = item.rank || "—";
    const title = escHtml(item.title || item.post_url || "LinkedIn Post");
    const context = escHtml(item.context || "");
    const score = item.relevance_score ? `Relevance: ${item.relevance_score}/10` : "";

    const profileBtn = item.profile_url
      ? `<a class="btn-link btn-profile" href="${escAttr(item.profile_url)}" target="_blank" rel="noopener">
           <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.7 0 4.8-2.1 4.8-4.8S14.7 2.4 12 2.4 7.2 4.5 7.2 7.2 9.3 12 12 12zm0 2.4c-3.2 0-9.6 1.6-9.6 4.8v2.4h19.2v-2.4c0-3.2-6.4-4.8-9.6-4.8z"/></svg>
           View Profile
         </a>`
      : "";

    const postBtn = item.post_url
      ? `<a class="btn-link btn-post" href="${escAttr(item.post_url)}" target="_blank" rel="noopener">
           <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M14 3v2H5v14h14v-9h2v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10zm5-2v6h-2V4.414l-7.293 7.293-1.414-1.414L17.586 3H14V1h5z"/></svg>
           View Post
         </a>`
      : "";

    card.innerHTML = `
      <div class="rank-badge">${rank}</div>
      <div class="card-body">
        <div class="card-title">${title}</div>
        <p class="card-context">${context}</p>
        <div class="card-links">
          ${profileBtn}
          ${postBtn}
          ${score ? `<span class="relevance">${score}</span>` : ""}
        </div>
      </div>
    `;

    grid.appendChild(card);
  });

  wrap.classList.remove("hidden");
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escAttr(str) {
  return String(str).replace(/"/g, "&quot;");
}
