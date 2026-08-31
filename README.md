# AIFOD Daily AI News Aggregator (Korea & Japan)

A Python-based serverless service that fetches AI-related news from South Korea and Japan, filters them for relevance to AIFOD's mission, aggressively deduplicates similar coverages, translates and summarizes the top 5 most impactful stories in English (including adding AIFOD policy insights and discussion Q&As), and emails a daily digest to the practitioner every day at midnight (Asia/Tokyo time).

Deployed on Google Cloud Run and scheduled via Google Cloud Scheduler.

---

## Architecture & System Flowcharts

### 1. High-Level Infrastructure Overview

```mermaid
flowchart TD
    %% -------------------------------------------------------------
    %% Trigger & Orchestration Layer
    %% -------------------------------------------------------------
    subgraph TriggerLayer ["1. Trigger & Scheduling Layer"]
        CRON["⏰ GCP Cloud Scheduler<br/><code>ai-news-aggregator-daily-trigger</code><br/>(0 0 * * * Asia/Tokyo)"]
        CLI["💻 Local CLI / Manual Trigger<br/><code>python -m src.main --hours 24</code>"]
        SA["🔑 IAM Service Account<br/><code>ai-news-scheduler-sa</code><br/>(roles/run.invoker + OIDC)"]
    end

    %% -------------------------------------------------------------
    %% Compute & Hosting Infrastructure
    %% -------------------------------------------------------------
    subgraph ComputeLayer ["2. Compute & Runtime Infrastructure (GCP Cloud Run)"]
        CR["🚀 Cloud Run Service<br/><code>ai-news-aggregator-krjp</code><br/>(Region: us-central1)"]
        GUNICORN["🦄 Gunicorn WSGI Server<br/>(1 Worker, 8 Threads, Port: 8080)"]
        FLASK["🐍 Flask App<br/><code>src/app.py</code><br/>(POST /?hours=24)"]
        MAIN["⚙️ Orchestration Core<br/><code>src/main.py</code> (main())"]
    end

    %% -------------------------------------------------------------
    %% Ingestion & Anti-Blocking Resilience Layer
    %% -------------------------------------------------------------
    subgraph ScrapingLayer ["3. Ingestion & Multi-Tier Resilience Layer (src/rss_parser.py)"]
        QUERIES["🔍 Search Query Matrix<br/>• 18 KR Queries (AI, ODA, 격차, 정책)<br/>• 18 JP Queries (AI, ODA, 格差, 政策)"]
        POOL["⚡ ThreadPoolExecutor<br/>(max_workers=15 concurrent tasks)"]
        
        subgraph FallbackChain ["Egress IP Anti-Blocking Chain"]
            DIRECT["1️⃣ Direct Google News RSS<br/>Rotating User-Agents (Chrome, Safari, Firefox)"]
            PROXY1["2️⃣ Primary CORS Proxy<br/><code>corsproxy.io/?url=...</code>"]
            PROXY2["3️⃣ Secondary CORS Proxy<br/><code>api.allorigins.win/raw?url=...</code>"]
        end
        
        GN_KR["🇰🇷 Google News RSS (KR)<br/><code>hl=ko&gl=KR&ceid=KR:ko</code>"]
        GN_JP["🇯🇵 Google News RSS (JP)<br/><code>hl=ja&gl=JP&ceid=JP:ja</code>"]
        
        DEDUP["🧹 In-Memory Deduplication & Time Filter<br/>• URL Hash Set (seen_urls)<br/>• Publication Window (<= 24h)<br/>• Top 100 Date-Sorted Buffer"]
    end

    %% -------------------------------------------------------------
    %% AI Intelligence Layer
    %% -------------------------------------------------------------
    subgraph AILayer ["4. AI Reasoning & Enrichment Layer (src/llm_filter.py)"]
        GEMINI["✨ Google Gemini API<br/>Model: <code>gemini-2.5-flash-lite</code><br/>(Auto-Retry & Rate-Limit Backoff)"]
        PROMPT["🧠 Multi-Stage Prompt Pipeline<br/>1. AIFOD Mission Alignment<br/>2. Zero-Tolerance Deduplication<br/>3. Thematic Diversity Filtering<br/>4. Natural English Translation<br/>5. Top 5 Selection & Ranking"]
        ENRICH["📑 Structured JSON Extraction<br/>• English Title & 2-3 Sentence Summary<br/>• Relevance Explanation<br/>• AIFOD Strategic Insight<br/>• Practitioner Discussion Q&A"]
    end

    %% -------------------------------------------------------------
    %% Email Generation & Delivery Layer
    %% -------------------------------------------------------------
    subgraph DeliveryLayer ["5. Email Formatting & Delivery (src/email_sender.py)"]
        HTML_BUILDER["🎨 Premium Responsive HTML Builder<br/>• Plus Jakarta Sans Typography<br/>• KR/JP Country Badges<br/>• Gradient Header & KPI Counters"]
        GMAIL_AUTH["🔐 Gmail OAuth 2.0 Auth<br/><code>credentials.json</code> + <code>token.json</code><br/>(Auto-refresh Token Flow)"]
        GMAIL_API["📬 Google Gmail API<br/>(users.messages.send)"]
        INBOX["📩 Recipient Mailbox<br/><code>henry.hyunwookim@gmail.com</code>"]
    end

    %% -------------------------------------------------------------
    %% CI/CD & Deployment Layer
    %% -------------------------------------------------------------
    subgraph DevOpsLayer ["6. DevOps & Build Infrastructure"]
        DOCKER["🐳 Dockerfile (python:3.11-slim)"]
        CB["🏗️ Google Cloud Build"]
        AR["📦 Artifact Registry"]
        PS["📜 PowerShell Deploy Script<br/><code>deployment/deploy_cloud.ps1</code>"]
    end

    %% Flow Connections
    CRON -->|OIDC Auth POST| SA --> CR
    CLI --> MAIN
    
    CR --> GUNICORN --> FLASK --> MAIN
    
    MAIN --> POOL
    QUERIES --> POOL
    
    POOL --> DIRECT
    DIRECT -.->|On 403 / 429 / 503 Block| PROXY1
    PROXY1 -.->|On Failure| PROXY2
    
    DIRECT --> GN_KR & GN_JP
    PROXY1 --> GN_KR & GN_JP
    PROXY2 --> GN_KR & GN_JP
    
    GN_KR & GN_JP --> DEDUP
    DEDUP --> GEMINI
    
    GEMINI --> PROMPT --> ENRICH
    
    ENRICH --> MAIN
    MAIN --> HTML_BUILDER
    
    GMAIL_AUTH --> GMAIL_API
    HTML_BUILDER --> GMAIL_API
    GMAIL_API --> INBOX
    
    PS --> CB --> AR --> CR
    DOCKER --> CB
```

