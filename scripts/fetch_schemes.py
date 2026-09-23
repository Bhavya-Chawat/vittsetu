#!/usr/bin/env python3
"""Automated Government Scheme Fetcher & Categorizer for RAG Dataset.

Fetches official central and state government schemes from MyScheme.gov.in,
formats them into standardized .txt documents, categorizes them into dedicated
subfolders inside data/, and automatically updates the ChromaDB vector store.
"""

import argparse
import html
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import requests

# Set up project path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from rag_core import force_rebuild_index
except ImportError:
    force_rebuild_index = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scheme_fetcher")

DATA_DIR = BASE_DIR / "data"
API_BASE_URL = "https://api.myscheme.gov.in"
DEFAULT_API_KEY = "tYTy5eEhlu9rFjyxuCr7ra7ACp4dv1RH8gWuHTDc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www.myscheme.gov.in",
    "Referer": "https://www.myscheme.gov.in/",
    "x-api-key": DEFAULT_API_KEY,
}

# Standard Category Mappings with discovery search keywords & folder paths
CATEGORIES_CONFIG: Dict[str, Dict[str, Any]] = {
    "agriculture": {
        "label": "Agriculture, Rural & Environment",
        "folder": "agriculture",
        "keywords": ["agriculture", "kisan", "farmer", "crop", "krishi", "fertilizer", "tractor", "dairy", "horticulture", "fisheries"],
    },
    "business": {
        "label": "Business & Entrepreneurship",
        "folder": "business_and_msme",
        "keywords": ["msme", "business", "subsidy", "loan", "vendor", "entrepreneur", "startup", "khadi", "pmegp", "industry"],
    },
    "education": {
        "label": "Education & Learning",
        "folder": "education_and_learning",
        "keywords": ["scholarship", "student", "education", "school", "college", "matric", "fellowship", "coaching", "higher education"],
    },
    "women": {
        "label": "Women and Child",
        "folder": "women_and_child",
        "keywords": ["women", "girl", "mother", "matru", "mahila", "kanya", "beti", "sukanya", "maternity", "adolescent girls"],
    },
    "health": {
        "label": "Health & Wellness",
        "folder": "health_and_wellness",
        "keywords": ["health", "ayushman", "medical", "hospital", "arogya", "treatment", "swasthya", "medicine", "health insurance"],
    },
    "housing": {
        "label": "Housing & Shelter",
        "folder": "housing_and_shelter",
        "keywords": ["awas", "housing", "shelter", "ghar", "home loan subsidy", "pradhan mantri awas yojana"],
    },
    "social_welfare": {
        "label": "Social Welfare & Empowerment",
        "folder": "social_welfare",
        "keywords": ["pension", "senior citizen", "disability", "minority", "sc st", "divyang", "welfare", "tribal", "backward classes"],
    },
    "skills": {
        "label": "Skills & Employment",
        "folder": "skills_and_employment",
        "keywords": ["skill", "employment", "training", "pmkvy", "apprenticeship", "vocational", "kaushal", "placement"],
    },
    "banking": {
        "label": "Banking, Financial Services & Insurance",
        "folder": "banking_and_financial",
        "keywords": ["pension", "insurance", "financial assistance", "savings certificate", "micro finance", "atal pension"],
    },
    "law_and_justice": {
        "label": "Public Safety, Law & Justice",
        "folder": "public_safety_and_law",
        "keywords": ["nyaya mitra", "legal aid", "tele law", "victim compensation", "law"],
    },
}


