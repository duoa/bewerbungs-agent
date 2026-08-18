# Senior Software Engineer — AI/ML Infrastructure

**Company**: Helix Compute GmbH
**Location**: Berlin, hybrid
**Role family**: Software engineering / platform engineering for AI/ML workloads

## About the role

We are hiring a Senior Software Engineer to build, operate, and scale the
infrastructure that runs our AI/ML workloads in production. You will own the
platform layer that hundreds of internal engineers and researchers rely on
every day. The role is squarely a software engineering and infrastructure role:
your week is spent designing reliable systems, writing robust Python, and
keeping inference and training pipelines fast, cheap, and observable.

This is not a research role. We have a small ML research team that builds
models; your job is to give them — and the rest of engineering — a platform
that does not break.

## What you will do

- Design and operate scalable cloud infrastructure for AI/ML training and
  inference, primarily on AWS (EKS, S3, MSK, RDS), with autoscaling, spot/GPU
  fleet management, and cost controls baked in.
- Write robust, well-tested Python software that holds up under production
  load: typed, modular, observable, recoverable from the kinds of failures
  large fleets actually produce.
- Build agentic systems that orchestrate multi-step LLM and tool-use workflows
  reliably — retries, idempotency, durable state, evaluation hooks, and
  guardrails are first-class concerns.
- Drive efficient compute: profile and reduce inference latency and cost,
  manage batched workloads, evaluate serving frameworks (vLLM, TGI, SageMaker),
  and own the trade-offs.
- Build the developer experience: CLI tooling, libraries, deployment
  templates, and CI integration so internal engineers can ship ML features
  without re-implementing platform primitives.
- Co-own incidents end-to-end: oncall rotation, postmortems, structural
  fixes that prevent recurrence, SLO-driven decision making.
- Mentor mid-level engineers and raise the bar on software quality for the
  whole platform team.

## Requirements

- 5+ years of production software engineering experience with a strong
  emphasis on Python.
- Deep hands-on experience operating distributed systems on a major cloud
  (AWS strongly preferred), including Kubernetes / containers, message queues,
  and managed storage.
- Track record of running AI/ML workloads in production: serving, batching,
  GPU/CPU scheduling, observability, cost optimisation.
- Experience designing systems that other engineers build on top of — APIs,
  SDKs, CLI tools, templates — with a clear sense of separation of concerns
  and backwards compatibility.
- Strong written communication: design docs, ADRs, postmortems.

## Nice to have

- Familiarity with biomedical or life-sciences data (we serve a few research
  partners in that space), but this is a peripheral domain context, not a
  primary requirement.
- Experience with agentic frameworks (LangGraph, AutoGen, or similar) and the
  evaluation harness around them.
- Prior platform-team or developer-tooling experience at a high-growth
  company.

## How we work

Small autonomous teams. RFC-driven decisions. Heavy investment in CI, type
checking, and reproducible builds. We prefer boring infrastructure that works
to clever infrastructure that doesn't.