---

### 2. Google Gemini AI Reasoning & Value-Add Pipeline

```mermaid
flowchart TD
    %% Input Articles
    subgraph InputStage ["1. Pre-Processing & Token Management"]
        RAW_ARTICLES["📥 Raw Candidate Articles (Up to 100)"]
        MINIMIZER["✂️ Payload Optimization<br/>Extract only: index, title, source, country, query, snippet[:300]"]
        COMPACT_JSON["📦 Compact JSON Payload"]
    end

    %% Prompt Architecture
    subgraph PromptStage ["2. Expert Prompt Architecture (AIFOD News Analyst)"]
        P_MISSION["🎯 5 Core AIFOD Mission Themes:<br/>1. Bridging the AI Gap (Digital Divide)<br/>2. AI Governance & Social Equity<br/>3. Capacity Building & Education<br/>4. International Cooperation & ODA (KOICA/JICA)<br/>5. AI for Social Good (Health, Agriculture, Climate)"]
        
        P_RULES["⚖️ Cognitive Filtering & Deduplication Rules:<br/>• Zero Tolerance for Identical Press Releases<br/>• Group Substantially Overlapping Trends<br/>• Thematic Redundancy Filter (Max 1 per theme type)<br/>• Cross-Lingual KR/JP Event Deduplication<br/>• Select Top 5 Most Impactful Developments"]
        
        P_SCHEMA["📋 Enforced JSON Schema Output:<br/>• english_title<br/>• english_summary (2-3 sentences)<br/>• relevance_explanation<br/>• aifod_insight<br/>• aifod_question<br/>• aifod_suggested_answer"]
    end

    %% Execution & Resilience Engine
    subgraph ExecutionStage ["3. Gemini API Invocation & Resilience Loop"]
        CALL_GEMINI["⚡ Call Google Gemini API<br/><code>gemini-2.5-flash-lite</code><br/><code>genai.GenerativeModel.generate_content()</code>"]
        
        subgraph ErrorHandling ["Retry & Rate-Limit Engine (Max 5 Attempts)"]
            CHECK_RESP{"API Call<br/>Success?"}
            RATE_LIMIT{"Error Type?"}
            WAIT_429["⏳ 429 / Resource Exhausted:<br/>Sleep 60 seconds"]
            WAIT_EXP["⏳ Other Error:<br/>Exponential Backoff (3s * attempt)"]
            RETRY["🔁 Retry Attempt (1..5)"]
            FAIL_SAFE["⚠️ Fallback: Return Empty List"]
        end
    end

    %% JSON Extraction & Synthesis
    subgraph ExtractionStage ["4. Response Parsing & Metadata Synthesis"]
        RAW_TEXT["📝 Raw LLM Output Text"]
        STRIP_MD["🧹 Markdown Cleaner<br/>Strip ```json fences & Regex match { ... }"]
        JSON_PARSE["🔍 JSON Deserializer (json.loads)"]
        MERGE_META["🔗 Re-attach Original Metadata:<br/>original_title, link, source, country, published"]
        FINAL_TOP5["✨ Final Top 5 AIFOD Briefings"]
    end

    %% Connections
    RAW_ARTICLES --> MINIMIZER --> COMPACT_JSON
    COMPACT_JSON & P_MISSION & P_RULES & P_SCHEMA --> CALL_GEMINI
    
    CALL_GEMINI --> CHECK_RESP
    CHECK_RESP -- "❌ Failure" --> RATE_LIMIT
    RATE_LIMIT -- "HTTP 429" --> WAIT_429 --> RETRY --> CALL_GEMINI
    RATE_LIMIT -- "Other Error" --> WAIT_EXP --> RETRY --> CALL_GEMINI
    RETRY -- "Exceeded 5 Retries" --> FAIL_SAFE
    
    CHECK_RESP -- "✅ Success" --> RAW_TEXT
    RAW_TEXT --> STRIP_MD --> JSON_PARSE --> MERGE_META --> FINAL_TOP5
