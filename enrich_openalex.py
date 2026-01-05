"""
CLI script to enrich all researchers with OpenAlex data.

Usage (from project root):

    source .venv/bin/activate
    python enrich_openalex.py

Optional environment variable:

    export OPENALEX_MAILTO="your-email@example.com"

OpenAlex recommends passing a contact email via the "mailto" parameter.
"""

from backend.db import SessionLocal
from backend.openalex_service import OpenAlexService, enrich_all_researchers


def main():
    sess = SessionLocal()
    try:
        svc = OpenAlexService()
        n = enrich_all_researchers(sess, svc)
        print(f"Enriched {n} researchers with OpenAlex data.")
    finally:
        sess.close()


if __name__ == "__main__":
    main()
