#!/usr/bin/env python3
"""Refresh a curated scholarly bibliography without silently adding namesakes.

Inputs: publications/curated.json, containing reviewed arXiv IDs and DOI records.
Outputs: papers.json, papers.bib, _list.qmd, and candidates.json.

Network errors never replace the reviewed metadata with empty data.
New arXiv hits remain review candidates until curated.json is amended.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
PUB = ROOT / "publications"
ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom",
        "ax": "http://arxiv.org/schemas/atom"}
USER_AGENT = "ConnellAcademicWeb/1.0 (mailto:connell@iu.edu)"


def get(url: str, timeout: int = 18) -> bytes | None:
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT,
                                    "Accept": "application/json, application/atom+xml"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        print(f"Metadata fetch unavailable ({type(error).__name__}): {url}", file=sys.stderr)
        return None


def norm_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z0-9]+", "", text)


def normalized_id(text: str) -> str:
    return re.sub(r"v[0-9]+$", "", text.strip().rsplit("/abs/", 1)[-1])


def parse_arxiv(data: bytes | None) -> dict[str, dict]:
    if not data:
        return {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    records = {}
    for entry in root.findall("a:entry", ATOM):
        identifier = normalized_id(entry.findtext("a:id", default="", namespaces=ATOM))
        if not identifier:
            continue
        title = " ".join(entry.findtext("a:title", default="", namespaces=ATOM).split())
        authors = [a.findtext("a:name", default="", namespaces=ATOM)
                   for a in entry.findall("a:author", ATOM)]
        records[identifier] = {
            "title": title,
            "authors": [a for a in authors if a],
            "arxiv_id": identifier,
            "updated": entry.findtext("a:updated", default="", namespaces=ATOM),
            "year": int(entry.findtext("a:published", default="0000", namespaces=ATOM)[:4] or 0),
            "doi": entry.findtext("ax:doi", default="", namespaces=ATOM).strip(),
            "journal_ref": entry.findtext("ax:journal_ref", default="", namespaces=ATOM).strip(),
        }
    return records


def arxiv_by_ids(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    url = ARXIV_API + "?" + urlencode({"id_list": ",".join(ids), "max_results": len(ids) + 5})
    return parse_arxiv(get(url))


def doi_metadata(doi: str, expected_title: str) -> dict:
    url = "https://api.crossref.org/works/" + quote(doi, safe="/")
    raw = get(url)
    if not raw:
        return {}
    try:
        work = json.loads(raw).get("message", {})
        title = (work.get("title") or [""])[0]
        if SequenceMatcher(None, norm_title(title), norm_title(expected_title)).ratio() < 0.95:
            return {}
        authors = work.get("author") or []
        if not any("connell" in (a.get("family") or "").lower() for a in authors):
            return {}
        result = {"doi": work.get("DOI", doi), "journal": (work.get("container-title") or [""])[0]}
        for key in ("volume", "issue", "page"):
            if work.get(key):
                result[key] = str(work[key])
        date = work.get("published-print") or work.get("published") or work.get("published-online")
        if date and date.get("date-parts"):
            result["year"] = int(date["date-parts"][0][0])
        return result
    except (ValueError, TypeError, IndexError, KeyError):
        return {}


def crossref_title_lookup(title: str) -> dict:
    # Strictly title- and author-matched; never trust the first search result alone.
    params = urlencode({"query.title": title, "rows": 3,
                        "select": "DOI,title,author,container-title,published,volume,issue,page"})
    raw = get("https://api.crossref.org/works?" + params)
    if not raw:
        return {}
    try:
        items = json.loads(raw).get("message", {}).get("items", [])
        want = norm_title(title)
        for item in items:
            found = norm_title((item.get("title") or [""])[0])
            authors = item.get("author") or []
            if found == want and any((a.get("family") or "").lower() == "connell" for a in authors):
                return doi_metadata(item["DOI"], title)
    except (ValueError, TypeError, IndexError, KeyError):
        pass
    return {}


def bib_value(value: object) -> str:
    # Preserve TeX math in titles; outer braces protect capitalization.
    return "{" + str(value).replace("\n", " ").strip() + "}"


def bib_entry(p: dict) -> str:
    article = bool(p.get("journal"))
    fields = [
        ("title", p["title"]),
        ("author", " and ".join(p["authors"])),
        ("year", p["year"]),
    ]
    for name in ("journal", "volume", "issue", "page", "doi"):
        val = p.get(name)
        if val:
            fields.append(("number" if name == "issue" else "pages" if name == "page" else name, val))
    if p.get("arxiv_id"):
        fields.extend([("eprint", p["arxiv_id"]),
                       ("archivePrefix", "arXiv"),
                       ("url", "https://arxiv.org/abs/" + p["arxiv_id"])])
    elif p.get("doi"):
        fields.append(("url", "https://doi.org/" + p["doi"]))
    out = [f"@{'article' if article else 'misc'}{{{p['key']},"]
    out.extend(f"  {k} = {bib_value(v)}," for k, v in fields)
    out.append("}")
    return "\n".join(out)


def render_markdown(papers):
    """Render only the manually verified bibliography for Quarto."""
    lines = ["<!-- Generated from publications/connell.bib; do not edit. -->", ""]
    is_book = lambda p: p.get("type") in {
        "book", "inbook", "incollection", "inproceedings", "proceedings"}
    categories = [
        ("Journal articles", [p for p in papers if p.get("journal")]),
        ("Books, chapters and proceedings",
         [p for p in papers if not p.get("journal") and is_book(p)]),
        ("Preprints and other works",
         [p for p in papers if not p.get("journal") and not is_book(p)]),
    ]
    for heading, entries in categories:
        if not entries:
            continue
        lines.extend(["## " + heading, ""])
        for p in entries:
            title = html.escape(p.get("title") or "Untitled work")
            authors = html.escape(", ".join(p.get("authors", [])))
            venue = html.escape(p.get("journal") or p.get("booktitle") or
                                ("arXiv preprint" if p.get("arxiv_id")
                                 else p.get("type", "misc").replace("_", " ").capitalize()))
            links = []
            if p.get("doi"):
                links.append(f'[DOI](https://doi.org/{quote(p["doi"], safe="/")})')
            if p.get("arxiv_id"):
                links.append(f'[arXiv](https://arxiv.org/abs/{p["arxiv_id"]})')
                links.append(f'[PDF](https://arxiv.org/pdf/{p["arxiv_id"]})')
            lines.extend([
                "::: {.publication-item}",
                f'<div class="pub-title">{title}</div>',
                f'<div class="pub-authors">{authors}</div>',
                f'<div class="pub-details">{venue} · {p.get("year") or "n.d."}</div>',
                " · ".join(links),
                ":::",
                "",
            ])
    return "\n".join(lines)


def discover_candidates(tracked: set[str]) -> list[dict]:
    # "Connell" matches unrelated researchers; deliberately do not publish new
    # hits automatically until a unique ORCID has been explicitly confirmed.
    params = urlencode({"search_query": '(au:"Chris Connell" OR au:"Christopher Connell")',
                        "start": 0, "max_results": 100,
                        "sortBy": "submittedDate", "sortOrder": "descending"})
    parsed = parse_arxiv(get(ARXIV_API + "?" + params))
    result = []
    for identifier, paper in parsed.items():
        if identifier in tracked:
            continue
        if not any(a.lower() in ("chris connell", "christopher connell")
                   for a in paper.get("authors", [])):
            continue
        result.append({k: paper.get(k) for k in ("arxiv_id", "title", "authors", "year")})
    return sorted(result, key=lambda p: (p["year"], p["arxiv_id"]), reverse=True)


def write_if_changed(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


# The manually checked bibliography is connell.bib.
# papers.bib is a generated union of reviewed records and discovery candidates.
import argparse
import hashlib
import os
import bibtexparser
from collections import Counter


def read_bib(content):
    reader = bibtexparser.bparser.BibTexParser(common_strings=True)
    reader.ignore_nonstandard_types = False
    parsed = bibtexparser.loads(content, parser=reader)
    if not parsed.entries:
        raise ValueError("No valid entries in connell.bib")
    keys = [e["ID"] for e in parsed.entries]
    if len(keys) != len(set(keys)):
        raise ValueError("Repeated citation keys in connell.bib")
    return parsed.entries


def checked_record(e):
    f = {k.lower(): v for k, v in e.items()}
    found = re.search(r"\b(?:18|19|20)\d{2}\b", f.get("year") or f.get("date") or "")
    names = re.split(r"\s+and\s+", f.get("author", f.get("editor", "")), flags=re.I)
    authors = []
    for name in names:
        name = name.strip()
        if name.count(",") == 1:
            last, first = name.split(",", 1)
            name = first.strip() + " " + last.strip()
        if name:
            authors.append(name)
    return dict(key=f["id"], title=f.get("title", ""),
                authors=authors, year=int(found.group()) if found else 0,
                journal=f.get("journal") or f.get("journaltitle") or "",
                booktitle=f.get("booktitle", ""),
                doi=clean_doi(f.get("doi", "")),
                arxiv_id=clean_arxiv(f.get("eprint", "") or f.get("arxivid", "") or f.get("url", "")),
                sources=["verified"], url=f.get("url", ""),
                volume=f.get("volume", ""), issue=f.get("number", ""),
                page=f.get("pages", ""), type=f.get("entrytype", "misc"))


def clean_doi(s):
    return re.sub(r"(?i)^https?://(?:dx\.)?doi.org/", "", str(s or "").strip()).lower()


def clean_arxiv(s):
    s = str(s or "").strip().removeprefix("arXiv:")
    s = s.split("arxiv.org/abs/")[-1].split("arxiv.org/pdf/")[-1]
    s = re.sub(r"v\d+$", "", s).removesuffix(".pdf")
    return s if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})", s) else ""


def connell_author(p):
    return any(re.search(r"\b(?:Chris|Christopher|C\.?\s*G\.?)\b[^,]*\bConnell\b|"
                         r"\bConnell,\s*(?:Chris|Christopher|C\.?\s*G\.?)",
                         n, re.I) for n in p.get("authors", []))


def arxiv_source(queries):
    result = []
    for query in queries:
        start, limit = 0, 1000
        while start < limit:
            url = ARXIV_API + "?" + urlencode({"search_query": query, "start": start,
                "max_results": min(100, limit-start), "sortBy": "submittedDate",
                "sortOrder": "descending"})
            raw = get(url)
            if not raw:
                break
            try:
                root = ET.fromstring(raw)
                found = parse_arxiv(raw)
            except (ET.ParseError, ValueError):
                break
            for p in found.values():
                p["journal"] = p.get("journal_ref", "")
                p["doi"] = clean_doi(p.get("doi", ""))
                p["sources"] = ["arXiv"]
                if connell_author(p):
                    result.append(p)
            num = len(root.findall("{http://www.w3.org/2005/Atom}entry"))
            total = int(root.findtext("{http://a9.com/-/spec/opensearch/1.1/}totalResults") or 0)
            start += num
            if num == 0 or start >= total:
                break
            time.sleep(3)
    return result


def crossref_source(names):
    result = []
    for name in names:
        for offset in (0, 100, 200):
            url = "https://api.crossref.org/works?" + urlencode({"query.author": name,
                "rows": 100, "offset": offset, "select":
                "DOI,title,author,container-title,published,volume,issue,page,type,URL"})
            raw = get(url)
            if not raw:
                break
            try:
                items = json.loads(raw)["message"]["items"]
            except (KeyError, ValueError, TypeError):
                break
            for r in items:
                dates = (r.get("published") or {}).get("date-parts") or []
                authors = [(a.get("given", "") + " " + a.get("family", "")).strip()
                           for a in r.get("author", [])]
                p = dict(title=(r.get("title") or [""])[0], authors=authors,
                         year=int(dates[0][0]) if dates and dates[0] else 0,
                         journal=(r.get("container-title") or [""])[0],
                         doi=clean_doi(r.get("DOI", "")), volume=r.get("volume", ""),
                         issue=r.get("issue", ""), page=r.get("page", ""),
                         sources=["Crossref"])
                if p["title"] and connell_author(p):
                    result.append(p)
            if len(items) < 100:
                break
    return result


def dblp_source(pid):
    if not re.fullmatch("[a-zA-Z0-9/_-]+", pid or ""):
        return []
    raw = get("https://dblp.org/pid/" + pid + ".bib")
    if not raw:
        return []
    try:
        entries = read_bib(raw.decode("utf-8-sig"))
        result = [checked_record(e) for e in entries]
    except (ValueError, UnicodeError):
        return []
    for p in result:
        p["sources"] = ["dblp"]
    return [p for p in result if connell_author(p)]


def openalex_source(checked, configured_ids):
    ids = {x for x in configured_ids if re.fullmatch("A[0-9]+", x)}
    if not ids:
        # Require two independently verified DOIs supporting the same author ID.
        support = Counter()
        for doi in list(dict.fromkeys(p["doi"] for p in checked if p.get("doi")))[:12]:
            raw = get("https://api.openalex.org/works/doi:" + quote(doi, safe="/"))
            if not raw:
                continue
            try:
                r = json.loads(raw)
                for a in r.get("authorships", []):
                    name = a.get("author", {}).get("display_name", "")
                    aid = a.get("author", {}).get("id", "").rsplit("/", 1)[-1]
                    if re.search(r"\bConnell\b", name, re.I) and re.fullmatch("A[0-9]+", aid):
                        support[aid] += 1
            except (ValueError, TypeError):
                continue
        ids = {aid for aid, num in support.items() if num >= 2}
    result = []
    for aid in sorted(ids):
        for page in range(1, 6):
            params = {"filter": "author.id:" + aid, "page": page, "per_page": 100}
            if os.environ.get("OPENALEX_API_KEY"):
                params["api_key"] = os.environ["OPENALEX_API_KEY"]
            raw = get("https://api.openalex.org/works?" + urlencode(params))
            if not raw:
                break
            try:
                docs = json.loads(raw)["results"]
            except (ValueError, KeyError):
                break
            for r in docs:
                loc = r.get("primary_location") or {}
                p = dict(title=r.get("title") or "",
                         authors=[a.get("author", {}).get("display_name", "")
                                  for a in r.get("authorships", [])],
                         year=r.get("publication_year") or 0,
                         doi=clean_doi(r.get("doi", "")),
                         journal=(loc.get("source") or {}).get("display_name", ""),
                         url=loc.get("landing_page_url", ""), sources=["OpenAlex"])
                if p["title"] and connell_author(p):
                    result.append(p)
            if len(docs) < 100:
                break
    return result


def merge_duplicates(papers):
    output, ids, titles = [], {}, {}
    for p in papers:
        title = norm_title(p.get("title", ""))
        if not title:
            continue
        possible = set()
        for field, cleaner in (("doi", clean_doi), ("arxiv_id", clean_arxiv)):
            value = cleaner(p.get(field, ""))
            if value and (field, value) in ids:
                possible.add(ids[(field, value)])
        if title in titles:
            possible.add(titles[title])
        if len(possible) > 1:
            print("Ambiguous metadata merge:", p["title"], file=sys.stderr)
            continue
        if possible:
            index = possible.pop()
            existing = output[index]
            for key, val in p.items():
                if key == "sources":
                    existing[key] = sorted(set(existing.get(key, []) + (val or [])))
                elif val and not existing.get(key):
                    existing[key] = val
        else:
            index = len(output)
            output.append(dict(p))
            existing = output[index]
        titles[title] = index
        for field, cleaner in (("doi", clean_doi), ("arxiv_id", clean_arxiv)):
            value = cleaner(p.get(field, "") or existing.get(field, ""))
            if value:
                ids[(field, value)] = index
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()
    checked_bib = (PUB / "connell.bib").read_text("utf-8")
    manual = read_bib(checked_bib)
    checked = [checked_record(p) for p in manual]
    checked.sort(key=lambda p: (-p["year"], p["title"].lower()))
    write_if_changed(PUB / "papers.json", json.dumps(checked, ensure_ascii=False, indent=2) + "\n")
    write_if_changed(PUB / "_list.qmd", render_markdown(checked))
    cache_file = PUB / "discovered.json"
    cache = json.loads(cache_file.read_text("utf-8")) if cache_file.exists() else []
    if args.discover:
        config = json.loads((PUB / "sources.json").read_text("utf-8"))
        new = arxiv_source(config.get("arxiv_queries", []))
        new += crossref_source(config.get("crossref_author_queries", []))
        new += dblp_source(config.get("dblp_pid", ""))
        new += openalex_source(checked, config.get("openalex_author_ids", []))
        cache = merge_duplicates(cache + new)
        write_if_changed(cache_file, json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
    union = merge_duplicates(checked + cache)
    known_titles = {norm_title(p["title"]) for p in checked}
    known_dois = {p["doi"] for p in checked if p["doi"]}
    known_arxiv = {p["arxiv_id"] for p in checked if p["arxiv_id"]}
    candidates = []
    combined_bib = ["% GENERATED: Do not edit papers.bib.",
                    "% Reviewed and displayed bibliography is connell.bib.",
                    "% The candidate section is unverified and may contain namesakes.",
                    "", checked_bib.rstrip(), "", "% UNREVIEWED CANDIDATES", ""]
    for p in sorted(union, key=lambda item: (-int(item.get("year", 0)), item["title"].lower())):
        if norm_title(p["title"]) in known_titles or clean_doi(p.get("doi", "")) in known_dois or clean_arxiv(p.get("arxiv_id", "")) in known_arxiv:
            continue
        id_text = clean_doi(p.get("doi", "")) or clean_arxiv(p.get("arxiv_id", "")) or norm_title(p["title"])
        p["key"] = "CandidateConnell" + str(p.get("year") or "XXXX") + "_" + hashlib.sha1(id_text.encode()).hexdigest()[:10]
        combined_bib += ["% Unreviewed; sources: " + ", ".join(p.get("sources", [])), bib_entry(p), ""]
        candidates.append(p)
    write_if_changed(PUB / "papers.bib", "\n".join(combined_bib).rstrip() + "\n")
    write_if_changed(PUB / "candidates.json",
                     json.dumps(candidates, ensure_ascii=False, indent=2) + "\n")
    print(f"Verified {len(checked)}, total collected {len(union)}, candidates {len(candidates)}")


if __name__ == "__main__":
    main()