```

---

### 3. Data Ingestion & Anti-Blocking Fallback Pipeline

```mermaid
flowchart TD
    %% Query Generation
    subgraph QueryDispatch ["1. Query Formulation & Concurrent Dispatch"]
        K_LIST["🇰🇷 18 Korean Keywords<br/>(AI 개발도상국, 국제협력, ODA, 정보격차...)"]
        J_LIST["🇯🇵 18 Japanese Keywords<br/>(AI 途上国, 国際協力, ODA, デジタル格差...)"]
        DISPATCH["⚡ ThreadPoolExecutor (15 concurrent workers)<br/>Execute <code>get_feed_articles(query, country)</code>"]
    end

    %% Tier 1 Direct
    subgraph Tier1 ["2. Tier 1: Direct HTTP Request"]
        UA_ROTATE["🔄 Desktop User-Agent Pool<br/>(Chrome 120 / Safari 17 / Firefox 121)"]
        REQ_DIRECT["🌐 Direct GET Request to<br/><code>news.google.com/rss/search?q=...</code><br/>(Timeout: 10s)"]
        CHECK_T1{"Response<br/>Valid?"}
    end

    %% Tier 2 Primary Proxy
    subgraph Tier2 ["3. Tier 2: Primary CORS Proxy Fallback"]
        REQ_PROXY1["🛡️ Fallback: Route through corsproxy.io<br/><code>https://corsproxy.io/?<encoded_url></code><br/>(Timeout: 12s)"]
        CHECK_T2{"Proxy 1<br/>Success?"}
    end

    %% Tier 3 Secondary Proxy
    subgraph Tier3 ["4. Tier 3: Secondary CORS Proxy Fallback"]
        REQ_PROXY2["🛡️ Fallback: Route through allorigins.win<br/><code>https://api.allorigins.win/raw?url=<encoded_url></code><br/>(Timeout: 12s)"]
        CHECK_T3{"Proxy 2<br/>Success?"}
    end

    %% Feed Parser & Deduplication
    subgraph IngestionOutput ["5. Feed Parsing, Filtering & In-Memory Deduplication"]
        FEED_PARSER["📄 feedparser.parse(xml_data)"]
        TIME_FILTER["⏱️ Time Window Filter: <code>pub_date >= (now - hours_back)</code>"]
        SEEN_CHECK{"URL already in<br/><code>seen_urls</code> hash set?"}
        ADD_UNIQUE["➕ Append to unique_articles list<br/>Add URL to seen_urls"]
        DISCARD["🗑️ Discard Duplicate"]
        SORT_BUFF["📊 Sort by Publication Date Descending"]
    end

    %% Flow Connections
    K_LIST & J_LIST --> DISPATCH
    DISPATCH --> UA_ROTATE --> REQ_DIRECT --> CHECK_T1
    
    CHECK_T1 -- "✅ 200 OK & Has Entries" --> FEED_PARSER
    CHECK_T1 -- "❌ 403 / 429 / 503 / Bozo" --> REQ_PROXY1 --> CHECK_T2
    
    CHECK_T2 -- "✅ Success" --> FEED_PARSER
    CHECK_T2 -- "❌ Failed" --> REQ_PROXY2 --> CHECK_T3
    
    CHECK_T3 -- "✅ Success" --> FEED_PARSER
    CHECK_T3 -- "❌ Failed" --> DISCARD
    
    FEED_PARSER --> TIME_FILTER --> SEEN_CHECK
    SEEN_CHECK -- "No (New)" --> ADD_UNIQUE --> SORT_BUFF
    SEEN_CHECK -- "Yes (Duplicate)" --> DISCARD
