# Design: Rename `vergil-docker` → `vergil-containers`

- **Issue:** [#328](https://github.com/vergil-project/vergil-docker/issues/328)
- **Date:** 2026-06-02
- **Status:** Approved (design)

## Intent

Rename the repository from `vergil-docker` to **`vergil-containers`** to decouple
the project's identity from Docker specifically. Docker is the image format in use
today, but this project is fundamentally a *container* mechanism — it already prefers
the open-source, Docker-compatible runtimes (nerdctl/Lima, with Docker as a fallback).
Naming the repository for the container concept rather than for one implementation
avoids permanent coupling to Docker should a better option emerge. The name fits the
sibling-repo pattern: `vergil-tooling`, `vergil-claude-plugin`, `vergil-project`.

This effort is the **rename plus live-reference updates only**. It deliberately does
not change terminology, directory names, or image identifiers.

## Why this is low-risk

Dependencies on this repository are almost entirely *indirect*: consumers use the
published images, not the repository itself. Image paths use the stable user namespace
`ghcr.io/vergil-project/{dev|prod}-{lang}`, which is unaffected by a repository rename.
The rename is therefore largely a documentation/reference update.

## Scope

### In scope — live/canonical references to update (single PR)

- `README.md` — H1 title, the Architecture GitHub Pages link, the GHCR
  "Select `vergil-docker`" setup step.
- `docs/site/mkdocs.yml` — `site_name` ("Vergil Docker" → "Vergil Containers"),
  `repo_url`, `repo_name`.
- `CLAUDE.md` — project-name mentions, the images-doc Pages link, the GHCR
  per-package setup step.
- Canonical-source header comments in all six `docker/*/Dockerfile.template`
  files (`base`, `python`, `java`, `go`, `ruby`, `rust`) and `docker/build.sh`
  (including its "Managed by vergil-docker" line).
- The two inbound GitHub Pages links (`README.md:123`, `CLAUDE.md:197`).

### Explicitly out of scope (candidate follow-ups)

- Docker → container **terminology sweep** in prose (e.g. `mkdocs.yml`
  `site_description`, body copy). Left as-is for this effort.
- Renaming the `docker/` **directory**.
- Changing **image prefixes** (`dev-`/`prod-`).
- Renaming the `cd-docker-publish.yml` **workflow file**.

### Explicitly unchanged (and why)

- **GHCR image paths** — `ghcr.io/vergil-project/{dev|prod}-{lang}` use the stable
  user namespace. This is the core reason downstream consumers are unaffected.
- **Historical records** — `CHANGELOG.md`, `releases/*`, dated `docs/plans/*` and
  `docs/specs/*`, and `paad/*` review files. These are point-in-time artifacts that
  were accurate when written; GitHub's automatic redirect keeps their github.com
  links working.

## Cross-repo coordination

The rename PR is repo-local. Live references in sibling repositories are tracked via
**follow-up issues** (not edited in this PR). GitHub's automatic old→new redirect
covers github.com links during the interim.

Inventory of **live** external references (historical files in those repos are left
alone, consistent with the in-repo policy):

- **`vergil-tooling`**: `CLAUDE.md`, `docs/site/docs/guides/releasing.md`,
  `docs/site/docs/guides/ci-architecture.md`.
- **`vergil-claude-plugin`**: `README.md`, `docs/development/skills-architecture.md`.

## Rollout order

The order matters to avoid transient 404s (new references must resolve immediately).

1. **Rename the repository on GitHub** — an admin action performed by a human via
   repository settings (not available through `vrg-gh`, which only permits
   `repo list`/`repo view`). GitHub auto-creates the old→new redirect and Pages
   republishes at `https://vergil-project.github.io/vergil-containers/`.
2. **Verify GHCR package write-access survived the rename.** Each `dev-`/`prod-`
   package grants Write to this repository. The repository ID is preserved across a
   rename, so the grant should persist — but this is the one real operational risk,
   so confirm it: check a package's *Manage Actions access*, or watch the next
   `dev-` publish succeed.
3. **Land the reference-update PR** on the renamed repository.
4. **Open coordinated follow-up issues** in `vergil-tooling` and
   `vergil-claude-plugin`.
5. **Update local clone remotes** (`vrg-git remote set-url`) — optional; the GitHub
   redirect keeps the old URL working.

## GitHub Pages URL

The Pages docs URL moves from `vergil-project.github.io/vergil-docker/` to
`.../vergil-containers/`. This change is accepted: the repo-level redirect handles
github.com links, and the inbound Pages links are few and internal (updated in the
PR). Preserving the old Pages path is not pursued.

## Verification

- `vrg-container-run -- vrg-validate` is green; CI is green on the PR.
- The docs site builds and serves at the new Pages URL.
- A `dev-` image publish succeeds, proving GHCR write-access remained intact after
  the rename.

## Deliverables

- This committed design spec.
- The tracking issue (#328), updated to link this spec.
- A reference-update PR (created during implementation, after the repo rename).
