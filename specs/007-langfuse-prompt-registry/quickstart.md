# Quickstart: Langfuse Prompt Registry

**Feature**: 007-langfuse-prompt-registry
**Audience**: prompt engineers who want their local prompt files tracked, versioned, and labelled in Langfuse.

---

## 1. Prerequisites

- Feature 006 (Langfuse observability) installed and configured.
- A Langfuse project + credentials in `.env`:
  ```
  LANGFUSE_PUBLIC_KEY=pk-lf-...
  LANGFUSE_SECRET_KEY=sk-lf-...
  LANGFUSE_BASE_URL=https://cloud.langfuse.com
  ```
- The `langfuse` Python SDK installed (already pinned in `pyproject.toml`).

No further configuration: the registry uses the same credentials as feature 006.

---

## 2. First sync

From the repo root:

```bash
uv run jobagent prompts sync
```

Default label is `staging`. Expected output:

```
[prompts] Discovered 11 local prompt files.
[prompts] CREATED   bewerbungs-agent/planner            version 1   label=staging
[prompts] CREATED   bewerbungs-agent/writer             version 1   label=staging
[prompts] CREATED   bewerbungs-agent/hiring_reviewer    version 1   label=staging
[prompts] CREATED   bewerbungs-agent/requirements       version 1   label=staging
[prompts] CREATED   bewerbungs-agent/evidence           version 1   label=staging
[prompts] CREATED   bewerbungs-agent/tailor_cv          version 1   label=staging
[prompts] CREATED   bewerbungs-agent/targeted_rewriter  version 1   label=staging
[prompts] CREATED   bewerbungs-agent/validator          version 1   label=staging
[prompts] CREATED   bewerbungs-agent/system             version 1   label=staging
[prompts] CREATED   bewerbungs-agent/styles/standard    version 1   label=staging
[prompts] CREATED   bewerbungs-agent/styles/aida        version 1   label=staging
[prompts] Summary: 11 created, 0 unchanged, 0 relabeled, 0 failed.
```

Open Langfuse → Prompts: you'll see each prompt under its `bewerbungs-agent/...` name, each at version 1, each carrying the staging label and the metadata block (file path, content hash, model, git commit).

---

## 3. Re-sync (idempotent)

Without any local edit, re-run:

```bash
uv run jobagent prompts sync
```

```
[prompts] Discovered 11 local prompt files.
[prompts] UNCHANGED bewerbungs-agent/planner            version 1   label=staging
[prompts] UNCHANGED bewerbungs-agent/writer             version 1   label=staging
...
[prompts] Summary: 0 created, 11 unchanged, 0 relabeled, 0 failed.
```

Zero new versions created. Safe to wire into CI.

---

## 4. Edit and re-sync

Edit `prompts/writer.md`. Re-run:

```bash
uv run jobagent prompts sync
```

```
[prompts] CREATED   bewerbungs-agent/writer             version 2   label=staging
[prompts] UNCHANGED bewerbungs-agent/planner            version 1   label=staging
... (all others unchanged) ...
[prompts] Summary: 1 created, 10 unchanged, 0 relabeled, 0 failed.
```

`staging` label moved from version 1 to version 2 of `bewerbungs-agent/writer`. Version 1 stays in history for rollback.

---

## 5. Promote to production

Once you've validated the new writer prompt on staging:

```bash
uv run jobagent prompts sync --label production
```

The current local content matches what's on Langfuse (staging label points at it), so no new version is created — the `production` label is moved to that same version:

```
[prompts] RELABELED bewerbungs-agent/writer            version 2   label=production (was: staging)
[prompts] UNCHANGED bewerbungs-agent/planner           version 1   label=production (already)
...
```

The `production` label now points at the validated content. The `staging` label is unchanged (it still points at the same version).

> **Note**: with the default semantics, `--label production` moves the requested label only. Other labels on the same version stay where they are.

---

## 6. Inspect

```bash
uv run jobagent prompts list
```

```
FILE                          HASH      LANGFUSE NAME                       VERSION  LABELS              STATUS
prompts/planner.md            a3f9c12d  bewerbungs-agent/planner            1        production,staging  ✓ up-to-date
prompts/writer.md             4e2b0a91  bewerbungs-agent/writer             2        production,staging  ✓ up-to-date
prompts/hiring_reviewer.md    7e8c1f23  bewerbungs-agent/hiring_reviewer    1        staging             ✓ up-to-date
...
```

After editing `prompts/planner.md` locally but not re-syncing:

