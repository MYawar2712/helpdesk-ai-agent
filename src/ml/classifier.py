"""Inference wrapper for trained helpdesk ticket classifiers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from ml.train import DEFAULT_MODEL_PATH


@dataclass(frozen=True)
class TicketPrediction:
    """Classification result returned to the application layer."""

    category: str
    priority: str
    confidence_score: float
    requires_llm_review: bool


class TicketClassifier:
    """Load and run the persisted category and priority pipelines."""

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Ticket classifier model not found: {model_path}. "
                "Run `python -m ml.train` first."
            )
        artifact: dict[str, Any] = joblib.load(model_path)
        try:
            self.category_model = artifact["category"]
            self.priority_model = artifact["priority"]
        except KeyError as error:
            raise ValueError("Invalid ticket classifier artifact") from error

    def predict(self, text: str) -> TicketPrediction:
        """Predict category, priority, and the lower confidence fallback flag."""

        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        category, category_confidence = self._predict_one(self.category_model, text)
        priority, priority_confidence = self._predict_one(self.priority_model, text)
        confidence = min(category_confidence, priority_confidence)
        return TicketPrediction(
            category=category,
            priority=priority,
            confidence_score=confidence,
            requires_llm_review=confidence < 0.60,
        )

    @staticmethod
    def _predict_one(model: Any, text: str) -> tuple[str, float]:
        probabilities = model.predict_proba([text])[0]
        index = int(probabilities.argmax())
        return str(model.classes_[index]), float(probabilities[index])
