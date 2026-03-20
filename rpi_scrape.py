"""
RPI Course Catalog Scraper
===========================
Scrapes course data from catalog.rpi.edu (Modern Campus/Acalog system).
Outputs structured JSON with course name, number, description, credits,
and parsed prerequisites.
"""

import argparse
import json
import re
import time
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Both domains point to the same Acalog system:
#   catalog.rpi.edu            – catoid=33, navoid=891 -> 2025-2026
# To find the latest catalog: visit catalog.rpi.edu, select the newest year
# from the dropdown, then grab catoid & navoid from the Courses page URL.
BASE_URL = "https://catalog.rpi.edu/"

# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class Course:
    course_id: str
    prefix: str
    number: str
    title: str
    description: str = ""
    credit_hours: str = ""
    prerequisites_raw: str = ""
    prerequisites: list = field(default_factory=list)
    prerequisite_logic: Optional[dict] = None
    when_offered: str = ""
    catalog_url: str = ""

# ── Prerequisite parser ─────────────────────────────────────────────────────

COURSE_CODE_RE = re.compile(r"\b([A-Z]{3,4})\s+(\d{4}(?:\.\d{1,2})?)\b")

def _strip_formatting(text: str) -> str:
    text = re.sub(r"_{2,}", "", text)
    text = re.sub(r"\*{2,}", "", text) 
    return text.strip()

def parse_prereq_logic(text: str):
    if not text:
        return None

    text = _strip_formatting(text)
    text = re.sub(r"\s+", " ", text).strip()

    text = re.sub(r"^(?:one of|any of|either|completion of)\s+", "", text, flags=re.IGNORECASE)

    or_parts = re.split(r"\s*,?\s+or\s+", text, flags=re.IGNORECASE)

    or_items = []
    for or_part in or_parts:
        and_parts = re.split(r"\s*(?:,?\s+and\s+|,\s+)", or_part, flags=re.IGNORECASE)

        and_items = []
        for and_part in and_parts:
            codes = COURSE_CODE_RE.findall(and_part)
            for code in codes:
                and_items.append(f"{code[0]} {code[1]}")

        if len(and_items) == 0:
            continue
        elif len(and_items) == 1:
            or_items.append(and_items[0])
        else:
            or_items.append({"type": "AND", "items": and_items})

    if len(or_items) == 0:
        return None
    elif len(or_items) == 1:
        return or_items[0]
    else:
        return {"type": "OR", "items": or_items}


def parse_prereqs(text: str) -> dict:
    if not text:
        return {"prerequisites": [], "prerequisite_logic": None, "raw": ""}

    text_clean = _strip_formatting(text)

    coreq_split = re.split(r"[Cc]orequisite[s]?\s*:?\s*", text_clean, maxsplit=1)

    prereq_text = coreq_split[0]
    coreq_text = coreq_split[1] if len(coreq_split) > 1 else ""

    prereqs = [f"{m[0]} {m[1]}" for m in COURSE_CODE_RE.findall(prereq_text)]
    coreqs = [f"{m[0]} {m[1]}" for m in COURSE_CODE_RE.findall(coreq_text)]
    all_prereqs = prereqs + coreqs

    seen = set()
    unique_prereqs = []
    for p in all_prereqs:
        if p not in seen:
            seen.add(p)
            unique_prereqs.append(p)

    logic = parse_prereq_logic(prereq_text)
    if coreqs:
        coreq_logic = parse_prereq_logic(coreq_text)
        if logic and coreq_logic:
            logic = {"type": "AND", "items": [logic, coreq_logic]}
        elif coreq_logic:
            logic = coreq_logic

    return {
        "prerequisites": unique_prereqs,
        "prerequisite_logic": logic,
        "raw": text_clean,
    }

# ── Scraper ─────────────────────────────────────────────────────────────────

