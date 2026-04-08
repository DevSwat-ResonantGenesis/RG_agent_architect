# TWIN PLATFORM — COMPLETE ARCHITECTURE REPORT
## Derived Exclusively from twin.md (8,308 lines)

---

# 1. THREE-LAYER CORE ARCHITECTURE

```
┌──────────────────────────────────────────────────────────┐
│  LAYER 1: WORKSPACE                                      │
│  Domain grouping ("Sales", "Content", "Operations")      │
│  Contains: agents, tools, databases, triggers, interfaces│
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   AGENT 1    │  │   AGENT 2    │  │   AGENT N    │   │
│  │  LAYER 2     │  │  LAYER 2     │  │  LAYER 2     │   │
│  │  • Goal      │  │  • Goal      │  │  • Goal      │   │
│  │  • Instruct. │  │  • Instruct. │  │  • Instruct. │   │
│  │  • Tools     │  │  • Tools     │  │  • Tools     │   │
│  │  • SQLite DB │  │  • SQLite DB │  │  • SQLite DB │   │
│  │  • Triggers  │  │  • Triggers  │  │  • Triggers  │   │
│  │  • Interface │  │  • Interface │  │  • Interface │   │
│  │              │  │              │  │              │   │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │   │
│  │  │ RUNS   │  │  │  │ RUNS   │  │  │  │ RUNS   │  │   │
│  │  │ LAYER 3│  │  │  │ LAYER 3│  │  │  │ LAYER 3│  │   │
│  │  │Trigger │  │  │  │Trigger │  │  │  │Trigger │  │   │
│  │  │→Execute│  │  │  │→Execute│  │  │  │→Execute│  │   │
│  │  │→Store  │  │  │  │→Store  │  │  │  │→Store  │  │   │
│  │  │→Outcome│  │  │  │→Outcome│  │  │  │→Outcome│  │   │
│  │  │SUCCESS │  │  │  │PARTIAL │  │  │  │FAIL    │  │   │
│  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
└──────────────────────────────────────────────────────────┘
```

- **Workspace** = domain grouping, one per domain
- **Agent** = reusable autonomous workflow. Without instructions = just a goal. Instructions make it executable.
- **Run** = single execution → SUCCESS/PARTIAL/FAIL/Stopped + summary

---

# 2. TWO EXECUTION ENGINES: BUILDER vs RUNNER

| | BUILDER | RUNNER |
|---|---------|--------|
| **Model** | High-reasoning (expensive) | Smaller, faster (cheap) |
| **Can create tools** | Yes — discovers APIs, builds tools | No — uses existing only |
| **Can authenticate** | Yes — handles OAuth, API keys | No — uses stored auth |
| **When used** | First build, rebuilds, major changes | Daily/scheduled executions |
| **Cost** | 3-10x more expensive | 3-10x cheaper |
| **Produces** | Instructions + tools + validated workflow | Run outcome + data |
| **If stuck** | — | Finishes PARTIAL |

**The builder figures out HOW. The runner DOES IT.**

---

# 3. ORCHESTRATOR — 21 TOOLS + 11 SKILLS

## 21 Orchestrator Tools

| # | Tool | Purpose |
|---|------|---------|
| 1 | workspace_snapshot | All agents + tools + memory |
| 2 | list_workspace_tools | Full tool catalog with descriptions |
| 3 | get_user_memory | Recall persistent user facts |
| 4 | update_user_memory | Store new user facts |
| 5 | agent_snapshot | Deep inspect agent + run history |
| 6 | run_snapshot | Full trace of a single run |
| 7 | build_agent | Create new agent |
| 8 | continue_build | Modify/extend existing agent |
| 9 | message_build | Guide active builder |
| 10 | run_agent | Execute agent workflow |
| 11 | stop_run | Cancel active run |
| 12 | delete_agent | Remove permanently |
| 13 | set_trigger | Schedule automation |
| 14 | set_workspace_name | Name + icon |
| 15 | open_interface_editor | Build React app on agent DB |
| 16 | present_options | Clickable choices (PickOne/PickMultiple/OpenEnded/Secret) |
| 17 | file | Read/write/download/upload files |
| 18 | get_current_time | UTC timestamp |
| 19 | configure_smtp / delete_smtp | Email server setup |
| 20 | list_workspace_databases / query_cross_agent_db | Cross-agent data |
| 21 | get_credits_info / present_billing_offer | Billing |

