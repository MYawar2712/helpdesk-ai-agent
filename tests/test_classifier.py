from pathlib import Path

import pytest

from ml.classifier import TicketClassifier
from ml.train import train_and_save
from models import TicketCategory, normalize_ticket_category


@pytest.fixture
def classifier(tmp_path: Path) -> TicketClassifier:
    model_path = tmp_path / "ticket_classifier.joblib"
    train_and_save(model_path=model_path)
    return TicketClassifier(model_path)


def test_predicts_urgent_technical_issue(classifier: TicketClassifier) -> None:
    prediction = classifier.predict("Server completely down across all sites")
    assert prediction.category == "technical"
    assert prediction.priority == "urgent"
    assert 0.0 <= prediction.confidence_score <= 1.0


def test_model_uses_only_canonical_categories(classifier: TicketClassifier) -> None:
    assert set(classifier.category_model.classes_) == {
        category.value for category in TicketCategory
    }


def test_legacy_category_labels_migrate_to_canonical_values() -> None:
    assert normalize_ticket_category("hardware") == TicketCategory.TECHNICAL.value
    assert normalize_ticket_category("outage") == TicketCategory.TECHNICAL.value
    assert normalize_ticket_category("general_inquiry") == TicketCategory.GENERAL.value


def test_ambiguous_text_requests_llm_review(classifier: TicketClassifier) -> None:
    prediction = classifier.predict("Please help")
    assert prediction.requires_llm_review is True


def test_missing_model_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="model not found"):
        TicketClassifier(tmp_path / "missing.joblib")


def test_classify_intent_service_request() -> None:
    from models import TicketIntent
    from tools.classify_intent import classify_intent

    intent = classify_intent(
        "can u make a plumber to visit my place on thursday at 11 am to check toilet"
    )
    assert intent == TicketIntent.NEW_SERVICE_REQUEST
    assert (
        classify_intent("make me a service visit for a technician on Saturday at 10 am")
        == TicketIntent.NEW_SERVICE_REQUEST
    )
