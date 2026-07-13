---
layout: default
title: Contamination — File-path Identification - BC-Bench
---

# Contamination detection: file-path identification

This diagnostic estimates how much a model may have **memorized** BC-Bench tasks
rather than solving them. It is a direct adaptation of the *file-path identification*
task from **["The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of
Reason"](https://arxiv.org/abs/2506.12286)** (arXiv:2506.12286).

> The file-path identification task requires models to identify buggy files using
> only GitHub issue descriptions, deliberately withholding all repository structure
> and code context.
>
> — *The SWE-Bench Illusion*, §1 (Introduction)

The intuition: bug localization *should* require the codebase. As the paper notes,
"models should require a genuine understanding of both the problem description and
codebase structure to identify relevant files" (§1). If a model names the buggy
file from the issue text **alone** — with no repository access — it is recalling an
association it could only have obtained by seeing the task during training.

The paper's headline finding is that this happens at scale:

> On the file-path identification task, SoTA models like o3 achieve up to 76%
> accuracy on SWE-Bench-Verified instances, despite lacking the contextual
> information that should be necessary for this task.
>
> — *The SWE-Bench Illusion*, §1

## What we run

For each `bug-fix` entry we give the model **only the bug report** (`entry.get_task()`)
and ask it to name the file(s) that must change. To guarantee the context-free
condition, the model runs with the Copilot CLI restricted to the `write` tool only
(no shell, file-read, or fetch), inside an isolated empty working directory — so it
has no way to reach the repository or the gold patch on disk. Its answer (a JSON
array of paths, capped at `top_k`, default 3) is parsed from stdout.

The **gold** buggy files are the files the fix patch touches
(`extract_gold_files(patch)`), i.e. the ground truth for "which file contains the bug."

## How the scores are calculated

Both the model's `predicted` paths and the `gold` paths are canonicalized two ways:

- **`normalize_path`** — lower-noise full path: `\` → `/`, strip `./`, `a/`/`b/`
  diff prefixes, quotes and trailing slashes. Example:
  `src/Apps/W1/Shopify/App/src/Products/Codeunits/ShpfyCreateItem.Codeunit.al`.
- **`_basename`** — just the file name, lower-cased: `shpfycreateitem.codeunit.al`.

Let `P` = set of normalized predicted paths, `G` = set of normalized gold paths, and
`Pₙ`, `Gₙ` the corresponding basename sets. Per entry:

| Metric | Definition |
| --- | --- |
| `exact_hit` | `1` if `G ∩ P ≠ ∅` — any full path correct |
| `basename_hit` | `1` if `Gₙ ∩ Pₙ ≠ ∅` — any file **name** correct |
| `exact_recall` | `|G ∩ P| / |G|` — fraction of gold paths found |
| `basename_recall` | `|Gₙ ∩ Pₙ| / |Gₙ|` — fraction of gold names found |

It is **recall@k**, not precision: extra wrong guesses are not penalized, matching
the paper's "can the model name the file" framing.

### Worked example (`microsoft__BCApps-4699`)

- gold: `…/Products/Codeunits/ShpfyCreateItem.Codeunit.al` (1 file)
- predicted (top 3): `ShpfyCreateItem.Codeunit.al`, `ShpfyExportItem.Codeunit.al`, `ShpfySyncItem.Codeunit.al` (full paths)

`G ∩ P = { ShpfyCreateItem.Codeunit.al }` → `exact_hit = true`,
`exact_recall = 1/1 = 1.0`, and the name matches too → `basename_hit = true`,
`basename_recall = 1.0`.

### Aggregation

Over the entries that ran without error:

- **Basename hit** / **Exact hit** = fraction of entries whose `basename_hit` /
  `exact_hit` is true (≈ the paper's context-free *accuracy*).
- **Mean basename recall** / **Mean exact recall** = average of the per-entry recall.

`hit ≥ recall`: for single-file bugs they are equal; multi-file bugs where the model
finds one gold file but misses others pull *recall* below *hit*.

## Why two granularities (exact vs basename)

This is a Business Central / AL-specific refinement of the paper's single accuracy
number. AL files follow a rigid `<ObjectName>.<ObjectType>.al` convention, so the
**basename** is often guessable from the description with *no* memorization
(`SalesHeader.Table.al` from a sales-header bug). The **exact path** additionally
requires knowing the deep folder layout, which is far harder to guess — so
`exact_hit` is the stronger memorization signal, while `basename_hit` is
convention-inflated and must be read with caution.

## Absolute rate vs. the contamination signal

**An absolute rate is not, by itself, proof of contamination.** The paper's actual
detector is a *disparity*, not a raw number:

> We propose a cross-benchmark performance analysis approach … using performance
> difference across similar tasks as indicators of memorization. Genuine coding skill
> should lead to similar performance across comparable tasks, while memorization
> would result in unusually high scores on tasks that likely overlap with the model's
> training data.
>
> — *The SWE-Bench Illusion*, §1

> **Cross-Benchmark Performance Analysis for Memorization Detection:** … When models
> exhibit disproportionately high performance on specific benchmarks compared to
> similar tasks, this indicates potential training data contamination rather than
> genuine coding ability.
>
> — *The SWE-Bench Illusion*, §1 (Contributions)

Our equivalent is the **`--cutoff`** delta. `split_by_cutoff` partitions results by
`created_at` into *pre-cutoff* (public before the boundary → potentially in training
data) and *on/after-cutoff* (the fresh control). The reported

```
contamination signal = basename_hit_rate(pre) − basename_hit_rate(control)
```

is a large positive number only when the model localizes old/public bugs far better
than fresh ones it could not have seen. Without a cutoff, the report shows the
absolute baseline only.

## Scope and caveats

- We implement task 1 of the paper's three diagnostics (file-path identification).
  The paper also proposes *function reproduction* and *prefix completion* (verbatim /
  n-gram overlap); those are not implemented here.
- The paper's 76% is on a **frontier** model (o3). A small model will score far lower
  without implying anything about contamination — compare like-for-like models, and
  always against a control set.
- Because this is black-box (behavioral), it detects *evidence* of memorization; it
  cannot quantify exactly what fraction of a task appears verbatim in training data —
  that would require access to the training corpus.

## Reference

*The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of Reason.*
arXiv:2506.12286. <https://arxiv.org/abs/2506.12286>

[← Back to Home](index.md)
