# Christopher G. Connell — academic website

This public repository contains the Quarto source for
[https://chris-connell.github.io](https://chris-connell.github.io).

## Initial activation

1. Visit **Settings → Pages** in this GitHub repository.
2. Under **Build and deployment**, select **GitHub Actions** as the source.
3. In **Actions**, open **Publish academic website** and choose **Run workflow**
   if a push has not already deployed the website.
4. Open https://chris-connell.github.io after the workflow succeeds.

The workflow renders Quarto, updates curated bibliographic records from public
metadata services, and deploys the site. It runs on pushes and daily.

## Editing content

Edit the *.qmd pages directly in GitHub or locally; every push to main
rebuilds the website. Use 'quarto preview' to preview changes locally.

## Publications

- 'publications/curated.json': reviewed publications with stable citation keys.
- 'publications/papers.bib': generated downloadable BibTeX.
- 'publications/papers.json': generated structured list.
- 'publications/_list.qmd': generated Quarto publication listing.
- 'publications/candidates.json': potential new arXiv works for manual review.
- 'scripts/sync_publications.py': standard-library Python metadata updater.

New arXiv search results are **not** automatically added to the public listing
until authorship is verified, since namesake researchers exist. Reviewed works
can be added to 'curated.json', after which their metadata is kept updated.
Crossref DOI matches must have the expected exact normalized title and a
Connell author match. Manual details remain the fallback when API calls fail.

This repository intentionally has **no blanket content license**.
Individual research papers may have separate publisher rights.
