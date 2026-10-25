# Upline

Hack/OHIO 2026, AEP Challenge: AI Outage Concierge

Built by Varun Viswapriyan and Matt Wang, Computer Science and Engineering, The Ohio State University.

## About

When a big storm is coming, people want to know if they'll lose power, for how long, and what they should do to prepare. Upline is a mobile app that answers those questions for each individual home before the storm hits.

We built Upline on AEP's Roanoke Valley data, which covers homes, power lines, equipment, past storm damage and crew labor standards. Using AEP's network data, we trace the path power takes from each home back to its substation. A home only loses power if something on that path breaks, so Upline uses it to estimate outage risk, with a Poisson regression model trained on past damage records. If the power goes out, a Monte Carlo simulation of repair crews gives a range for when it will be back. Users can change crews, road access or damage and watch the estimate update.

Upline also creates a plan for before, during and after an outage, and personalizes it for each customer. Customers can tell the app about their household, and Upline builds a plan around their specific needs, adding the steps that matter for them and explaining why each one is there. Alerts go out by text, app, call or email, in English or Spanish, and the AI assistant, powered by GPT-OSS 120B on Groq, answers questions by text or voice using only Upline's own numbers.

What makes Upline different is that every answer is specific to one home and explained in plain words. Instead of a general outage map, customers see their own power path and the weak spot most likely to fail. The AI can't make up numbers, every card is labeled as an AEP fact, an estimate or a to-do, and homes stay anonymous. We also tested the risk model on a real storm it had never seen: the areas it rated riskiest were damaged about 15 times more often than the safest.

Our biggest challenges were working with raw utility data, estimating crew capacity that wasn't in the data, and keeping the app simple and private for everyday customers.

## Running it

Requires Python 3.10 or newer. The trained model files are already included in `data/`.

```
pip install numpy
python3 run.py
```

Then open http://localhost:8000 in Chrome. On a laptop the app is shown inside a phone frame. On a phone it runs full screen and can be added to the home screen. Phones need an https link for voice input and installing; a free option is `cloudflared tunnel --url http://localhost:8000`.

### AI assistant

The app works without an API key using built-in answers. To use the language model, set an OpenAI-compatible endpoint before starting:

```
export UPLINE_LLM_BASE_URL="https://api.groq.com/openai/v1"
export UPLINE_LLM_API_KEY="your_groq_key"
export UPLINE_LLM_MODEL="openai/gpt-oss-120b"
python3 run.py --check-ai
python3 run.py
```

### Sending real alerts (optional)

Text messages and calls use Twilio. Email uses any SMTP account, such as Gmail with an app password.

```
export UPLINE_TWILIO_SID="..."
export UPLINE_TWILIO_TOKEN="..."
export UPLINE_TWILIO_FROM="+1XXXXXXXXXX"
export UPLINE_SMTP_USER="you@gmail.com"
export UPLINE_SMTP_PASS="your_app_password"
```

App notifications work in the browser without any setup.

### Rebuilding the model from AEP's data (optional)

```
pip install -r requirements-pipeline.txt
python3 pipeline/build_data.py --raw /path/to/aep_challenge_hack26-main/data
python3 pipeline/calibrate.py
```

## Files

```
run.py                     Starts the web server and handles the API routes
requirements.txt           Packages needed to run the app
requirements-pipeline.txt  Packages needed to rebuild the model from raw data

server/engine.py           Outage risk model, power path, Monte Carlo restoration simulation, map data
server/guidance.py         Personalized preparation plan, alert rules and alert messages (English and Spanish)
server/concierge.py        AI assistant: safety and privacy checks, question handling, language model calls
server/notify.py           Sends real text messages, phone calls and emails

pipeline/build_data.py     Reads AEP's data, builds the power network, trains and tests the risk model
pipeline/calibrate.py      Sets crew capacity so the simulation matches the February 2025 repair timeline
pipeline/shp.py            Reads shapefile geometry
pipeline/dbf.py            Reads shapefile attribute tables

data/model.json            Model settings, test results and labor standards
data/network.json          Power network: protective devices, transformers and risk values
data/premises.json         Anonymous home IDs and generalized locations
data/map.json              Neighborhood map grid, main lines and generalized facility locations
data/calibration.json      Crew capacity calibration results

web/index.html             App layout
web/app.js                 App behavior: screens, charts, map, voice input, alerts, storm playback
web/app.css                App styling
web/sw.js                  Service worker that lets the app be installed and open offline
web/manifest.json          App name and icons for installing on a phone
web/icon.svg, icon-*.png   App icons
```

## Data and privacy

All homes use anonymous IDs. Life-support and safety flags in the source data are never loaded. The map shows neighborhoods of at least 10 homes, and hospital and emergency service locations are generalized. Personal details typed into the assistant are removed before processing, and contact details for alerts are used once and not stored.
