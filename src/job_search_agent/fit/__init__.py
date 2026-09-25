"""Fit-scoring agents: judge whether a listing matches the user's profile.

Two stages (tasks.md Phase 6/7): a cheap Haiku pass over everything that survives the
rule-based pre-filter, then a more careful Sonnet pass only on what Haiku doesn't rule out -
model tiering is the main cost-control lever in the whole pipeline.
"""
