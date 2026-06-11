# GitHub owner settings — verification report & manual checklist

Date: 2026-06-10 · Repo: `akashguha9/sleeping-passenger-v1` · Owner: Akash Guha

## Verified read-only in Pass 2 (authenticated GitHub API via Claude Code's GitHub integration)

| Setting | State | Verdict |
| --- | --- | --- |
| Repository visibility | `private: true` | ✅ Verified |
| Default branch | `main` | ✅ Verified |
| Collaborators | exactly one: `akashguha9` (admin) — no stale collaborators, no outside collaborators | ✅ Verified |
| GitHub Pages | disabled (`has_pages: false`) | ✅ Verified |
| Wiki / Discussions | disabled | ✅ Verified |
| License posture | custom proprietary (`NOASSERTION` / All Rights Reserved) | ✅ Verified |

`gh` CLI is not available in this environment and the integration token
does not expose branch-protection, Actions-permission, deploy-key,
webhook, or secrets endpoints — those could **not** be verified
programmatically and must be checked in the GitHub UI below. Nothing was
mutated.

## Manual checklist (GitHub → repo → Settings)

Work top to bottom; every box should be checkable in under a minute.

### General
- [ ] Visibility stays **Private** (verified today; re-check after any transfer).
- [ ] Default branch is `main` (verified today).
- [ ] Template repository: off. Forking: leave off unless you need it (private-repo forks inherit your code into other namespaces).

### Branches → Branch protection on `main`
- [ ] Add a protection rule for `main`.
- [ ] Require status checks to pass: `backend pytest`, `safety floor`, `frontend vitest + typecheck + build`, `defensive gate`, `dep-audit` jobs.
- [ ] Require a pull request before merging — optional while you are the only committer; **mandatory the moment any collaborator exists**.
- [ ] Restrict who can push: only `akashguha9`.
- [ ] Require linear history (recommended: keeps the audit trail trivially readable).
- [ ] Do not allow force pushes or deletions.

### Actions → General
- [ ] Default workflow permissions: **Read repository contents** (workflows also pin this in-file, but the org/repo default is defense in depth).
- [ ] "Require approval for all external contributors" for fork PRs.
- [ ] Allowed actions: "Allow actions created by GitHub" + the pinned `gitleaks/gitleaks-action` SHA, or leave "Allow all" since every workflow is SHA-pinned and CI fails on any unpinned addition (`scripts/audit_github_actions_pinning.py`).

### Security
- [ ] Code security → Enable **Dependabot alerts**.
- [ ] Enable **Secret scanning** and **Push protection** (available on private repos under current GitHub plans; enable whatever your plan allows).
- [ ] Private vulnerability reporting: optional (single-owner repo).

### Access & credentials
- [ ] Collaborators: only `akashguha9` (verified today; re-check quarterly).
- [ ] Deploy keys: none expected — remove anything listed.
- [ ] Webhooks: none expected — remove anything listed.
- [ ] Installed GitHub Apps: only ones you recognize (Claude / Claude Code integrations you installed). Remove strangers.
- [ ] Fine-grained PATs / classic tokens (account-level → Settings → Developer settings): rotate or delete unused ones.
- [ ] Actions secrets and variables: none required by these workflows — anything present should be explainable; delete leftovers.
- [ ] Environments: none expected; delete stale ones.

### Publishing surface
- [ ] Packages: nothing published.
- [ ] Pages: stays disabled (verified today).
- [ ] Releases: none expected; anything tagged should be deliberate.

Re-run this checklist after adding any collaborator, app, or integration.
