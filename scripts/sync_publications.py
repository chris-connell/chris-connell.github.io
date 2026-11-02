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


def render_markdown(papers: list[dict]) -> str:
    lines = ["<!-- Generated by scripts/sync_publications.py; edit curated.json instead. -->", ""]
    for heading, subset in [
        ("Journal publications", [p for p in papers if p.get("journal")]),
        ("Preprints and other works", [p for p in papers if not p.get("journal")]),
    ]:
        lines.extend(["## " + heading, ""])
        if not subset:
            lines.extend(["No entries yet.", ""])
        for p in subset:
            title = html.escape(p["title"])
            authors = html.escape(", ".join(p["authors"]))
            venue = html.escape(p.get("journal") or "arXiv preprint")
            links = []
            if p.get("doi"):
                links.append(f'[Journal / DOI](https://doi.org/{quote(p["doi"], safe="/")})')
            if p.get("arxiv_id"):
                links.append(f'[arXiv](https://arxiv.org/abs/{p["arxiv_id"]})')
                links.append(f'[PDF](https://arxiv.org/pdf/{p["arxiv_id"]})')
            lines.extend([
                "::: {.publication-item}",
                f'<div class="pub-title">{title}</div>',
                f'<div class="pub-authors">{authors}</div>',
                f'<div class="pub-details">{venue} · {p["year"]}</div>',
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


def main() -> None:
    seeds = json.loads((PUB / "curated.json").read_text(encoding="utf-8"))
    if len({s["key"] for s in seeds}) != len(seeds):
        raise ValueError("Duplicate BibTeX keys in curated.json")
    if len({s["arxiv_id"] for s in seeds if s.get("arxiv_id")}) != len([s for s in seeds if s.get("arxiv_id")]):
        raise ValueError("Duplicate arXiv IDs in curated.json")

    arxiv = arxiv_by_ids([s["arxiv_id"] for s in seeds if s.get("arxiv_id")])
    merged = []
    for seed in seeds:
        p = seed.copy()
        current = arxiv.get(seed.get("arxiv_id", ""), {})
        if current:
            # Do not change citation key, author attribution, curated journal or year.
            p["arxiv_updated"] = current.get("updated", "")
            if not p.get("doi") and current.get("doi"):
                p["doi"] = current["doi"]
        if p.get("doi"):
            p.update(doi_metadata(p["doi"], p["title"]))
        elif not p.get("journal"):
            # A strict title match allows a reviewed preprint to transition to a journal article.
            p.update(crossref_title_lookup(p["title"]))
        merged.append(p)

    merged.sort(key=lambda p: (-int(p["year"]), p["title"].casefold()))
    bib = "% Generated bibliography. Edit publications/curated.json, not this file.\n\n"
    bib += "\n\n".join(bib_entry(p) for p in merged) + "\n"
    changed = []
    outputs = {
        "papers.bib": bib,
        "papers.json": json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        "_list.qmd": render_markdown(merged),
    }
    for name, contents in outputs.items():
        if write_if_changed(PUB / name, contents):
            changed.append(name)

    # A failed discovery fetch must not overwrite an existing candidate review file.
    candidates = discover_candidates({s["arxiv_id"] for s in seeds if s.get("arxiv_id")})
    if candidates:
        text = json.dumps(candidates, indent=2, ensure_ascii=False) + "\n"
        if write_if_changed(PUB / "candidates.json", text):
            changed.append("candidates.json")

    print(f"Curated publications: {len(merged)}; updated files: {', '.join(changed) or 'none'}")


if __name__ == "__main__":
    main()