class RPICatalogScraper:
    def __init__(self, catoid: int = 33, navoid: int = 891,
                 delay: float = 1.0, base_url: str = BASE_URL):
        self.catoid = catoid
        self.navoid = navoid
        self.delay = delay
        self.base_url = base_url.rstrip("/") + "/"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "RPI-Course-Scraper/1.0 (student project)"
        })

    def _get(self, url: str) -> BeautifulSoup:
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")


    def get_all_prefixes(self) -> list[str]:

        print("  Discovering all department prefixes...")
        prefixes = set()
        page = 1

        while True:
            url = (
                f"{self.base_url}content.php?catoid={self.catoid}"
                f"&catoid={self.catoid}&navoid={self.navoid}"
                f"&filter%5Bitem_type%5D=3"
                f"&filter%5Bonly_active%5D=1"
                f"&filter%5B3%5D=1"
                f"&filter%5Bcpage%5D={page}"
            )

            print(f"    page {page}...", end=" ", flush=True)
            soup = self._get(url)

            course_anchors = soup.find_all(
                "a", href=re.compile(r"preview_course_nopop\.php\?catoid=\d+&coid=\d+")
            )

            if not course_anchors:
                print("done.")
                break

            for a in course_anchors:
                text = a.get_text(strip=True)
                match = re.match(r"([A-Z]{3,4})\s+\d{4}", text)
                if match:
                    prefixes.add(match.group(1))

            print(f"{len(prefixes)} prefixes so far.")

            page_links = soup.find_all("a", href=re.compile(rf"filter%5Bcpage%5D=\d+"))
            has_next = any(
                f"filter%5Bcpage%5D={page + 1}" in (a.get("href", ""))
                for a in page_links
            )

            if has_next:
                page += 1
            else:
                break

        result = sorted(prefixes)
        print(f"  Found {len(result)} departments: {', '.join(result)}")
        return result

    # ── Step 1: Collect course links from the paginated listing ──

    def get_course_links(self, prefix: Optional[str] = None) -> list[dict]:
        links = []
        page = 1
        found_prefix = False

        while True:
            url = (
                f"{self.base_url}content.php?catoid={self.catoid}"
                f"&catoid={self.catoid}&navoid={self.navoid}"
                f"&filter%5Bitem_type%5D=3"
                f"&filter%5Bonly_active%5D=1"
                f"&filter%5B3%5D=1"
                f"&filter%5Bcpage%5D={page}"
            )

            label = f"page {page}" + (f" [{prefix.upper()}]" if prefix else " [all]")
            print(f"  Fetching listing {label}...", end=" ", flush=True)
            soup = self._get(url)

            course_anchors = soup.find_all(
                "a", href=re.compile(r"preview_course_nopop\.php\?catoid=\d+&coid=\d+")
            )

            if not course_anchors:
                print("no courses found — done with listings.")
                break

            page_courses = []
            for a in course_anchors:
                text = a.get_text(strip=True)
                href = urljoin(self.base_url, a["href"])
                match = re.match(r"([A-Z]{3,4})\s+(\d{4}(?:\.\d{1,2})?)\s*-\s*(.+)", text)
                if match:
                    page_courses.append({
                        "prefix": match.group(1),
                        "number": match.group(2),
                        "title": match.group(3).strip(),
                        "url": href,
                    })

            if prefix:
                target = prefix.upper()
                page_prefixes = {c["prefix"] for c in page_courses}

                if found_prefix and target not in page_prefixes:
                    print(f"past {target} alphabetically — stopping early.")
                    break

                if target not in page_prefixes and all(p < target for p in page_prefixes):
                    print(f"skipping (before {target}).")
                else:
                    count = 0
                    for c in page_courses:
                        if c["prefix"] == target:
                            found_prefix = True
                            links.append(c)
                            count += 1
                    print(f"found {count} courses.")
            else:
                links.extend(page_courses)
                print(f"found {len(page_courses)} courses.")

            page_links = soup.find_all("a", href=re.compile(rf"filter%5Bcpage%5D=\d+"))
            has_next = any(
                f"filter%5Bcpage%5D={page + 1}" in (a.get("href", ""))
                for a in page_links
            )

            if has_next:
                page += 1
            else:
                print(f"  No more pages after page {page}.")
                break

        print(f"\nTotal course links collected: {len(links)}")
        return links

    # ── Step 2: Scrape individual course detail pages ──

    def scrape_course_detail(self, url: str) -> dict:
        soup = self._get(url)

        result = {
            "description": "",
            "credit_hours": "",
            "prerequisites_raw": "",
            "prerequisites": [],
            "prerequisite_logic": None,
            "when_offered": "",
        }

        block = soup.find("td", class_="block_content")
        if not block:
            return result

        plain_hrs = [
            hr for hr in block.find_all("hr")
            if "navbar" not in (hr.get("class") or [])
        ]

        if len(plain_hrs) >= 2:
            content_parts = []
            node = plain_hrs[0].next_sibling
            while node and node != plain_hrs[1]:
                if hasattr(node, 'get_text'):
                    text = node.get_text(separator=" ")
                else:
                    text = str(node)
                text = text.strip()
                if text:
                    content_parts.append(text)
                node = node.next_sibling
            body_text = " ".join(content_parts)
        elif len(plain_hrs) == 1:
            content_parts = []
            node = plain_hrs[0].next_sibling
            while node:
                if hasattr(node, 'get_text'):
                    text = node.get_text(separator=" ")
                else:
                    text = str(node)
                text = text.strip()
                if text:
                    content_parts.append(text)
                node = node.next_sibling
            body_text = " ".join(content_parts)
        else:
            body_text = block.get_text(separator=" ")

        body_text = re.sub(r"\s+", " ", body_text).strip()

        desc_match = re.search(
            r"[A-Z]{3,4}\s+\d{4}(?:\.\d{1,2})?\s*-\s*.+?\s{2,}"
            r"(.*?)"
            r"(?=Prerequisites|Corequisites|When Offered|Credit Hours:)",
            body_text, re.IGNORECASE
        )
        if not desc_match:
            desc_match = re.search(
                r"(.*?)(?=Prerequisites|Corequisites|When Offered|Credit Hours:)",
                body_text, re.IGNORECASE
            )
        if desc_match:
            desc = desc_match.group(1).strip()
            desc = re.sub(r"^[A-Z]{3,4}\s+\d{4}(?:\.\d{1,2})?\s*-\s*.*?(?:---?|—)\s*", "", desc).strip()
            desc = re.sub(r"^[\s\*]+|[\s\*]+$", "", desc).strip()
            desc = re.sub(r"\s*Prerequisites?(?:/Corequisites?)?\s*:?\s*.*$", "", desc, flags=re.IGNORECASE).strip()
            result["description"] = desc

        prereq_match = re.search(
            r"Prerequisites?(?:/Corequisites?)?\s*:?\s*"
            r"(.*?)"
            r"(?=When Offered|Credit Hours:|Contact,?\s*Lecture|$)",
            body_text, re.IGNORECASE
        )
        if prereq_match:
            raw_prereqs = prereq_match.group(1).strip()
            parsed = parse_prereqs(raw_prereqs)
            result["prerequisites_raw"] = parsed["raw"]
            result["prerequisites"] = parsed["prerequisites"]
            result["prerequisite_logic"] = parsed["prerequisite_logic"]

        credit_match = re.search(r"Credit Hours:\s*(\S[^A-Z]*?)(?:\s{2,}|$)", body_text, re.IGNORECASE)
        if credit_match:
            val = credit_match.group(1).strip()
            val = re.split(r"(?:Contact|When Offered|Prerequisites|Back to)", val, maxsplit=1)[0]
            result["credit_hours"] = val.strip()

        offered_match = re.search(
            r"When Offered:\s*(.*?)(?=Credit Hours:|Contact,?\s*Lecture|Prerequisites|Graded:|$)",
            body_text, re.IGNORECASE
        )
        if offered_match:
            val = offered_match.group(1).strip()
            val = re.sub(r"\s*Graded\s*:.*$", "", val, flags=re.IGNORECASE).strip()
            result["when_offered"] = val

        return result


    def scrape_all(self, prefix: Optional[str] = None) -> list[Course]:
        """Run the full scrape: listing pages → detail pages → Course objects."""
        print(f"RPI Catalog Scraper (catoid={self.catoid})\n")
        print("Step 1/2: Collecting course links...")
        links = self.get_course_links(prefix=prefix)

        print(f"\nStep 2/2: Scraping {len(links)} course detail pages...")
        courses = []
        for i, link in enumerate(links, 1):
            print(f"  [{i}/{len(links)}] {link['prefix']} {link['number']} - {link['title']}")
            try:
                detail = self.scrape_course_detail(link["url"])
                course = Course(
                    course_id=f"{link['prefix']} {link['number']}",
                    prefix=link["prefix"],
                    number=link["number"],
                    title=link["title"],
                    description=detail["description"],
                    credit_hours=detail["credit_hours"],
                    prerequisites_raw=detail["prerequisites_raw"],
                    prerequisites=detail["prerequisites"],
                    prerequisite_logic=detail["prerequisite_logic"],
                    when_offered=detail["when_offered"],
                    catalog_url=link["url"],
                )
                courses.append(course)
            except Exception as e:
                print(f"    Error scraping: {e}")

        return courses

