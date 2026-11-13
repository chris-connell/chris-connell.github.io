# Christopher G. Connell — Public Website

Public website: **https://chris-connell.github.io/**

This is the **public publishing repository**. It contains only generated website
files under `site/`, plus this README and the GitHub Pages deployment workflow.

The editable Quarto source, bibliography files, publication discovery data,
and Python scripts are maintained in a separate **private** repository:
[connell-website-source](https://github.com/chris-connell/connell-website-source)
(access is restricted).

Please do **not** edit generated HTML directly. Edit the private Quarto pages
and `publications/connell.bib` instead. Once a repository-scoped deploy key is
configured, a private GitHub Actions workflow builds the complete site and
commits only approved static output into the `site/` folder here. This public
repository then automatically deploys `site/` to GitHub Pages.

No BibTeX bibliography, review dataset or Python program is meant to be
distributed by this repository.

### Historical visibility

Older commits in this repository previously contained the Quarto source and
bibliographic files. Removing them from the current branch does not eliminate
the old Git history or copies that may have been downloaded. A separate
history-reset decision is necessary if you want to reduce the visibility of
those historical commits.
