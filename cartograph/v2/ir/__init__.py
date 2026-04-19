"""Intermediate representations for the v2 pipeline.

Each stage boundary has its own IR module:
    base      — IR base class, Result/Ok/Err_ typed fallibility
    errors    — typed error IRs per stage
    syntactic — Stage 1 output (SyntacticModule + variants)
    resolved  — Stage 2 output (ResolvedGraph + UnresolvedCall variants)
    annotated — Stage 3 output (AnnotatedGraph + SemanticLabel variants)
    analyzed  — Stage 4 output (AnalyzedGraph + EntryPoint variants)
    common    — CommonGraph, the benchmarking IR shared with v1 (ADR-012)
"""
