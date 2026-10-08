# JobFlow AI

**Personal portfolio project · Python · FastAPI · SQLAlchemy · SQLite · JavaScript**

[Español](README.md) · [Architecture](docs/architecture.md) · [Demo guide](docs/demo.md)


JobFlow helps a job seeker review listings using explicit filters, title relevance and explainable scores. It keeps facts, inferences and unknown information separate, preserves user feedback across searches and suggests preference changes that require approval.

## Features

- Adzuna integration, conservative deduplication and persistent feedback.
- Search by postcode radius, date and employment type, including explicit Minijob wording.
- Sorting, saved/interested/rejected counts and remembered browser filters.
- Optional OpenAI analysis with structured JSON and checked evidence quotes.
- Explicit confirmation of selected analysis requests, reusable cache and local call limits.
- Reviewable preference adjustments from feedback; conditional interest notes are preserved separately.

## Run the synthetic demo

Python **3.11+** is required. Create a virtual environment and install `requirements.txt`. Run `python demo.py` with that environment, then open **http://127.0.0.1:8799/** and submit a search.

The demo uses synthetic listings and isolated local storage. It makes no Adzuna or OpenAI requests. Live integrations require credentials in a private `.env` file. The Spanish README contains Windows and macOS/Linux commands.

## Scope and limitations

This version uses postcode 44145 in Dortmund and a 0–10 km radius. Adzuna snippets are incomplete and only up to 50 candidates are processed per search. Approximate coordinates do not establish exact distance. Feedback adjusts reviewed rule weights rather than training a custom model. The app has one shared user profile; online deployment has not been completed or verified.

This is a personal project developed with AI assistance. The repository includes generic configuration and synthetic examples, not the original user's credentials, private database or personal qualification profile.

GeoNames postcode coordinates are attributed in the [Spanish README](README.md). Live listings retain Adzuna attribution.
