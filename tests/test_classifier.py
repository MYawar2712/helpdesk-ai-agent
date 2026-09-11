from pathlib import Path

import pytest

from ml.classifier import TicketClassifier
from ml.train import train_and_save


@pytest.fixture
def classifier(tmp_path: Path) -> TicketClassifier:
    model_path = tmp_path / "ticket_classifier.joblib"
    train_and_save(model_path=model_path)
    return TicketClassifier(model_path)


def test_predicts_urgent_outage(classifier: TicketClassifier) -> None:
    prediction = classifier.predict("Server completely down across all sites")
    assert prediction.category == "outage"
    assert prediction.priority == "urgent"
    assert 0.0 <= prediction.confidence_score <= 1.0


def test_ambiguous_text_requests_llm_review(classifier: TicketClassifier) -> None:
    prediction = classifier.predict("Please help")
    assert prediction.requires_llm_review is True


def test_missing_model_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="model not found"):
        TicketClassifier(tmp_path / "missing.joblib")
