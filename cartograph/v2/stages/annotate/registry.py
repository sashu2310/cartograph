"""default_annotators() — the standard set of framework annotators."""

from __future__ import annotations

from cartograph.v2.stages.annotate.frameworks.celery import CeleryAnnotator
from cartograph.v2.stages.annotate.frameworks.django_ninja import DjangoNinjaAnnotator
from cartograph.v2.stages.annotate.frameworks.django_orm import DjangoOrmAnnotator
from cartograph.v2.stages.annotate.frameworks.django_signals import (
    DjangoSignalsAnnotator,
)
from cartograph.v2.stages.annotate.frameworks.fastapi import FastApiAnnotator
from cartograph.v2.stages.annotate.frameworks.flask import FlaskAnnotator
from cartograph.v2.stages.annotate.protocol import Annotator


def default_annotators() -> tuple[Annotator, ...]:
    """All framework annotators that ship with v2. Order is not semantically
    significant — labels from all annotators get merged into one dict."""
    return (
        FastApiAnnotator(),
        FlaskAnnotator(),
        CeleryAnnotator(),
        DjangoNinjaAnnotator(),
        DjangoSignalsAnnotator(),
        DjangoOrmAnnotator(),
    )