```

---

### 4. End-to-End API Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Scheduler as ⏰ GCP Cloud Scheduler
    participant CloudRun as 🚀 Cloud Run (Flask / Gunicorn)
    participant Orchestrator as ⚙️ main.py
    participant RSSParser as 🔍 rss_parser.py
    participant GoogleNews as 🌐 Google News RSS / Proxies
    participant Gemini as ✨ Google Gemini API (2.5-flash-lite)
    participant EmailSender as 🎨 email_sender.py
    participant GmailAPI as 📬 Gmail REST API
    actor Recipient as 📩 User Inbox

    %% Step 1: Scheduling
    Scheduler->>CloudRun: POST /?hours=24 (with OIDC Bearer Token)
    activate CloudRun
    CloudRun->>Orchestrator: main(hours_back=24)
    activate Orchestrator

    %% Step 2: Auth Check
    Orchestrator->>EmailSender: Verify / Refresh Gmail OAuth Token
    EmailSender-->>Orchestrator: Credentials Valid (token.json)

    %% Step 3: RSS Scraping
    Orchestrator->>RSSParser: parse_and_filter_articles(hours_back=24)
    activate RSSParser
    par Concurrent Fetch (15 Workers)
        RSSParser->>GoogleNews: Direct GET with Desktop UA
        GoogleNews-->>RSSParser: 200 OK / 503 Blocked
        opt On 503 Block
            RSSParser->>GoogleNews: Fallback via corsproxy.io / allorigins.win
            GoogleNews-->>RSSParser: 200 OK (Proxied XML)
        end
    end
    RSSParser->>RSSParser: URL Deduplication & Timestamp Sorting
    RSSParser-->>Orchestrator: List of Unique Articles (~30-80 articles)
    deactivate RSSParser

    %% Step 4: AI Reasoning
    Orchestrator->>Gemini: generate_content(prompt + articles_json)
    activate Gemini
    Note over Gemini: 1. AIFOD Mission Alignment<br/>2. Zero-Tolerance Deduplication<br/>3. Thematic Diversity Ranking<br/>4. English Translation<br/>5. Insight & Q&A Synthesis
    Gemini-->>Orchestrator: Structured JSON (Top 5 Selected Articles)
    deactivate Gemini

    %% Step 5: Email Assembly & Dispatch
    Orchestrator->>EmailSender: send_digest_email(top_5, total_fetched, date_str)
    activate EmailSender
    EmailSender->>EmailSender: Compile Responsive HTML with Plus Jakarta Sans & Country Badges
    EmailSender->>GmailAPI: users.messages.send(raw=MIME_Base64)
    activate GmailAPI
    GmailAPI-->>Recipient: Deliver Daily Digest Email
    GmailAPI-->>EmailSender: Message ID (Success)
    deactivate GmailAPI
    EmailSender-->>Orchestrator: Email Dispatched Successfully
    deactivate EmailSender

    %% Step 6: Completion
    Orchestrator-->>CloudRun: Execution Stats (success=True, counts)
    deactivate Orchestrator
    CloudRun-->>Scheduler: 200 OK (JSON Response)
    deactivate CloudRun
```

---

## Features

