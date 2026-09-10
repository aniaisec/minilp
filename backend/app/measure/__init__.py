"""Measuring MiniLP by collecting labels through it (docs/MEASUREMENT.md).

Three tools, none of which the platform itself depends on:

    provision  mint study raters (user + key + human annotator)   — needs the DB
    simulate   drive a project with raters of known quality        — HTTP only
    report     join exports with an answer key the platform never  — HTTP only
               saw, and compute what the study measures

``metrics`` holds the arithmetic, pure and fixture-tested, so a study's numbers
can be recomputed from its archived exports alone.
"""
