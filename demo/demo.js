/*
 * PresenAIT Outreach - demo mode for GitHub Pages.
 *
 * GitHub Pages can't run the Python engine, so this script answers the
 * dashboard's /api/... requests itself with SAMPLE data and simulates the
 * Find and Write buttons. Nothing is searched, written or sent, and
 * everything resets when the page is reloaded.
 */
(function () {
  window.PRESENAIT_DEMO = true;
  const RELEASE_URL = "https://github.com/AddyBahl/presenait-outreach/releases/latest";
  const MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"];
  const EST_DRAFT = { "claude-opus-5-5": [0.12, 0.35], "claude-sonnet-5-5": [0.06, 0.18], "claude-haiku-5-5": [0.02, 0.05] };
  const EST_FIND = { "claude-opus-5-5": [0.15, 0.6], "claude-sonnet-5-5": [0.08, 0.35], "claude-haiku-5-5": [0.05, 0.12] };
  const RATES = { Lite: 5, Core: 8, Pro: 12 };

  // ---------------------------------------------------------------- sample data (fictional)
  const biz = (company, slug, suburb, industry, phone, size, why, extra = {}) => ({
    type: "client", company, website: `https://${slug}.example.com`, suburb_state: suburb, industry,
    contact_name: "", contact_role: "", email: "", phone, contact_page: `https://${slug}.example.com/contact`,
    size_hint: size, why_fit: why, source: "sample data", ...extra,
  });
  const PROSPECTS = [
    biz("Sample Spotless Cleaning", "sample-spotless", "Werribee VIC", "Commercial cleaning", "03 9000 0001",
      "About 40 cleaners across 12 commercial sites; hiring casuals", "Cleaners start at different sites at night, so paper timesheets are hard to check.",
      { contact_name: "Sam Taylor", contact_role: "Operations Manager", email: "sam@sample-spotless.example.com" }),
    biz("Sample Bayside Security", "sample-bayside", "Point Cook VIC", "Security services", "03 9000 0002",
      "24/7 guards on 6 client sites", "Guards on rotating shifts at client sites need proof they were on site.",
      { contact_name: "Priya Shah", contact_role: "Director" }),
    biz("Sample Corner Cafe Group", "sample-cornercafe", "Hoppers Crossing VIC", "Cafe / hospitality", "03 9000 0003",
      "3 cafes, about 35 casual staff", "Casual staff across three cafes; manual timesheets before each pay run.",
      { contact_name: "Tom Nguyen", contact_role: "Owner", email: "tom@sample-cornercafe.example.com" }),
    biz("Sample Westgate Logistics", "sample-westgate", "Laverton VIC", "Warehouse / logistics", "03 9000 0004",
      "Warehouse with 2 shifts, about 60 staff", "Two shifts a day and overtime make accurate hours important."),
    biz("Sample Little Steps Childcare", "sample-littlesteps", "Tarneit VIC", "Childcare centre", "03 9000 0005",
      "2 centres, about 30 educators", "Educator ratios mean knowing exactly who is on the floor."),
    biz("Sample FitHub Gym", "sample-fithub", "Wyndham Vale VIC", "Gym / fitness", "03 9000 0006",
      "Open 5am-10pm, about 18 staff", "Early and late shifts with a small team; one site, so Lite fits."),
    { ...biz("Sample Wyndham Plaza", "sample-wyndhamplaza", "Werribee VIC", "Shopping centre", "03 9000 0007",
      "About 90 specialty stores; independent owner", "Many small retail tenants with casual staff - a good tenant-perk partner."),
      type: "partner", contact_role: "Centre Manager" },
  ];
  const FIND_POOL = {
    client: [
      ["Sample Greenleaf Landscaping", "sample-greenleaf", "Werribee VIC", "03 9000 0011", "4 crews, about 25 staff", "Crews start at different job sites each day."],
      ["Sample Harbour Dental", "sample-harbourdental", "Point Cook VIC", "03 9000 0012", "2 clinics, about 20 staff", "Part-time staff across two clinics."],
      ["Sample Metro Movers", "sample-metromovers", "Truganina VIC", "03 9000 0013", "About 30 casual movers", "Casual crews paid by the hour - hours must be exact."],
      ["Sample Sunrise Bakery", "sample-sunrise", "Altona VIC", "03 9000 0014", "Bakery plus 2 shops, about 22 staff", "Very early starts and split shifts."],
      ["Sample Apex Electrical", "sample-apex", "Hoppers Crossing VIC", "03 9000 0015", "About 16 electricians and apprentices", "Staff clock on at customer sites; geo-fencing helps."],
      ["Sample Bright Smiles Childcare", "sample-brightsmiles", "Werribee VIC", "03 9000 0016", "1 centre, about 14 educators", "Small team on one site - Lite plan."],
      ["Sample Westside Auto Care", "sample-westside-auto", "Laverton VIC", "03 9000 0017", "2 workshops, about 18 staff", "Mechanics across two workshops."],
      ["Sample Pure Clean Services", "sample-pureclean", "Tarneit VIC", "03 9000 0018", "About 50 cleaners, hiring", "Large casual workforce on many sites."],
    ],
    partner: [
      ["Sample Point Cook Village", "sample-pcvillage", "Point Cook VIC", "03 9000 0021", "About 60 specialty stores; independent owner", "Smaller independent centre - quicker to agree a tenant perk."],
      ["Sample Tarneit Central", "sample-tarneitcentral", "Tarneit VIC", "03 9000 0022", "About 70 stores", "Growing area with many new small retailers."],
      ["Sample Hoppers Crossing Market", "sample-hcmarket", "Hoppers Crossing VIC", "03 9000 0023", "About 40 stalls and shops", "Lots of small owner-run businesses."],
    ],
  };

  const keyOf = (r) => `${(r.company || "").trim().toLowerCase()}|${(r.website || "").trim().toLowerCase()}`;
  const domainOf = (u) => String(u || "").toLowerCase().replace(/^[a-z]+:\/\//, "").replace(/^www\./, "").split("/")[0];

  function price(type, plan, staff) {
    if (type === "partner") return "partner (referral)";
    if (!staff) return "from $30/month";
    if (plan === "Lite" && staff > 15) plan = "Core";
    return `$${Math.max(30, RATES[plan] * staff)}/month (${plan}, ${staff} staff, ex GST)`;
  }
  function staffGuess(p) { const m = String(p.size_hint).match(/(\d+)\s*(?:staff|cleaners|educators|guards|movers|electricians|casual)/i); return m ? Number(m[1]) : 12; }

  function makeDraft(p) {
    const s = state.settings;
    const sig = `\n\n${s.sender_name || "[Your name]"}\n${s.sender_title || "[Your title]"}, PresenAIT by DataAIT Technologies Pty Ltd\n${s.sender_email || "[your@email]"} | presenait.com\nIf you'd rather not hear from me again, just reply 'unsubscribe'.`;
    const hi = p.contact_name ? `Hi ${p.contact_name.split(" ")[0]},` : "Hi there,";
    if (p.type === "partner") {
      return {
        fit_score: 4, fit_reason: p.why_fit, business_summary: `${p.company} is a shopping centre in ${p.suburb_state} with ${p.size_hint.toLowerCase()}.`,
        attendance_pain: "Specialty retailers juggle casual staff timesheets and Fair Work record-keeping on their own.",
        estimated_staff: 0, suggested_plan: "Lite", price_estimate: "partner (referral)",
        email_subject: "A tenant perk for your specialty retailers",
        email_body: `${hi}\n\nMany of the specialty retailers at ${p.company} run on casual staff and paper timesheets, which makes Fair Work record-keeping harder than it needs to be.\n\nPresenAIT is a Melbourne-built attendance app (from $5 per staff a month). We'd like to offer it to your tenants as a centre perk: tenants get their first month free, and the centre earns a referral fee.\n\nOur offer: ${s.referral_offer}.\n\nWould you be open to a 15-minute call?${sig}`,
        follow_up_email: `${hi} just following up on a tenant perk for ${p.company}'s retailers. Happy to send a one-page summary you can share with your team.${sig}`,
        linkedin_message: `Hi - I'm working with Melbourne shopping centres on a free-first-month attendance app perk for specialty retailers. Would be great to connect.`,
        call_opener: `Hi, it's ${s.sender_name || "[name]"} from PresenAIT in Melbourne. We help small retailers replace paper timesheets, and we're offering it to centres as a tenant perk. Who looks after retailer programs at ${p.company}?`,
      };
    }
    const staff = staffGuess(p);
    const plan = /one site|1 centre|Lite/i.test(p.size_hint + p.why_fit) && staff <= 15 ? "Lite" : staff > 40 ? "Pro" : "Core";
    const pr = price("client", plan, staff);
    const cost = pr.split(" ")[0].replace("/month", "");
    return {
      fit_score: staff >= 30 ? 5 : staff >= 18 ? 4 : 3,
      fit_reason: p.why_fit,
      business_summary: `${p.company} (${p.industry.toLowerCase()}) in ${p.suburb_state}: ${p.size_hint}.`,
      attendance_pain: p.why_fit,
      estimated_staff: staff, suggested_plan: plan, price_estimate: pr,
      email_subject: `Timesheets at ${p.company.replace(/^Sample /, "")}`,
      email_body: `${hi}\n\nWith ${p.size_hint.toLowerCase()}, I imagine collecting and checking hours before each pay run takes a fair bit of time.\n\nPresenAIT lets staff clock in on a shared tablet or their phone, with geo-fencing so it only works on site. Managers approve hours in one click and export them straight to Xero or MYOB. For a team your size that's about ${cost} a month, with a 14-day free trial.\n\nWorth a 15-minute look?${sig}`,
      follow_up_email: `${hi} a quick follow-up on attendance tracking for ${p.company.replace(/^Sample /, "")}. I can set up the free trial for you in a few minutes if that helps.${sig}`,
      linkedin_message: `Hi ${p.contact_name ? p.contact_name.split(" ")[0] : "there"} - I help Melbourne ${p.industry.toLowerCase()} businesses replace paper timesheets with a simple clock-in app. Would be good to connect.`,
      call_opener: `Hi, it's ${s.sender_name || "[name]"} from PresenAIT in Melbourne. Quick question - how do your staff record their hours at the moment?`,
    };
  }

  // ---------------------------------------------------------------- state
  const state = {
    settings: { sender_name: "Alex Example", sender_title: "Founder", sender_email: "alex@presenait.example.com", model: "claude-opus-5-5",
      effort: "low", max_searches: 2, budget_usd: 5, referral_offer: "20% of each referred tenant's first-year subscription, and referred tenants get their first month free" },
    prospects: PROSPECTS.map((p) => ({ ...p })),
    results: {},
    job: { running: false, kind: "", log: [], error: "", found: [], progress: [0, 0], spend: 0, finished_at: 0, stop: false },
    sessionSpend: 0,
  };
  // three ready-made drafts so the Drafts tab isn't empty
  [[0, "READY"], [2, "NEEDS REVIEW"], [6, "NEEDS REVIEW"]].forEach(([i, status]) => {
    const p = state.prospects[i];
    state.results[keyOf(p)] = { key: keyOf(p), ...p, ...makeDraft(p), status,
      research_notes: `- ${p.size_hint}\n- ${p.why_fit}\n- (Sample research notes - in the real app these come from a live web search, with source links.)` };
  });
  state.results[keyOf(state.prospects[3])] = { key: keyOf(state.prospects[3]), ...state.prospects[3], status: "ERROR",
    error: "Sample error: the website couldn't be reached. It would be retried on the next run." };

  const pending = () => state.prospects.filter((p) => !["NEEDS REVIEW", "READY", "SENT", "SKIPPED"].includes((state.results[keyOf(p)] || {}).status));
  const now = () => new Date().toTimeString().slice(0, 8);
  const log = (line) => { state.job.log.push(`${now()}  ${line}`); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const addSpend = (x) => { state.job.spend += x; };

  async function simulateFind(p) {
    const kind = p.type === "partner" ? "partner" : "client";
    const what = kind === "partner" ? "shopping centres" : p.industry;
    log(`Searching the web for ${p.count} ${what} near ${p.location} ... (demo: sample results)`);
    await sleep(1200); addSpend(0.09); log("Reading websites and contact pages ...");
    await sleep(1200); addSpend(0.11);
    const names = new Set(state.prospects.map((x) => x.company.toLowerCase()));
    const doms = new Set(state.prospects.map((x) => domainOf(x.website)));
    state.job.found = FIND_POOL[kind].slice(0, Number(p.count) || 10).map(([company, slug, suburb, phone, size, why]) => {
      const r = biz(company, slug, suburb, kind === "partner" ? "Shopping centre" : p.industry || "Business", phone, size, why,
        { type: kind, source: `sample finder: ${what} near ${p.location}` });
      return { ...r, already: names.has(company.toLowerCase()) || doms.has(domainOf(r.website)) };
    });
    log(`Found ${state.job.found.length} businesses. Estimated spend $${state.job.spend.toFixed(2)} (demo - nothing was charged).`);
  }

  async function simulateRun(p) {
    const todo = pending().slice(0, Number(p.limit) || 5);
    state.job.progress = [0, todo.length];
    for (let i = 0; i < todo.length; i++) {
      if (state.job.stop) { log("Stopped: stopped by you."); break; }
      const row = todo[i], n = `[${i + 1}/${todo.length}]`;
      log(`${n} Researching ${row.company} ...`); await sleep(900); addSpend(0.08);
      log(`${n} Writing drafts for ${row.company} ...`); await sleep(900); addSpend(0.06);
      const d = makeDraft(row);
      state.results[keyOf(row)] = { key: keyOf(row), ...row, ...d, status: "NEEDS REVIEW",
        research_notes: `- ${row.size_hint || "Size unknown"}\n- ${row.why_fit || ""}\n- (Sample research notes - the real app searches the web.)` };
      state.job.progress = [i + 1, todo.length];
      log(`${n} ${row.company}: NEEDS REVIEW (fit ${d.fit_score}) $0.140, total $${state.job.spend.toFixed(2)}`);
    }
    log(`Done. ${state.job.progress[0]} processed, estimated spend $${state.job.spend.toFixed(2)} (demo - nothing was charged).`);
  }

  function startJob(kind, fn, params) {
    if (state.job.running) return [409, { error: "Another job is already running." }];
    Object.assign(state.job, { running: true, kind, log: [], error: "", stop: false, progress: [0, 0], spend: 0 });
    if (kind === "find") state.job.found = [];
    fn(params).finally(() => { state.sessionSpend += state.job.spend; state.job.running = false; state.job.finished_at = Date.now(); });
    return [200, { ok: true }];
  }

  // ---------------------------------------------------------------- fake API
  function handle(path, method, body) {
    if (path === "/api/meta") return [200, { api_key: true, models: MODELS, settings: state.settings, est_draft: EST_DRAFT, est_find: EST_FIND,
      pending: pending().length, session_spend: state.sessionSpend }];
    if (path === "/api/prospects" && method === "GET")
      return [200, state.prospects.map((p) => ({ ...p, key: keyOf(p), draft_status: (state.results[keyOf(p)] || {}).status || "" }))];
    if (path === "/api/prospects/add") {
      let added = 0, skipped = 0;
      for (const r of body.rows || []) {
        const dup = state.prospects.some((x) => x.company.toLowerCase() === (r.company || "").toLowerCase() || (r.website && domainOf(x.website) === domainOf(r.website)));
        if (!r.company || dup) { skipped++; continue; }
        const { already, ...clean } = r; state.prospects.push({ type: "client", ...clean }); added++;
      }
      return [200, { added, skipped }];
    }
    if (path === "/api/prospects/update") {
      const p = state.prospects.find((x) => keyOf(x) === body.key); if (!p) return [404, { error: "not found" }];
      Object.entries(body.fields || {}).forEach(([k, v]) => { if (k !== "company" && k !== "website") p[k] = String(v); });
      return [200, p];
    }
    if (path === "/api/prospects/delete") {
      const before = state.prospects.length; state.prospects = state.prospects.filter((p) => !(body.keys || []).includes(keyOf(p)));
      return [200, { deleted: before - state.prospects.length }];
    }
    if (path === "/api/drafts" && method === "GET") {
      const live = Object.fromEntries(state.prospects.map((p) => [keyOf(p), p]));
      const out = Object.values(state.results).map((r) => {
        const m = { ...r }, l = live[r.key] || {};
        ["email", "contact_name", "contact_role", "phone", "contact_page", "website", "suburb_state"].forEach((f) => { if (l[f]) m[f] = l[f]; });
        return m;
      });
      out.sort((a, b) => (a.status === "ERROR") - (b.status === "ERROR") || (b.fit_score || 0) - (a.fit_score || 0));
      return [200, out];
    }
    if (path === "/api/drafts/update") {
      const r = state.results[body.key]; if (!r) return [404, { error: "not found" }];
      Object.assign(r, body.fields || {}); return [200, r];
    }
    if (path === "/api/drafts/redo") {
      const r = state.results[body.key]; if (!r) return [404, { error: "not found" }];
      Object.assign(r, { status: "ERROR", error: "Queued to be drafted again" }); return [200, { ok: true }];
    }
    if (path === "/api/settings") { if (method === "POST") Object.assign(state.settings, body); return [200, state.settings]; }
    if (path === "/api/apikey") return [400, { error: "The demo doesn't use an API key. Download the app to use your own." }];
    if (path === "/api/find") {
      if (!body.location || (body.type !== "partner" && !body.industry)) return [400, { error: "Enter a business type and a location." }];
      return startJob("find", simulateFind, body);
    }
    if (path === "/api/run") return startJob("draft", simulateRun, body);
    if (path === "/api/stop") { state.job.stop = true; log("Stopping after the current business ..."); return [200, { ok: true }]; }
    if (path === "/api/job") {
      const j = state.job;
      return [200, { running: j.running, kind: j.kind, log: j.log.slice(-80), error: j.error, found: j.found, progress: j.progress,
        spend: j.spend, session_spend: state.sessionSpend + (j.running ? j.spend : 0), finished_at: j.finished_at }];
    }
    return [404, { error: "Not available in the demo" }];
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const i = url.pathname.indexOf("/api/");
    if (i === -1) return realFetch(input, init);
    const body = init.body ? JSON.parse(init.body) : {};
    const [status, data] = handle(url.pathname.slice(i), (init.method || "GET").toUpperCase(), body);
    await sleep(120);
    return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  };

  // ---------------------------------------------------------------- banner
  document.addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div");
    b.style.cssText = "background:#F6C945;color:#15171A;font-family:'Avenir Next',Avenir,-apple-system,'Segoe UI',sans-serif;font-size:14px;padding:10px 16px;text-align:center;line-height:1.4";
    b.innerHTML = '<b>Demo with sample data.</b> The businesses and drafts are made up, nothing is searched or sent, and changes reset when you reload. ' +
      `<a href="${RELEASE_URL}" style="color:#15171A;font-weight:700">Download the real app</a>`;
    document.body.prepend(b);
  });
})();
