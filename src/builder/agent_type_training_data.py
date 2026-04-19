"""Seed training data for the Agent Type Classifier.

Maps (goal_text, tools) → agent_type label.  The classifier learns
to identify which of the 10 specialised types (+ "general") a new
agent belongs to based on its stated goal and selected tools.

Agent types mirror the mood prompts in src/prompts/modules/mood_*.py:
  researcher, scraper, monitor, sales, content, code,
  email, data, social, integration, general
"""

AGENT_TYPES = [
    "researcher",
    "scraper",
    "monitor",
    "sales",
    "content",
    "code",
    "email",
    "data",
    "social",
    "integration",
    "general",
]


def get_training_data():
    """Return list of (goal_text, agent_type) tuples for training."""
    return [
        # ── Researcher ──
        ("Research the latest AI trends and create a briefing", "researcher"),
        ("Find the top 10 competitors in the SaaS market", "researcher"),
        ("Investigate blockchain adoption in healthcare", "researcher"),
        ("Compile a report on renewable energy startups", "researcher"),
        ("Research best practices for microservice architecture", "researcher"),
        ("Summarize the latest papers on transformer models", "researcher"),
        ("Find news about Tesla stock and earnings", "researcher"),
        ("Research cybersecurity threats in 2026", "researcher"),
        ("Investigate the impact of AI on education", "researcher"),
        ("Build a daily research briefing on fintech trends", "researcher"),
        ("Analyze market trends for electric vehicles in Europe", "researcher"),
        ("Research privacy regulations GDPR CCPA and how they affect SaaS", "researcher"),
        ("Find the latest funding rounds for AI companies", "researcher"),
        ("Investigate supply chain disruptions in semiconductor industry", "researcher"),

        # ── Scraper ──
        ("Scrape product prices from Amazon for these 5 products", "scraper"),
        ("Crawl job listings from LinkedIn for data engineer roles", "scraper"),
        ("Scrape all company profiles from Crunchbase in the AI category", "scraper"),
        ("Extract real estate listings from Zillow for San Francisco", "scraper"),
        ("Crawl news headlines from TechCrunch daily", "scraper"),
        ("Scrape restaurant reviews from Yelp for New York", "scraper"),
        ("Extract product specifications from manufacturer websites", "scraper"),
        ("Crawl patent filings from USPTO related to machine learning", "scraper"),
        ("Scrape flight prices from Google Flights for LAX to JFK", "scraper"),
        ("Collect GitHub repository stats for Python ML libraries", "scraper"),
        ("Scrape all product listings and prices from competitor store", "scraper"),
        ("Extract contact info from business directory pages", "scraper"),

        # ── Monitor ──
        ("Monitor competitor pricing changes daily", "monitor"),
        ("Watch for new job postings at Google and notify me", "monitor"),
        ("Track website uptime and alert if it goes down", "monitor"),
        ("Monitor Hacker News for mentions of our company", "monitor"),
        ("Watch for price drops on these 10 products", "monitor"),
        ("Alert me when new SEC filings are posted for Apple", "monitor"),
        ("Monitor social media for brand mentions", "monitor"),
        ("Track changes on competitor landing pages", "monitor"),
        ("Watch for new regulations in crypto compliance", "monitor"),
        ("Monitor stock price of NVIDIA and alert on 5% changes", "monitor"),
        ("Alert me whenever a specific subreddit has a trending post", "monitor"),
        ("Watch for new GitHub issues on our open source project", "monitor"),

        # ── Sales ──
        ("Generate leads for B2B SaaS companies in healthcare", "sales"),
        ("Find contact info for CTOs at Fortune 500 companies", "sales"),
        ("Build a prospect list for our new product launch", "sales"),
        ("Research potential clients in the real estate industry", "sales"),
        ("Create an outreach sequence for warm leads", "sales"),
        ("Find companies using Salesforce that might switch to us", "sales"),
        ("Generate leads of startup founders who raised Series A", "sales"),
        ("Build prospect database for cybersecurity vendors", "sales"),
        ("Find decision makers at companies with 50-200 employees", "sales"),
        ("Automate follow-up emails for cold outreach campaign", "sales"),
        ("Research and qualify inbound leads from our website", "sales"),
        ("Find companies hiring for DevOps roles as potential clients", "sales"),

        # ── Content ──
        ("Write a blog post about AI trends in 2026", "content"),
        ("Create a weekly newsletter about tech industry news", "content"),
        ("Generate social media posts for our product launch", "content"),
        ("Write product descriptions for our e-commerce store", "content"),
        ("Create an email newsletter summarizing industry news", "content"),
        ("Write a technical tutorial on building REST APIs", "content"),
        ("Generate marketing copy for our landing page", "content"),
        ("Create a weekly summary of top tech articles", "content"),
        ("Write press release for our new product feature", "content"),
        ("Create SEO-optimized blog content about cloud computing", "content"),
        ("Draft a whitepaper on enterprise AI adoption", "content"),
        ("Write documentation for our API endpoints", "content"),

        # ── Code ──
        ("Review code changes in our GitHub repository", "code"),
        ("Build a Python script to process CSV files", "code"),
        ("Fix bugs in our Node.js backend", "code"),
        ("Create unit tests for the authentication module", "code"),
        ("Refactor the database query layer for better performance", "code"),
        ("Analyze code quality and suggest improvements", "code"),
        ("Generate boilerplate code for a new microservice", "code"),
        ("Build a CI/CD pipeline configuration", "code"),
        ("Debug the memory leak in our React application", "code"),
        ("Write a data migration script for PostgreSQL", "code"),
        ("Create an automated code review agent for pull requests", "code"),
        ("Build a REST API endpoint for user management", "code"),

        # ── Email ──
        ("Send daily digest email with top news stories", "email"),
        ("Automate weekly report email to stakeholders", "email"),
        ("Read my inbox and summarize unread important emails", "email"),
        ("Send personalized outreach emails to 50 contacts", "email"),
        ("Create an automated email response for support queries", "email"),
        ("Forward important Gmail messages to Slack", "email"),
        ("Send a notification email when a task completes", "email"),
        ("Read and categorize support emails by urgency", "email"),
        ("Send automated follow-up emails after meetings", "email"),
        ("Create an email-based workflow for invoice approvals", "email"),
        ("Monitor inbox for emails from VIP clients and alert immediately", "email"),
        ("Send weekly performance reports via email to the team", "email"),

        # ── Data ──
        ("Collect and analyze sales data from our CRM", "data"),
        ("Process CSV files and generate summary statistics", "data"),
        ("Build a dashboard of key business metrics", "data"),
        ("Analyze customer churn patterns from usage data", "data"),
        ("Create a spreadsheet comparing vendor pricing", "data"),
        ("Process survey responses and generate insights", "data"),
        ("Aggregate financial data from multiple sources", "data"),
        ("Clean and normalize our customer database", "data"),
        ("Build a data pipeline for real-time analytics", "data"),
        ("Analyze website traffic patterns and generate report", "data"),
        ("Extract data from PDFs and organize into spreadsheet", "data"),
        ("Calculate ROI metrics from marketing campaign data", "data"),

        # ── Social ──
        ("Post daily updates to Twitter about our product", "social"),
        ("Monitor Reddit for discussions about our brand", "social"),
        ("Schedule LinkedIn posts for the week", "social"),
        ("Engage with comments on our Instagram posts", "social"),
        ("Track social media engagement metrics across platforms", "social"),
        ("Post to multiple social networks simultaneously", "social"),
        ("Find trending topics on Twitter relevant to our industry", "social"),
        ("Manage our Reddit community engagement", "social"),
        ("Create and schedule a week of social media content", "social"),
        ("Respond to customer inquiries on social media", "social"),
        ("Analyze competitor social media presence and strategy", "social"),
        ("Post product launch announcements on all social channels", "social"),

        # ── Integration ──
        ("Connect Salesforce data to our internal dashboard", "integration"),
        ("Build a Slack bot that answers questions from our docs", "integration"),
        ("Sync data between Google Sheets and our database", "integration"),
        ("Automate Jira ticket creation from Slack messages", "integration"),
        ("Connect Stripe payments to our accounting system", "integration"),
        ("Build a workflow connecting GitHub and Slack notifications", "integration"),
        ("Integrate our CRM with email marketing platform", "integration"),
        ("Create API bridge between internal tools", "integration"),
        ("Automate data sync between Shopify and inventory system", "integration"),
        ("Connect monitoring alerts to PagerDuty", "integration"),
        ("Build webhook handler for third-party service events", "integration"),
        ("Automate workflow: form submission to CRM to email sequence", "integration"),

        # ── General ──
        ("Help me plan my project timeline", "general"),
        ("Answer questions about our platform", "general"),
        ("Brainstorm ideas for a new feature", "general"),
        ("Summarize this document for me", "general"),
        ("What can you do?", "general"),
        ("Help me organize my tasks", "general"),
        ("Create a checklist for product launch", "general"),
        ("Explain how our billing system works", "general"),
        ("Compare options A and B and recommend one", "general"),
        ("Set up a workflow for the marketing team", "general"),
    ]