def clean_text(text: Optional[str]) -> str:
    """Clean HTML entities and whitespace from text."""
    if not text:
        return ""
    text = html.unescape(text)
    # Remove HTML tags if any
    text = re.sub(r"<[^>]+>", " ", text)
    # Normalize unicode spaces/quotes
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u20b9", "₹").replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_slate_nodes(nodes: Any, depth: int = 0, list_type: str = "ul", index: int = 1) -> str:
    """Recursively convert Slate JSON AST or list of nodes to clean Markdown text."""
    if not nodes:
        return ""
    if isinstance(nodes, str):
        return clean_text(nodes)

    if isinstance(nodes, dict):
        # Handle string markdown fallback if present
        if "eligibilityDescription_md" in nodes:
            return clean_text(nodes["eligibilityDescription_md"])
        if "children" in nodes:
            node_type = nodes.get("type", "")
            children_text = parse_slate_nodes(nodes["children"], depth=depth, list_type=list_type, index=index)

            if node_type == "paragraph":
                return f"\n{children_text}\n"
            elif node_type == "list_item":
                bullet = "* " if list_type == "ul" else f"{index}. "
                indent = "  " * depth
                return f"\n{indent}{bullet}{children_text.strip()}"
            elif node_type in ("ul_list", "unordered-list"):
                return parse_slate_nodes(nodes["children"], depth=depth + 1, list_type="ul")
            elif node_type in ("ol_list", "ordered-list"):
                return parse_slate_nodes(nodes["children"], depth=depth + 1, list_type="ol")
            elif node_type in ("heading-one", "h1"):
                return f"\n\n### {children_text.strip()}\n"
            elif node_type in ("heading-two", "h2", "heading-three", "h3"):
                return f"\n\n#### {children_text.strip()}\n"
            return children_text

        # Text leaf node
        text = nodes.get("text", "")
        if nodes.get("bold"):
            text = f"**{text}**"
        if nodes.get("italic"):
            text = f"*{text}*"
        return clean_text(text)

    if isinstance(nodes, list):
        out = []
        for i, item in enumerate(nodes, start=1):
            res = parse_slate_nodes(item, depth=depth, list_type=list_type, index=i)
            if res:
                out.append(res)
        return "".join(out)

    return str(nodes)


def sanitize_filename(name: str) -> str:
    """Create safe filename for a scheme."""
    name = re.sub(r"[^\w\s-]", "", name).strip()
    clean = re.sub(r"[\s-]+", "_", name)
    return f"{clean}.txt"


def get_existing_scheme_names(data_dir: Path = DATA_DIR) -> Set[str]:
    """Index existing filenames and scheme names across all data subfolders."""
    existing = set()
    if not data_dir.exists():
        return existing
    for f in data_dir.rglob("*.txt"):
        existing.add(f.stem.lower())
        try:
            first_line = f.read_text(encoding="utf-8").split("\n")[0].strip()
            if first_line:
                existing.add(first_line.lower())
        except Exception:
            pass
    return existing