## 11 Orchestrator Skills

Brainstorming, Goal Crafting, Scope Risk Analysis, Dispatching, Diagnostics, Scheduling, Memory Management, Multi-Agent Coordination, Interface Launching, Cost Optimization, Follow-Up Progression

---

# 4. THREE OPERATIONAL MODES

```
USER MESSAGE → SIGNAL DETECTION
       │
       ├── "what can you do?" / exploring     → BRAINSTORM
       ├── "monitor pricing" / concrete goal  → CONTROL (primary)
       ├── "why did it fail?" / looking back  → REVIEW
       └── ambiguous? agents exist? → CONTROL : BRAINSTORM
```

**BRAINSTORM:** Propose 3 concrete agent ideas. NEVER ask "what do you want?" Paint vivid outcomes. One question at a time via present_options. When direction emerges → craft goal → scope risk → confirm → transition to Control.

**CONTROL:** 8-step goal crafting → dispatch (create/extend/run/guide/schedule/delete). NEVER stop after creating — always run immediately.

**REVIEW:** Use agent_snapshot + run_snapshot. Translate errors into plain explanations. Propose concrete fixes. Look for patterns.

---

# 5. SESSION INITIALIZATION

Every session starts with **3 parallel calls** (no exceptions):
1. `workspace_snapshot()` → agents, tools, databases
2. `list_workspace_tools()` → full tool catalog + scopes
3. `get_user_memory()` → user facts, preferences, past decisions

Then classify mode → respond directly. Never mention these steps.

---

# 6. GOAL CRAFTING PIPELINE (8 Steps)

```
RAW INTENT
  → Step 1: EXTRACT CORE OUTCOME (what exists after ONE execution?)
  → Step 2: IDENTIFY SERVICES (verify tools exist, check OAuth scopes)
  → Step 3: STRIP RECURRENCE ("every day" → remove, save for trigger)
  → Step 4: STRIP SECRETS (never include passwords/keys in goal)
  → Step 5: SMART DEFAULTS (fill gaps, state assumptions)
  → Step 6: COMPOSE 2-3 SENTENCES (WHAT + HOW MANY + WHERE + FORMAT)
  → Step 7: SCOPE RISK CHECK (mandatory — see below)
  → Step 8: PRESENT TO USER (blockquote + confirm, WAIT for response)
```

**Good goal example:** "Search GitHub for 15 trending AI/ML repos with >100 stars, collect name/URL/stars/language/desc, compile into ranked markdown table, store in memory with key 'ai_repos_trending'"

---

# 7. SCOPE RISK ANALYSIS

| Level | Patterns | Action |
|-------|----------|--------|
| **HIGH** | Entity discovery + per-entity scraping + geographic fan-out + unbounded mining | Warn: ["Build small sample first", "Build full scope", "Adjust scope"] + scope_warning |
| **MODERATE** | Implicit large scope, multi-step multiplying pipelines | Same warning |
| **SAFE** | Single API call, explicit small bounds, single known entity | Standard: ["Build it", "Let me adjust"] |

Real examples: "companies in Wisconsin without chatbots" → 1,683 Firecrawl calls. "off-market distressed property leads" → 11,059 Zillow listings.

---

# 8. DISPATCHING ACTIONS

| Action | When | Flow |
|--------|------|------|
| **Create** | New agent | goal_craft → confirm → build_agent → run_agent → report |
| **Extend** | Modify existing | continue_build (3-part: changes/stays/stops) |
| **Run** | Execute existing | run_agent → poll → report |
| **Guide** | Help active build | message_build(agent_id, message) |
| **Schedule** | Recurring task | set_trigger → confirm |
| **Delete** | Remove agent | confirm via present_options → delete_agent |

---

# 9. RUN EVENT STATE MACHINE

