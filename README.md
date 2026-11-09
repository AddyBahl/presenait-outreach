# PresenAIT outreach agent

Finds businesses near you, researches them, and drafts personalised outreach selling
PresenAIT **attendance tracking**. It also handles **shopping centre partners**
(referral-fee pitch). It comes with a dashboard that opens in your web browser.

**It never sends anything.** You check every draft and send it yourself.

## 1. Set up (once)

You need **Python 3.10 or newer** (python.org/downloads). Open Terminal (Mac) or
Command Prompt (Windows), go to the folder that contains `app.py`, and run each line.
On Windows, use `.venv\Scripts\activate` instead of `source .venv/bin/activate`.

```bash
cd path/to/presenait-outreach   # the folder that contains app.py
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Start the dashboard

```bash
cd path/to/presenait-outreach   # the folder that contains app.py
source .venv/bin/activate
python app.py
```

Your browser opens at http://127.0.0.1:5055. It only runs on your Mac; nobody else can
reach it. To stop it, go back to Terminal and press **Ctrl + C**.

First time: go to **Settings**, paste your Anthropic API key (from console.anthropic.com,
with some prepaid credit), and add your name, title and email for the signature.

## 3. Using it

| Tab | What you do |
|---|---|
| **01 Find businesses** | Pick a business type (e.g. "Commercial cleaning") and an area (e.g. "Werribee VIC"). The agent searches the web and lists real businesses with their website, phone, size and contact page. Tick the ones you want and add them to your prospects. Switch to **Shopping centres** to find partner centres. |
| **02 Prospects** | Your list. Open each **contact page**, and if an email is published for the right role, paste it in. Add a contact name if you know it. Everything saves automatically. |
| **03 Write drafts** | Choose how many to do and a spending limit, then click **Write drafts**. Watch progress live; press Stop at any time. |
| **04 Drafts** | Best fit first. Edit, **Copy**, or **Open in Mail** (opens your mail app with the draft - you press send). Mark each one Ready, Sent or Skipped. |

### Why it doesn't collect email addresses

Australia's **Spam Act 2003 (sections 20-22)** bans making, buying or using software that
searches the internet for email addresses and collects them. So the finder brings back each
business's contact page, phone number and website, never email addresses (and it strips out
any that slip through). You add an address yourself only when it's published on their
website for the role you're contacting.

## Cost

| AI model | Finding 10 businesses | Drafting 1 business | 100 drafts |
|---|---|---|---|
| Opus 5.5 (default, best writing) | US$0.15-0.60 | US$0.12-0.35 | US$12-35 |
| Sonnet 5.5 | US$0.08-0.35 | US$0.06-0.18 | US$6-18 |
| Haiku 5.5 (cheapest) | US$0.05-0.12 | US$0.02-0.05 | US$2-5 |

These are estimates; the dashboard shows the running total, and each drafting run stops at
your spending limit. Check real usage in the Anthropic console.

## Before you send anything

- **Check every fact** in each draft against the business's website.
- **Spam Act:** only email addresses published for that person's role, keep the signature
  (it identifies you and gives an unsubscribe option), and honour every unsubscribe.
- Change the shopping centre referral offer in **Settings** once you've decided on it.

## Files

| File | What it is |
|---|---|
| `app.py` | The dashboard (a small local website) |
| `agent.py` | The AI steps: find businesses, research, write drafts |
| `store.py` | Reads and saves the lists |
| `static/index.html` | The dashboard's page |
| `prospects.csv` | Your prospect list (opens in Excel) |
| `output/drafts.md`, `output/drafts.csv` | Readable copies of all drafts |
| `.env` | Your API key, created when you save it in Settings. **Never share it.** |

## Without the dashboard (optional)

```bash
python agent.py find --industry "commercial cleaning" --location "Werribee VIC" --count 10
python agent.py find --type partner --location "Point Cook VIC" --count 5
python agent.py draft --dry-run
python agent.py draft --limit 5 --budget-usd 2
```
