# Release and branch protection

## Required checks

Merges to `main` must pass the consolidated [CI workflow](../.github/workflows/ci.yml):

- **Tests (Python 3.14)** — compile, pytest (95% coverage), Ruff, mypy
- **HACS validation**
- **Hassfest**
- **CI success** — aggregate gate that `needs` the three jobs above

Release Please runs only on pushes to `main`, and only after **CI success** for that exact SHA (`needs: [ci-success]`). Untested commits cannot create tags or GitHub releases through this automation.

## Repository ruleset (apply once)

Create or update a GitHub ruleset for `main` (Settings → Rules → Rulesets, or `gh api`):

1. Target branch: `main`
2. Require status checks to pass: `Tests (Python 3.14)`, `HACS validation`, `Hassfest`, `CI success`
3. Require branch to be up to date before merging
4. Require at least one approving review
5. Do **not** allow bypass for repository administrators on this ruleset

Example (adjust org/repo and existing ruleset id as needed):

```bash
gh api repos/{owner}/{repo}/rulesets --method POST --input - <<'EOF'
{
  "name": "main protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          {"context": "Tests (Python 3.14)"},
          {"context": "HACS validation"},
          {"context": "Hassfest"},
          {"context": "CI success"}
        ]
      }
    },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    }
  ],
  "bypass_actors": []
}
EOF
```

## Emergency break-glass

If a critical hotfix must land while CI or reviews are unavailable:

1. A repository admin temporarily sets the ruleset enforcement to `evaluate` (or adds a short-lived bypass actor).
2. Merge the hotfix with an explicit incident note in the PR.
3. Immediately restore `active` enforcement with empty `bypass_actors`.
4. Follow up with a normal PR that restores any skipped validation.

Do not leave bypass enabled.