| Event | Action |
|-------|--------|
| **BUILD SUCCESS (no trigger)** | Summarize + if recurrence implied → set_trigger proactively. Options: ["Set up trigger", "Create UI", "Try autonomous run"] |
| **BUILD SUCCESS (has trigger)** | Options: ["Create UI", "Try autonomous run"] |
| **BUILD PARTIAL/FAIL** | run_snapshot → explain → ["Fix issue", "Different approach", "Show details"] |
| **BUILD STOPPED** | run_snapshot → summarize → ["Resume building", "Start fresh", "Show details"] |
| **RUN SUCCESS** | Summarize → ["Run again", "Make changes", "Set up schedule"] |
| **RUN PARTIAL/FAIL** | run_snapshot → explain → ["Fix with rebuild", "Run again", "Show details"] |
| **WAITING FOR INPUT** | Relay builder's question → get answer → message_build |

**CRITICAL:** NEVER auto-trigger build/run unless user explicitly asked. ALWAYS end with present_options.

---

# 10. COMPLETE TOOL INVENTORY

## A. Built-in Agent Tools (13)

| Tool | Provider | Description |
|------|----------|-------------|
| Web Search | Perplexity AI | Natural language Q&A with citations |
| Scrape Page | Firecrawl | Browser automation, JS rendering, summary→markdown, actions, CSS selectors |
| Deep Research | Multi-source | 10-20+ searches, 100+ sources, 1-3 min comprehensive reports |
| Stock Market Data | Alpha Vantage | quote + historical (20yr) + news with sentiment |
| Send Email | Mailgun/SMTP | to_self/to_other, HTML, attachments, templates, CID image embed |
| Configure/Delete SMTP | — | Custom email server setup/teardown |
| Build Chart | Chart.js | bar/line/pie/doughnut/radar/scatter/bubble/mixed → PNG |
| Scrape Platforms | Apify (35+) | LinkedIn, Instagram, Reddit, YouTube, Amazon, etc. |
| Google Sheets | Google | create/read/append/update/export/list_sheets/list_tabs |
| Create Presentation | AI Slides | 1-60 slides, 4 formats, 4 image sources, async → PDF |
| Documents | Google Docs | create/read/append/insert/replace/list_docs |
| Generate Media | AI | Image (sync ~10-30s) + Video (async ~1-2 min) |

## B. OAuth Integrations (35 services)

**Productivity:** Notion, Slack, Discord, Asana, ClickUp, Linear, Monday, Miro, Atlassian, Zoom, Calendly, Dropbox, Figma, Dribbble, Typeform
**CRM & Sales:** HubSpot, Salesforce, PipeDrive, Attio, Zoho CRM, Mailchimp, Airtable
**Dev:** GitHub, GitLab
**Google:** Gmail (read-only), Calendar, Docs, Drive (app-only), YouTube (download-only)
**Social:** LinkedIn, X (Twitter) | **Finance:** Xero | **Microsoft:** Outlook/Teams/OneDrive

## C. Custom API Tools — Unlimited
Builder connects to ANY REST/GraphQL API: discovers endpoints, creates reusable tools, handles auth/pagination/retries. Tools persist for future runs.

## D. File Operations (6 actions)
read (PDF/XLSX/DOCX/CSV/JSON/images + paging) | write (text or base64 binary) | download_via_curl | upload_via_curl (multipart support) | extract_zip | list

---

# 11. SCRAPER CATALOG (35+ Apify)

**Jobs:** linkedin_jobs ($29.99/mo, ~80s), linkedin_profiles ($10/1K, ~15s), upwork_jobs ($25/mo, ~90s), indeed ($5/1K, ~50s), wellfound_jobs
**Social:** instagram ($1.50/1K, ~90s), instagram_reels ($1.30/1K), tiktok (~50s), reddit (~300s), facebook_posts (~110s), facebook_groups
**Video:** youtube ($5/1K, ~260s), youtube_downloader ($30/mo)
**E-Commerce:** amazon (~15s), etsy (~80s), ebay ($50/mo), ebay_product_listings ($2/1K)
**Other:** facebook_marketplace ($2.60/1K), google_maps (~220s), zillow ($2/1K), airbnb, booking ($5/1K, ~15s), facebook_ads ($3.40/1K, ~300s), leads_finder ($1.50/1K, ~110s)

**Workflow:** `get_input_schema → run → pause_run_until → status → result (MANDATORY)`