```
FILE                          HASH      LANGFUSE NAME                       VERSION  LABELS              STATUS
prompts/planner.md            f8b21d04  bewerbungs-agent/planner            1        production,staging  △ local-differs
prompts/writer.md             4e2b0a91  bewerbungs-agent/writer             2        production,staging  ✓ up-to-date
...
```

Machine-readable form:

```bash
uv run jobagent prompts list --json | jq '.[] | select(.status != "up-to-date")'
```

---

## 7. Wire into CI

A GitHub Actions step that auto-syncs from main to `staging`:

```yaml
- name: Sync prompts to Langfuse staging
  env:
    LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY }}
    LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY }}
    LANGFUSE_BASE_URL: ${{ secrets.LANGFUSE_BASE_URL }}
  run: uv run jobagent prompts sync --label staging
```

CI also benefits from `prompts list --json` as a pre-merge check:

```yaml
- name: Confirm all prompts are synced
  env:
    LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY }}
    LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY }}
    LANGFUSE_BASE_URL: ${{ secrets.LANGFUSE_BASE_URL }}
  run: |
    if uv run jobagent prompts list --json | jq -e '.[] | select(.status == "local-differs")' > /dev/null; then
      echo "Local prompts differ from Langfuse; run 'jobagent prompts sync' before merging."
      exit 1
    fi
```

---

## 8. Runtime cross-reference (with feature 006 observability)

If observability is enabled and prompts are synced, every LLM-stage span you click into in Langfuse now also tells you which prompt version produced it:

```
Trace: 4ffbe3df-...
├── plan_content          prompt=bewerbungs-agent/planner          version=3   label=production
├── write_letter          prompt=bewerbungs-agent/writer           version=7   label=production
├── tailor_cv             prompt=bewerbungs-agent/tailor_cv        version=2   label=production
├── hiring_review         prompt=bewerbungs-agent/hiring_reviewer  version=1   label=staging
├── targeted_rewrite      prompt=bewerbungs-agent/targeted_rewriter version=1  label=staging
```

If you've edited a prompt locally but not re-synced, the span shows:

```
├── plan_content          prompt=bewerbungs-agent/planner          version=unsynced  hash=f8b21d04
```

The `unsynced` marker makes drift between "what's running" and "what's registered" impossible to miss.

---

## 9. Disabled mode (no credentials)

Without `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` set:

```bash
$ uv run jobagent prompts sync
[prompts] Langfuse disabled (LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY missing); nothing uploaded.
$ echo $?
1
```

Exit code is `1` — CI catches an accidentally missing credential.

`prompts list` still works locally:

```bash
$ uv run jobagent prompts list
FILE                          HASH      LANGFUSE NAME                       VERSION  LABELS  STATUS
prompts/planner.md            a3f9c12d  bewerbungs-agent/planner            —        —       ✗ no-langfuse
...
$ echo $?
0
```

And `jobagent run` continues to work end-to-end exactly as it did before feature 007 — runtime never depends on Langfuse being reachable.

---

## 10. Smoke test (manual)

```bash
# 1. Fresh sync, verify all 11 prompts created.
uv run jobagent prompts sync --label staging
# Confirm: "Summary: 11 created, 0 unchanged, 0 relabeled, 0 failed."

# 2. Re-sync, verify idempotence.
uv run jobagent prompts sync --label staging
# Confirm: "Summary: 0 created, 11 unchanged, 0 relabeled, 0 failed."

# 3. Edit one file; re-sync.
echo "" >> prompts/planner.md
uv run jobagent prompts sync --label staging
# Confirm: "Summary: 1 created, 10 unchanged, 0 relabeled, 0 failed."

# 4. Inspect.
uv run jobagent prompts list
# Confirm: writer/hiring_reviewer/etc. status "✓ up-to-date";
#          planner status "✓ up-to-date" (we just synced it).

# 5. Revert the edit; do NOT re-sync.
git checkout prompts/planner.md
uv run jobagent prompts list
# Confirm: planner.md status "△ local-differs" (local reverted; remote still has the appended newline).

# 6. Run the agent and check the runtime span (in Langfuse UI).
uv run jobagent run --job data/examples/jobs/sample_software_engineer.md --template default_de_neutral
# Open the printed trace URL → plan_content span carries
#   prompt=bewerbungs-agent/planner  version=unsynced  hash=<reverted local hash>
```

If steps 1–4 produce the documented summaries and step 6 shows the `unsynced` marker for the locally-reverted prompt, the feature is working end-to-end.