# ── CLI entry point ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scrape RPI course catalog")
    parser.add_argument("--catoid", type=int, default=33,
                        help="Catalog ID (default 33 = 2025-2026)")
    parser.add_argument("--navoid", type=int, default=891,
                        help="Navigation ID for Courses page (default 891)")
    parser.add_argument("--base-url", type=str, default="https://catalog.rpi.edu/",
                        help="Base URL of the catalog site")
    parser.add_argument("--prefix", type=str, nargs="+", default=None,
                        help="Department prefix to scrape (e.g. --prefix MATH CSCI PHYS). "
                             "Each gets its own JSON file in the output directory.")
    parser.add_argument("--all", action="store_true", dest="scrape_all",
                        help="Scrape every department, each into its own JSON file. "
                             "Skips departments that already have a JSON (use --rescrape to override).")
    parser.add_argument("--output-dir", type=str, default="data_scraping",
                        help="Output directory for JSON files (default: data_scraping/)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Delay between requests in seconds")
    parser.add_argument("--rescrape", action="store_true",
                        help="Re-scrape departments even if their JSON already exists")
    args = parser.parse_args()

    import os
    os.makedirs(args.output_dir, exist_ok=True)

    scraper = RPICatalogScraper(
        catoid=args.catoid,
        navoid=args.navoid,
        delay=args.delay,
        base_url=args.base_url,
    )

    if args.scrape_all:
        prefixes = scraper.get_all_prefixes()
    elif args.prefix:
        prefixes = [p.upper() for p in args.prefix]
    else:
        prefixes = None 

    if prefixes:
        all_courses = []
        scraped = 0
        skipped = 0

        for prefix in prefixes:
            output_path = os.path.join(args.output_dir, f"{prefix.lower()}_courses.json")

            if os.path.exists(output_path) and not args.rescrape:
                print(f"  Skipping {prefix} — {output_path} already exists (use --rescrape to overwrite)")
                skipped += 1
                continue

            print(f"Scraping {prefix}")

            courses = scraper.scrape_all(prefix=prefix)

            output = [asdict(c) for c in courses]
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            with_prereqs = sum(1 for c in courses if c.prerequisites)
            print(f"\n Saved {len(courses)} {prefix} courses to {output_path}")
            print(f"  {with_prereqs} with prerequisites, {len(courses) - with_prereqs} without")

            all_courses.extend(courses)
            scraped += 1

        print(f"Files in {args.output_dir}/")
    else:
        output_path = os.path.join(args.output_dir, "all_courses.json")

        if os.path.exists(output_path) and not args.rescrape:
            print(f"  Skipping — {output_path} already exists (use --rescrape to overwrite)")
            return

        courses = scraper.scrape_all()

        output = [asdict(c) for c in courses]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Saved {len(courses)} courses to {output_path}")

        with_prereqs = sum(1 for c in courses if c.prerequisites)
        print(f"  {with_prereqs} courses have parsed prerequisites")
        print(f"  {len(courses) - with_prereqs} courses have no prerequisites")

if __name__ == "__main__":
    main()