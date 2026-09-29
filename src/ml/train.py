"""Train and persist the Day 8 ticket triage models."""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from models import normalize_ticket_category

DEFAULT_DATABASE = Path(__file__).parents[2] / "db" / "helpdesk.sqlite3"
DEFAULT_MODEL_PATH = Path(__file__).parents[2] / "models" / "ticket_classifier.joblib"


@dataclass(frozen=True)
class TrainingRecord:
    text: str
    category: str
    priority: str


SYNTHETIC_RECORDS = [
    ("invoice charged twice payment duplicate charge", "billing", "high"),
    ("incorrect invoice amount and unexpected fee", "billing", "medium"),
    ("refund request for my subscription payment", "billing", "medium"),
    ("credit card payment failed at checkout", "billing", "high"),
    ("need a copy of my monthly invoice", "billing", "low"),
    ("billing address needs to be updated", "billing", "low"),
    ("service completely down across all sites", "technical", "urgent"),
    ("server completely down across all sites", "technical", "urgent"),
    ("production outage all users cannot connect", "technical", "urgent"),
    ("network unavailable since this morning", "technical", "high"),
    ("website is returning errors for customers", "technical", "high"),
    ("intermittent connection outage in our office", "technical", "high"),
    ("monitoring reports a service interruption", "technical", "medium"),
    ("how do I change my account password", "general", "low"),
    ("please explain the available support plans", "general", "low"),
    ("where can I find the user documentation", "general", "low"),
    ("question about account settings", "general", "low"),
    ("request information about onboarding", "general", "medium"),
    ("need help configuring notification preferences", "general", "medium"),
    ("laptop will not boot after update", "technical", "high"),
    ("broken monitor needs replacement", "technical", "medium"),
    ("keyboard and mouse are not working", "technical", "medium"),
    ("server disk has failed and is beeping", "technical", "urgent"),
    ("printer is offline and cannot print", "technical", "medium"),
    ("new workstation equipment request", "technical", "low"),
    ("ac repair job lock technician service request", "technical", "medium"),
    ("air conditioning unit broken needs repair visit", "technical", "medium"),
    ("schedule job lock for ac maintenance technician", "technical", "medium"),
    ("move my technician appointment to another day", "scheduling", "medium"),
    ("please book a service visit for next week", "scheduling", "low"),
    ("reschedule my technician visit for next week", "scheduling", "medium"),
    ("my confirmed appointment is tomorrow morning", "scheduling", "medium"),
    ("technician has not arrived for my appointment", "scheduling", "high"),
    ("is this repair covered by my warranty", "warranty", "medium"),
    ("what does the warranty policy cover", "warranty", "low"),
    ("warranty claim for a failed compressor", "warranty", "medium"),
    ("are replacement parts covered by warranty", "warranty", "low"),
    ("my warranty expired last month", "warranty", "medium"),
    ("please cancel my upcoming service visit", "cancellation", "medium"),
    ("cancel my appointment booking", "cancellation", "low"),
    ("cancel my service appointment", "cancellation", "medium"),
    ("stop my upcoming technician visit", "cancellation", "medium"),
    ("terminate my subscription service", "cancellation", "low"),
]


def _synthetic_records() -> list[TrainingRecord]:
    """Return repeated, varied examples so every class is trainable."""

    records: list[TrainingRecord] = []
    for text, category, priority in SYNTHETIC_RECORDS:
        records.extend(
            TrainingRecord(f"{text} {suffix}", category, priority)
            for suffix in ("", " please investigate", " reported by customer")
        )
    return records


def load_database_records(database_path: Path) -> list[TrainingRecord]:
    """Load usable ticket text from SQLite, returning an empty list if unavailable."""

    if not database_path.exists():
        return []
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT title, description, category, priority FROM tickets"
        ).fetchall()

    records: list[TrainingRecord] = []
    for title, description, category, priority in rows:
        if not title or not description or not category or not priority:
            continue
        try:
            normalized_category = normalize_ticket_category(str(category))
        except (TypeError, ValueError):
            # Do not train on labels outside the canonical category contract.
            continue
        records.append(
            TrainingRecord(
                f"{title}. {description}",
                normalized_category,
                str(priority).lower(),
            )
        )
    return records


def build_dataset(database_path: Path = DEFAULT_DATABASE) -> list[TrainingRecord]:
    """Combine database examples with the robust fallback corpus."""

    return _synthetic_records() + load_database_records(database_path)


def build_pipeline() -> Pipeline[Any]:
    """Create the shared TF-IDF plus logistic-regression pipeline."""

    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True)),
            ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
        ]
    )


def _train_target(records: list[TrainingRecord], target: str) -> Pipeline[Any]:
    texts = [record.text for record in records]
    labels = [getattr(record, target) for record in records]
    pipeline = build_pipeline()
    train_texts, test_texts, train_labels, test_labels = train_test_split(
        texts, labels, test_size=0.25, random_state=42, stratify=labels
    )
    pipeline.fit(train_texts, train_labels)
    predictions = pipeline.predict(test_texts)
    print(f"\n{target.title()} classifier")
    print(f"Accuracy: {accuracy_score(test_labels, predictions):.3f}")
    print(
        f"F1 (weighted): {f1_score(test_labels, predictions, average='weighted'):.3f}"
    )
    print(classification_report(test_labels, predictions, zero_division=0))
    return pipeline


def train_and_save(
    database_path: Path = DEFAULT_DATABASE, model_path: Path = DEFAULT_MODEL_PATH
) -> Path:
    """Train both targets and save them as one versioned joblib artifact."""

    records = build_dataset(database_path)
    artifact = {
        "category": _train_target(records, "category"),
        "priority": _train_target(records, "priority"),
        "version": 2,
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    print(f"Saved model to {model_path}")
    return model_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    train_and_save(args.database, args.output)


if __name__ == "__main__":
    main()