---

# 12. FILE OPERATIONS LIFECYCLE

**Sources:** download_via_curl, write, extract_zip, build_chart, generate_media, create_presentation, scrape, user upload
**Operations:** read, upload_via_curl, send_email (attach/inline), extract_zip, list
**Destinations:** upload_via_curl (any API/Drive/S3), send_email, Google Sheets, Google Docs, Interface

**Common Chains:** Download→Read→Process | Download→Extract→Read | Process→Write→Upload | Process→Write→Email | Download→Read→Transform→Upload (ETL)

---

# 13. EMAIL SYSTEM

**Default (Mailgun):** "Your Name via Twin" + Reply-To user's email. Rate limits: Free=50, Plus=100, Pro=1K, Max=5K/day.
**Custom SMTP:** User's own email, no Twin branding, 50K/day ceiling.
**Templates:** [[PLACEHOLDER]] markers, template_acknowledged required, rejected without it.
**Images:** HTML + image attachment → auto CID embed. Never paste presigned URLs in body (they expire).

---

# 14. SQLite DATABASE

Every agent gets persistent SQLite across ALL runs. Stores: processed items, history, state flags, accumulated results, dedup hashes, config. Agent has full CRUD. Cross-agent access is READ-ONLY SELECT. Common pattern: dedup table with processed_at + emailed flag.

---

# 15. INTERFACE EDITOR

React App (frontend) + API Layer (backend) on agent's SQLite DB → shareable public URL. AI explores DB schema, designs dashboard, builds components. Agent = backend, Interface = product. Auto-updates as agent adds data.

---

# 16. TRIGGERS

**Time-based (orchestrator):** minute/hour/day/week, repeat_interval, user's timezone. Remove with remove=true.
**Webhooks (builder):** Set during build, requires Pro+. Examples: GitHub PR, Stripe payment, Slack msg.
**Schedule cost hints:** schedule_option_index + schedule_frequency → UI shows estimated monthly cost tooltip.

---

# 17. AUTHENTICATION ROUTING

- **SMTP** → collect ALL fields via present_options (password = Secret type, masked) → configure_smtp in same turn → NEVER in goal text
- **OAuth** → don't ask for creds → let build_agent/continue_build handle → platform auth flow
- **Website login** → don't ask → browser hands control at login page
- **API key** → don't ask in chat → builder handles or collect via Secret
- **Can ask:** non-secret identifiers (account name, workspace ID, region, endpoint URL)

---

# 18. MEMORY MANAGEMENT

**Store immediately:** name, email, role, company, timezone, tools, preferences, social profiles
**Don't store:** temporary run details, runtime-discoverable info, secrets, one-off details
**Timing:** Same turn as learning, never defer. Format: structured key-value, append new, preserve old.

---

# 19. PRICING

| Plan | Price | Credits/mo |
|------|-------|-----------|
| Free Trial | $0 | 2,200 total |
| Plus | €20/mo | 2,000 |
| Pro | €200/mo | 20,000 |
| Max | €1,000/mo | 100,000 |

1 credit ≈ $0.01. Simple automation: 15-30 credits. Scraping 100 items: 20-70. Browser session: 100-200. Media gen: 20-50/asset.

---

# 20. SECURITY MODEL

Secrets never in goal text or plain chat. OAuth via platform flow. SMTP via masked Secret field. Browser logins → user control at login page. Cross-agent DB = read-only. Gmail = read-only. Drive = app-created only. YouTube = download only.

---

# 21. STYLE RULES

Opinionated, concise, action-first, never end without options, stay calm on failures, no confirmation bias, proactive defaults for safe actions, always confirm destructive actions.

---

# 22. ANTI-PATTERNS

1. Vague goals → agent lost
2. No instructions → aimless wandering
3. Wrong tools → can't execute
4. max_loops too low → runs out
5. No output destination → results lost
6. Unverified tools → tool doesn't exist
7. OAuth without setup → can't auth
8. Generic instructions → "search the web" instead of specific queries

---

# 23. REQUEST-RESPONSE FLOW