def fetch_scheme_slugs_by_keywords(keywords: List[str], limit: int = 10) -> List[Tuple[str, str]]:
    """Discover scheme (slug, name) pairs using autocomplete keywords."""
    discovered: Dict[str, str] = {}
    for kw in keywords:
        if len(discovered) >= limit:
            break
        try:
            url = f"{API_BASE_URL}/search/v6/autocomplete?lang=en&suggest={requests.utils.quote(kw)}"
            res = requests.get(url, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                hits = res.json().get("data", {}).get("hits", {}).get("hits", [])
                for h in hits:
                    source = h.get("_source", {})
                    slug = source.get("slug")
                    name = source.get("schemeName") or source.get("schemeShortTitle")
                    if slug and name and slug not in discovered:
                        discovered[slug] = name
                        if len(discovered) >= limit:
                            break
            time.sleep(0.15)
        except Exception as e:
            logger.warning(f"Error querying keyword '{kw}': {e}")
    return list(discovered.items())


def fetch_scheme_details(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch complete scheme information from MyScheme API."""
    try:
        url = f"{API_BASE_URL}/schemes/v6/public/schemes?slug={slug}&lang=en"
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            logger.warning(f"Failed to fetch scheme slug '{slug}' (status {res.status_code})")
            return None

        payload = res.json()
        if payload.get("statusCode") != 200 or not payload.get("data"):
            logger.warning(f"No data found for slug '{slug}'")
            return None

        scheme_data = payload["data"]
        scheme_id = scheme_data.get("_id")
        en = scheme_data.get("en", {})
        if not en:
            return None

        # Fetch required documents checklist
        documents_list = []
        if scheme_id:
            try:
                doc_url = f"{API_BASE_URL}/schemes/v6/public/schemes/{scheme_id}/documents?lang=en"
                r_doc = requests.get(doc_url, headers=HEADERS, timeout=10)
                if r_doc.status_code == 200:
                    doc_payload = r_doc.json().get("data", {}).get("en", {})
                    documents_list = doc_payload.get("documents_required", [])
            except Exception as e:
                logger.debug(f"Could not fetch docs for {slug}: {e}")

        return {
            "slug": slug,
            "id": scheme_id,
            "basicDetails": en.get("basicDetails", {}),
            "schemeContent": en.get("schemeContent", {}),
            "eligibilityCriteria": en.get("eligibilityCriteria", {}),
            "documentsRequired": documents_list,
        }
    except Exception as e:
        logger.error(f"Error fetching scheme details for '{slug}': {e}")
        return None


def format_scheme_document(data: Dict[str, Any], default_category_label: str = "General") -> Tuple[str, str, str]:
    """Format fetched scheme data into standardized markdown/txt document.

    Returns (filename, content, category_folder).
    """
    basic = data.get("basicDetails", {})
    content = data.get("schemeContent", {})
    eligibility_obj = data.get("eligibilityCriteria", {})
    docs_obj = data.get("documentsRequired", [])

    # Scheme Name
    name = basic.get("schemeName") or basic.get("schemeShortTitle") or data.get("slug", "Unknown Scheme")
    name = clean_text(name)

    # Level
    level_val = basic.get("level", "National")
    if isinstance(level_val, dict):
        level_val = level_val.get("label", "National")
    state_name = basic.get("state", "")
    if isinstance(state_name, dict):
        state_name = state_name.get("label", "")
    level_str = f"State ({state_name})" if state_name and "state" in str(level_val).lower() else str(level_val)

    # Category
    categories = basic.get("schemeCategory", [])
    category_labels = []
    if isinstance(categories, list):
        for c in categories:
            if isinstance(c, dict) and "label" in c:
                category_labels.append(c["label"])
            elif isinstance(c, str):
                category_labels.append(c)
    category_str = ", ".join(category_labels) if category_labels else default_category_label

    # Brief / Key Benefit
    brief = clean_text(content.get("briefDescription", ""))
    key_benefit = brief if brief else "Financial & Welfare Assistance"
    if len(key_benefit) > 180:
        key_benefit = key_benefit[:177] + "..."

    # Eligibility
    eligibility_text = ""
    if isinstance(eligibility_obj, dict):
        eligibility_text = parse_slate_nodes(eligibility_obj.get("eligibilityDescription") or eligibility_obj)
    elif eligibility_obj:
        eligibility_text = parse_slate_nodes(eligibility_obj)
    if not eligibility_text.strip():
        eligibility_text = "* General eligibility as per ministry guidelines."

    # Benefits
    benefits_text = ""
    if content.get("benefits"):
        benefits_text = parse_slate_nodes(content["benefits"])
    elif content.get("detailedDescription"):
        benefits_text = parse_slate_nodes(content["detailedDescription"])
    if not benefits_text.strip():
        benefits_text = f"* {brief}" if brief else "* Financial and social benefits as per scheme norms."

    # Application Process & Documents
    app_text = ""
    if content.get("applicationProcess"):
        app_text = parse_slate_nodes(content["applicationProcess"])
    elif content.get("application_process"):
        app_text = parse_slate_nodes(content["application_process"])
    if not app_text.strip():
        app_text = "Visit the official government scheme portal or nearest citizen service center to apply."

    docs_text = ""
    if docs_obj:
        docs_text = parse_slate_nodes(docs_obj)
    if not docs_text.strip():
        docs_text = "* Aadhaar Card\n* Bank Account Details\n* Residential Proof\n* Income / Category Certificate (if applicable)"

    # Build standardized document body
    doc_content = f"""{name}
Level: {level_str}
Category: {category_str}
Key Benefit: {key_benefit}

===================================================
ELIGIBILITY CRITERIA
===================================================

{eligibility_text.strip()}

===================================================
SCHEME DETAILS & BENEFITS
===================================================

{benefits_text.strip()}

===================================================
APPLICATION PROCESS & DOCUMENTS
===================================================

Application Process:

{app_text.strip()}

Documents Required:

{docs_text.strip()}
"""

    filename = sanitize_filename(basic.get("schemeShortTitle") or name)
    return filename, doc_content.strip() + "\n", category_str


def save_scheme_file(
    filename: str, content: str, folder_name: str, target_dir: Path = DATA_DIR
) -> Path:
    """Save formatted scheme document into its dedicated category subdirectory."""
    category_path = target_dir / folder_name
    category_path.mkdir(parents=True, exist_ok=True)
    filepath = category_path / filename
    filepath.write_text(content, encoding="utf-8")
    return filepath


def fetch_category_schemes(
    category_key: str, count: int = 5, target_dir: Path = DATA_DIR
) -> int:
    """Fetch schemes for a given category and save into dedicated category folder."""
    config = CATEGORIES_CONFIG.get(category_key.lower())
    if not config:
        logger.error(f"Unknown category key '{category_key}'. Use --list-categories to see available options.")
        return 0

    folder = config["folder"]
    label = config["label"]
    keywords = config["keywords"]
    logger.info(f"==> Fetching {count} schemes for category: '{label}' -> data/{folder}/")

    existing_names = get_existing_scheme_names(target_dir)
    slug_pairs = fetch_scheme_slugs_by_keywords(keywords, limit=count * 2)

    saved_count = 0
    for slug, name in slug_pairs:
        if saved_count >= count:
            break

        # Check if already present
        if slug.lower() in existing_names or name.lower() in existing_names:
            logger.info(f"  [SKIP] '{name}' already exists in dataset.")
            continue

        details = fetch_scheme_details(slug)
        if not details:
            continue

        filename, file_content, cat_str = format_scheme_document(details, default_category_label=label)
        saved_file = save_scheme_file(filename, file_content, folder, target_dir)
        logger.info(f"  [SAVED] {saved_file.relative_to(target_dir)}")
        existing_names.add(slug.lower())
        existing_names.add(name.lower())
        existing_names.add(filename.replace(".txt", "").lower())
        saved_count += 1
        time.sleep(0.2)

    logger.info(f"Completed category '{label}': added {saved_count} new scheme(s).\n")
    return saved_count


def fetch_by_slug(slug: str, target_dir: Path = DATA_DIR, folder: str = "general") -> bool:
    """Fetch single scheme by slug."""
    logger.info(f"Fetching scheme by slug: '{slug}'...")
    details = fetch_scheme_details(slug)
    if not details:
        logger.error(f"Failed to fetch scheme for slug '{slug}'")
        return False

    # Auto-detect folder based on category if possible
    basic = details.get("basicDetails", {})
    categories = basic.get("schemeCategory", [])
    matched_folder = folder
    if isinstance(categories, list):
        for c in categories:
            cat_label = (c.get("label") if isinstance(c, dict) else str(c)).lower()
            for k, conf in CATEGORIES_CONFIG.items():
                if k in cat_label or any(w in cat_label for w in conf["keywords"][:3]):
                    matched_folder = conf["folder"]
                    break

    filename, file_content, _ = format_scheme_document(details)
    saved_path = save_scheme_file(filename, file_content, matched_folder, target_dir)
    logger.info(f"[SUCCESS] Saved scheme to {saved_path.relative_to(target_dir)}")
    return True


def fetch_by_query(query: str, count: int = 5, target_dir: Path = DATA_DIR, folder: str = "general") -> int:
    """Search and fetch schemes matching a custom query string."""
    logger.info(f"Searching schemes for query: '{query}'...")
    slug_pairs = fetch_scheme_slugs_by_keywords([query], limit=count * 2)
    if not slug_pairs:
        logger.warning(f"No schemes discovered for query '{query}'")
        return 0

    existing = get_existing_scheme_names(target_dir)
    saved_count = 0
    for slug, name in slug_pairs:
        if saved_count >= count:
            break
        if slug.lower() in existing or name.lower() in existing:
            continue
        details = fetch_scheme_details(slug)
        if not details:
            continue
        filename, file_content, _ = format_scheme_document(details)
        saved_path = save_scheme_file(filename, file_content, folder, target_dir)
        logger.info(f"  [SAVED] {saved_path.relative_to(target_dir)}")
        saved_count += 1
        time.sleep(0.2)

    return saved_count


def list_categories():
    """Print available category keys and folders."""
    print("\nAvailable Scheme Categories:")
    print("=" * 65)
    print(f"{'Category Key':<18} | {'Folder Name':<25} | {'Official Label'}")
    print("-" * 65)
    for key, conf in CATEGORIES_CONFIG.items():
        print(f"{key:<18} | data/{conf['folder']:<20} | {conf['label']}")
    print("=" * 65)
    print("Tip: Use --category all to fetch across all categories at once.\n")


def trigger_rebuild_index():
    """Rebuild ChromaDB vector index, streaming progress in real-time."""
    if force_rebuild_index is not None:
        return force_rebuild_index()

    venv_py = BASE_DIR / "venv" / "Scripts" / "python.exe"
    build_script = BASE_DIR / "scripts" / "build_index.py"
    if venv_py.exists() and build_script.exists():
        import subprocess
        logger.info("Starting ChromaDB vector index update via virtual environment...")
        res = subprocess.run([str(venv_py), str(build_script)])
        if res.returncode == 0:
            return True
        else:
            logger.error(f"Vector index build exited with code {res.returncode}")
            return False
    else:
        logger.warning("Could not reindex: chromadb is not in current Python and venv/Scripts/python.exe was not found.")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Automated Government Scheme Fetcher & Categorizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Fetch 5 Agriculture schemes into data/agriculture/
  python scripts/fetch_schemes.py --category agriculture --count 5

  # Fetch 3 schemes from EVERY category
  python scripts/fetch_schemes.py --category all --count 3

  # Fetch a specific scheme by slug
  python scripts/fetch_schemes.py --slug pm-kisan

  # Search and fetch by custom query
  python scripts/fetch_schemes.py --query "solar subsidy" --count 3

  # List all available categories
  python scripts/fetch_schemes.py --list-categories
""",
    )

    parser.add_argument(
        "-c",
        "--category",
        help="Category key to fetch (e.g. 'agriculture', 'business', 'education', 'women', 'all')",
    )
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=5,
        help="Number of schemes to fetch per category (default: 5)",
    )
    parser.add_argument(
        "--slug",
        help="Fetch a single scheme directly by slug (e.g. 'pm-kisan', 'pmegp')",
    )
    parser.add_argument(
        "-q",
        "--query",
        help="Custom search query term (e.g. 'solar rooftop', 'drone subsidy')",
    )
    parser.add_argument(
        "--no-reindex",
        action="store_true",
        help="Skip rebuilding the ChromaDB vector index after fetching",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List all supported categories and folder mappings",
    )

    args = parser.parse_args()

    if args.list_categories:
        list_categories()
        return

    total_added = 0

    if args.slug:
        success = fetch_by_slug(args.slug)
        total_added = 1 if success else 0
    elif args.query:
        total_added = fetch_by_query(args.query, count=args.count)
    elif args.category:
        if args.category.lower() == "all":
            for cat_key in CATEGORIES_CONFIG:
                total_added += fetch_category_schemes(cat_key, count=args.count)
        else:
            total_added = fetch_category_schemes(args.category, count=args.count)
    else:
        # Default: list categories or show interactive prompt
        print("\nNo fetch mode specified. Showing available categories:")
        list_categories()
        print("Run with --help to see all options or provide --category <name>.")
        return

    # Auto-Reindex ChromaDB
    if total_added > 0 and not args.no_reindex:
        print("\n" + "=" * 60)
        logger.info("Rebuilding ChromaDB vector index with newly fetched schemes...")
        try:
            trigger_rebuild_index()
            logger.info("ChromaDB vector store is fully up to date!")
        except Exception as e:
            logger.error(f"Failed to rebuild index: {e}")
        print("=" * 60)
    elif total_added == 0:
        logger.info("No new schemes were added (already up-to-date).")


if __name__ == "__main__":
    main()
