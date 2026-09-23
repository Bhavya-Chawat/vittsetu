"""Helper script to quickly add new scheme documents to data/ and rebuild the index."""

import argparse
import os
import sys
import re
from pathlib import Path

# Allow imports from project root
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from rag_core import force_rebuild_index

DATA_DIR = BASE_DIR / "data"


def sanitize_filename(name: str) -> str:
    """Convert scheme name to clean filename."""
    s = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"[\s-]+", "_", s) + ".txt"


def create_scheme_file(
    name: str,
    level: str,
    category: str,
    key_benefit: str,
    eligibility: str,
    benefits: str,
    application_process: str,
) -> Path:
    """Generate standardized scheme file in data/."""
    filename = sanitize_filename(name)
    filepath = DATA_DIR / filename

    content = f"""{name}
Level: {level}
Category: {category}
Key Benefit: {key_benefit}

===================================================
ELIGIBILITY CRITERIA
===================================================

{eligibility.strip()}

===================================================
SCHEME DETAILS & BENEFITS
===================================================

{benefits.strip()}

===================================================
APPLICATION PROCESS & DOCUMENTS
===================================================

{application_process.strip()}
"""
    filepath.write_text(content, encoding="utf-8")
    print(f"[INFO] Created scheme document at: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Add a new scheme document to RAG dataset")
    parser.add_argument("--name", help="Full scheme name (e.g. 'PM Awas Yojana')")
    parser.add_argument("--level", default="National", help="Level (e.g. 'National' or 'State - Karnataka')")
    parser.add_argument("--category", default="Financial Assistance", help="Category")
    parser.add_argument("--benefit", default="Subsidized Loan / Grant", help="Key Benefit short description")
    parser.add_argument("--file", help="Path to raw text file containing scheme details")
    parser.add_argument("--no-reindex", action="store_true", help="Skip automatic index rebuilding")

    args = parser.parse_args()

    if args.name and args.file:
        raw_text = Path(args.file).read_text(encoding="utf-8")
        create_scheme_file(
            name=args.name,
            level=args.level,
            category=args.category,
            key_benefit=args.benefit,
            eligibility=raw_text,
            benefits=raw_text,
            application_process=raw_text,
        )
    elif args.name:
        print(f"Adding scheme: {args.name}")
        eligibility = input("Enter Eligibility Criteria details: ")
        benefits = input("Enter Scheme Benefits & Loan Details: ")
        application = input("Enter Application Process & Documents required: ")
        create_scheme_file(
            name=args.name,
            level=args.level,
            category=args.category,
            key_benefit=args.benefit,
            eligibility=eligibility,
            benefits=benefits,
            application_process=application,
        )
    else:
        print("=== Interactive Scheme Builder ===")
        name = input("Scheme Name (e.g., PM Vishwakarma Scheme): ").strip()
        if not name:
            print("Scheme name is required!")
            return
        level = input("Level [Default: National]: ").strip() or "National"
        category = input("Category [Default: Financial Assistance]: ").strip() or "Financial Assistance"
        benefit = input("Key Benefit Summary: ").strip() or "Financial & skill support"
        print("\nPaste or type ELIGIBILITY CRITERIA:")
        eligibility = input("Eligibility: ")
        
        create_scheme_file(
            name=name,
            level=level,
            category=category,
            key_benefit=benefit,
            eligibility=eligibility,
            benefits=eligibility,
            application_process=eligibility,
        )

    if not args.no_reindex:
        print("[INFO] Rebuilding ChromaDB vector store index...")
        coll = force_rebuild_index()
        print(f"[SUCCESS] Index rebuilt! Total indexed chunks: {coll.count()}")


if __name__ == "__main__":
    main()