- **Resilient Multilingual Retrieval**: Automatically queries Google News RSS feeds for South Korea (in Korean) and Japan (in Japanese) using AIFOD-targeted keywords. Implements rotating browser User-Agents and multiple public CORS proxy fallbacks (`corsproxy.io` and `allorigins.win`) to bypass Google News `503 Service Unavailable` IP blocks on Google Cloud datacenter egress ranges.
- **AIFOD-Focused Filtering & Deduplication**: Uses the Gemini API (`gemini-2.5-flash-lite`) to filter articles strictly relevant to AIFOD's mission (bridging the digital divide, AI policy in emerging markets, capacity building, and international cooperation). It aggressively deduplicates similar or overlapping stories across both countries and sources, selecting the top 5 most significant developments of the day.
- **AIFOD Value-Adds**: For each of the top 5 articles, Gemini generates:
  - A 2-3 sentence English summary.
  - An analytical paragraph explaining the significance/implication of the news specifically for AIFOD.
  - A critical question that AIFOD practitioners should ask regarding the development.
  - A suggested stance/response representing AIFOD's perspective.
- **Premium Email Digests**: Compiles a responsive, beautifully styled HTML email with country-specific badges, relevance markers, and clean layouts sent directly via the Gmail API.
- **GCP Native**: Fully containerized and deployed on Google Cloud Run, triggered securely with OIDC authentication by Cloud Scheduler.

---

## File Structure

```text
├── src/
│   ├── __init__.py
│   ├── app.py           # Flask web service entry point for Cloud Run
│   ├── auth.py          # Gmail OAuth authentication helper
│   ├── config.py        # Configuration variables & search query keywords
│   ├── email_sender.py  # HTML email generator & Gmail sender
│   ├── llm_filter.py    # Gemini filtering, translation, and AIFOD analysis
│   ├── main.py          # Orchestration pipeline
│   └── rss_parser.py    # RSS parsing & filtering by publication time
├── deployment/
│   └── deploy_cloud.ps1 # PowerShell script to build & deploy to GCP
├── .env                 # Local environment configuration (git-ignored)
├── .env.example         # Template for environment configuration
├── .gcloudignore        # Custom ignore rules to copy credentials during builds
├── .gitignore           # Git ignore rules
├── Dockerfile           # Container build file
├── requirements.txt     # Python dependencies
└── README.md            # Project documentation (this file)
```

---

## Local Setup & Execution

### 1. Installation
Clone this repository and install the dependencies (Python 3.11+ recommended):

```bash
pip install -r requirements.txt
```

### 2. Configuration
Copy the `.env.example` file to `.env` and fill in your credentials:
- `GEMINI_API_KEY`: Google AI Gemini API Key.
- `GCP_PROJECT_ID`: Google Cloud Project ID.
- `RECIPIENT_EMAIL`: Recipient email (e.g., `henry.hyunwookim@gmail.com`).

Make sure your Google OAuth client credential files (`credentials.json` and `token.json`) are present in the project root directory.

### 3. Interactive Authentication
If `token.json` is expired or missing, run the following command in an interactive terminal to perform the Gmail OAuth login flow in your browser:

```bash
python -m src.main --auth
```

### 4. Running Locally
To run a test harvest locally (default is last 24 hours):

```bash
python -m src.main
```

To run a test harvest looking back a specific number of hours (e.g. 48 hours):

```bash
python -m src.main --hours 48
```

---

## Cloud Deployment

Deploying the service to Google Cloud Run and configuring Cloud Scheduler is automated using the deployment script:

```powershell
.\deployment\deploy_cloud.ps1
```

This script will:
1. Enable necessary Google Cloud APIs (`run.googleapis.com`, `cloudbuild.googleapis.com`, etc.).
2. Submit a build to Cloud Build, compile the container, and deploy it to **Cloud Run** (`ai-news-aggregator-krjp`).
3. Set up a secure Service Account (`ai-news-scheduler-sa`) with permissions to invoke the Cloud Run service.
4. Create or update a **Cloud Scheduler Job** (`ai-news-aggregator-daily-trigger`) configured to trigger the service daily at midnight (`0 0 * * *`) in the `Asia/Tokyo` timezone.

---

## Verification & Manual Trigger

You can manually trigger the deployed Cloud Run service through Cloud Scheduler at any time using `gcloud`:

```bash
gcloud scheduler jobs run ai-news-aggregator-daily-trigger --location=us-central1
```

Check the execution logs of your service in the Google Cloud Console under the **Cloud Run logs tab** for `ai-news-aggregator-krjp`.
