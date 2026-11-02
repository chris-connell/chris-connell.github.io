# Christopher G. Connell — academic website

Website: https://chris-connell.github.io/

## Your two bibliographies

**publications/connell.bib** is manually checked and is the single source of
truth for the public-facing Publications page and verified BibTeX download.
You can paste a much larger BibTeX file into it. Committing changes to main
automatically rebuilds the publication listing; automated jobs do not edit
this file. You control the citation keys and bibliographic content.

**publications/papers.bib** is automatically generated from the entries in
connell.bib plus discovered records from scholarly databases. Do not edit
papers.bib by hand; every workflow run regenerates it. It contains
unverified candidates as well as the manually checked publications.

### Discovery sources

- arXiv: author searches covering multiple name variants, paginated
  beyond the most recent results (maximum 1,000 per query).
- Crossref: journal articles and DOI metadata from author searches.
- dblp: author-specific curated bibliography, profile 64/9215.
- OpenAlex: works linked to a candidate author ID supported by two
  independently verified publication DOIs, or IDs explicitly specified
  in publications/sources.json.

The synchronizer saves discoveries to publications/discovered.json and
writes unverified new papers to publications/candidates.json. Papers can be
accepted by copying and checking their BibTeX entries from papers.bib into
connell.bib. The website never attributes newly discovered records to you
without review. Identical DOI, arXiv ID, or normalized title records are
merged. Source outages do not empty the persistent discovery cache.

Optional future sources include zbMATH Open, especially valuable for older
mathematics publications. CiteSeer is not used at present.

### Important files

| File | Role |
| --- | --- |
| publications/connell.bib | Manually verified bibliography, website source |
| publications/papers.bib | Generated scholarly candidate collection |
| publications/discovered.json | Preserved source-search results |
| publications/candidates.json | Unreviewed discoveries |
| publications/papers.json | Generated structured verified bibliography |
| publications/_list.qmd | Generated publication list for Quarto |
| publications/sources.json | Search configuration and optional author IDs |
| scripts/sync_publications.py | Synchronization program |

The initial ten publications in connell.bib are a seed set only, and
should be expanded using your full verified publication list.

## Website publishing

GitHub Actions rebuilds the site on each push to main and runs a scholarly
discovery scan on a daily schedule or when manually started. GitHub Pages
should have GitHub Actions selected under Settings > Pages.

This repository does not contain a blanket license for its content.
