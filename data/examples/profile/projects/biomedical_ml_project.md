# Project — Biomedical-ML Modelling for Drug-Response Prediction

**Role**: ML lead (contract)
**Duration**: 2023–2024, 10 months
**Domain**: Computational biology / oncology drug response
**Team size**: 4 (1 ML lead, 2 ML engineers, 1 biostatistician)

## Context

A pharma research group wanted to predict tumour-cell response to a small
panel of candidate drugs using transcriptomic profiles. The previous in-house
approach was a hand-tuned random forest with limited generalisation across
tissue types.

## What I did

- Designed and trained a multi-task neural network that predicts
  drug-response curves jointly across 12 tissue types from RNA-seq profiles,
  using a shared encoder + per-tissue heads.
- Built the data pipeline that ingests, deduplicates, and normalises
  expression matrices from three internal cohorts and two public datasets
  (TCGA, CCLE), producing a reproducible, versioned training corpus.
- Owned model evaluation end-to-end: stratified cross-validation across
  tissue lineages, calibration analysis, comparison to the prior random-forest
  baseline using AUROC and concordance index on held-out test sets.
- Collaborated weekly with the biostatistician and oncology researchers to
  translate scientific questions into modelling decisions.

## Outcomes

- New model improved per-tissue AUROC from 0.72 (baseline) to 0.81 (mean
  across 12 tissues).
- Reduced training time from ~14 hours to ~3 hours by switching from per-tissue
  models to the shared-encoder design, freeing GPU capacity for the larger
  research program.
- Codebase (Python, PyTorch, scikit-learn) handed over with a reproducible
  training script, model card, and an evaluation harness the in-house team
  has continued to use.

## What I learned

- How to translate biological constraints (tissue similarity, treatment
  dose-response shapes) into model architecture choices.
- Working closely with domain experts who don't speak ML-engineer; learned to
  drive design through shared visualisations rather than jargon.
- The boundary between "ML modelling" and "ML platform" — this project taught
  me that the biggest leverage usually lives in the platform layer, which is
  where I've focused since.