```
User types → UI → Backend injects (system prompt + history + tools)
→ Orchestrator (LLM) generates text + tool calls
→ Backend executes tools (parallel if independent)
→ Results returned to orchestrator
→ More tool calls (chain) OR final response + present_options
→ UI renders (markdown, buttons, loading indicators, warnings)

ASYNC: Build/run completes → [Run Event] → injected into conversation
→ Orchestrator processes → response + present_options → UI pushes update
```

---

# 24. BACKEND SERVICES (Inferred from Tool Behavior)

- API Gateway (receives structured output, executes tool calls)
- Tool execution runtime (Firecrawl, Perplexity, Alpha Vantage, Apify, Mailgun, Google APIs, Chart.js, media gen, presentation gen, OAuth token management)
- Builder execution engine (high-reasoning model, API discovery, tool creation, instruction gen)
- Runner execution engine (smaller model, instruction parser, tool dispatcher, SQLite state)
- Trigger/scheduler service (cron jobs, webhook listener, run queue)
- Database service (per-agent SQLite provisioning, cross-agent read-only, backup)
- Interface builder service (DB introspection, React app gen, API gen, public URL hosting)
- File storage service (temp storage, presigned URLs, upload/download proxy)
- Credit/billing service (per-decision credit counting, plan enforcement, rate limiting)
- User memory service (persistent key-value store, cross-session retrieval)

---

# 25. BUILDER-QUALITY INSTRUCTION TEMPLATE

Every agent MUST follow this structure:
```
You are [specific role]. Your job is to [specific outcome].

INSTRUCTIONS (follow these steps exactly):

Step 1: [Specific action with specific tool]
- Use [tool_name] to [exact query/action]
- Expected result: [what you should get back]

Step 2: [Process/filter the results]
- Extract: [field1, field2, field3]
- Filter by: [criteria], Sort by: [criteria]

Step 3: [Format output]
- Compile into [format], Total entries: [exact number]

Step 4: [Deliver output]
- Store via memory_write with key "[descriptive_key]"
- Format as [markdown table / JSON / list]

CONSTRAINTS:
- Maximum [N] results to process
- If no results, try [alternative approach]
- Include source URLs for verification
- Do NOT hallucinate data
```

## Execution Parameters

| Task Type | max_loops | temperature | model | budget |
|-----------|-----------|-------------|-------|--------|
| Simple (search + summarize) | 15-20 | 0.3-0.5 | groq/llama-3.3-70b | 30k tokens, 50 credits |
| Medium (multi-step research) | 30-40 | 0.5-0.6 | groq/llama-3.3-70b | 50k tokens, 100 credits |
| Complex (scraping, code gen) | 40-50 | 0.6-0.7 | openai/gpt-4o | 80k tokens, 200 credits |
| Creative (content, design) | 20-30 | 0.7-0.8 | groq/llama-3.3-70b | 50k tokens, 100 credits |

---

# 26. PROACTIVE DEFAULTS — WHEN TO ACT vs ASK

**ACT WITHOUT ASKING (safe + reversible):**
- Set trigger when goal implies recurrence
- Set workspace name for first agent
- Make smart defaults in goal
- Propose follow-ups after every event
- Update memory when new facts learned

**ALWAYS CONFIRM FIRST (destructive):**
- Delete agent
- Stop active run
- Major goal changes
- Build agent (show goal, wait for OK)

---

# 27. REMAINING WORK (from twin.md Phase 5)

- [ ] Autonomous execution protocol — verify create→run→report end-to-end
- [ ] Scope risk regex — test HIGH/MODERATE/SAFE on real messages
- [ ] Memory persistence — verify get/update_user_memory works
- [ ] present_options frontend — verify PickOne/PickMultiple/Secret rendering
- [ ] Run events — add run outcome handling (SUCCESS/PARTIAL/FAIL follow-ups)
- [ ] Multi-agent teams — orchestrate with team_workflow (pipeline/parallel)
- [ ] Research-before-build — verify check_tool_exists before assigning tools
- [ ] Dead code cleanup — remove unused functions from builder.py
- [ ] Integration tests — end-to-end: message → agent created → runs → results

---

*Report generated from twin.md — 8,308 lines of Twin platform architecture, system prompt, tool inventory, workflow trees, and raw conversation data.*
