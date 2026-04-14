from cartograph.parser.languages.python.frameworks.celery import CeleryDetector
from cartograph.parser.languages.python.frameworks.django_ninja import (
    DjangoNinjaDetector,
)
from cartograph.parser.languages.python.frameworks.django_orm import DjangoORMDetector
from cartograph.parser.languages.python.frameworks.django_signals import (
    DjangoSignalDetector,
)
from cartograph.parser.languages.python.frameworks.fastapi import FastAPIDetector
from cartograph.parser.languages.python.frameworks.flask import FlaskDetector

__all__ = [
    "CeleryDetector",
    "DjangoNinjaDetector",
    "DjangoORMDetector",
    "DjangoSignalDetector",
    "FastAPIDetector",
    "FlaskDetector",
]
