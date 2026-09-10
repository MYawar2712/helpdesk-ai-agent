"""SQLite JSON document client for support chat transcripts."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import ValidationError

from models_nosql import ChatTranscript


class TranscriptValidationError(ValueError):
    """Raised when transcript input or stored JSON is invalid."""


class NoSQLClient:
    """CRUD client for transcript documents stored in SQLite JSON."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS transcripts (
                transcript_id TEXT PRIMARY KEY,
                document TEXT NOT NULL CHECK (json_valid(document)),
                created_at TEXT NOT NULL
            )"""
        )
        self.connection.commit()

    def create_transcript(self, data: dict[str, Any]) -> str:
        """Validate and insert a transcript, returning its identifier."""

        transcript = self._validate(data)
        document = transcript.model_dump(mode="json")
        try:
            self.connection.execute(
                "INSERT INTO transcripts "
                "(transcript_id, document, created_at) VALUES (?, ?, ?)",
                (
                    transcript.transcript_id,
                    json.dumps(document),
                    document["created_at"],
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"Transcript already exists: {transcript.transcript_id}"
            ) from error
        return transcript.transcript_id

    def get_transcript(self, transcript_id: str) -> dict[str, Any] | None:
        """Return a validated transcript document, or ``None`` if absent."""

        row = self.connection.execute(
            "SELECT document FROM transcripts WHERE transcript_id = ?",
            (transcript_id,),
        ).fetchone()
        if row is None:
            return None
        return self._validate(json.loads(row[0])).model_dump(mode="json")

    def update_transcript_metadata(
        self, transcript_id: str, new_metadata: dict[str, Any]
    ) -> bool:
        """Replace a transcript's nested metadata object after validation."""

        metadata = ChatTranscript.model_fields["metadata"].annotation
        try:
            validated_metadata = metadata.model_validate(new_metadata)
        except ValidationError as error:
            raise TranscriptValidationError(str(error)) from error
        cursor = self.connection.execute(
            """UPDATE transcripts
            SET document = json_set(document, '$.metadata', json(?))
            WHERE transcript_id = ?""",
            (json.dumps(validated_metadata.model_dump(mode="json")), transcript_id),
        )
        self.connection.commit()
        if cursor.rowcount == 0:
            return False
        if self.get_transcript(transcript_id) is None:
            raise TranscriptValidationError("Stored transcript failed validation")
        return True

    def search_transcripts_by_keyword(self, keyword: str) -> list[dict[str, Any]]:
        """Find transcripts whose message text contains ``keyword``."""

        if not keyword.strip():
            raise ValueError("keyword must not be empty")
        rows = self.connection.execute(
            """SELECT DISTINCT transcripts.document
            FROM transcripts, json_each(transcripts.document, '$.messages') AS message
            WHERE lower(json_extract(message.value, '$.text'))
                LIKE '%' || lower(?) || '%'
            ORDER BY transcripts.transcript_id""",
            (keyword,),
        ).fetchall()
        return [
            self._validate(json.loads(row[0])).model_dump(mode="json") for row in rows
        ]

    def get_transcripts_by_ticket(self, ticket_id: str) -> list[dict[str, Any]]:
        """Return all transcripts associated with a ticket."""

        return self._get_transcripts_by_field("ticket_id", ticket_id)

    def get_transcripts_by_customer(self, customer_id: str) -> list[dict[str, Any]]:
        """Return all transcripts associated with a customer."""

        return self._get_transcripts_by_field("customer_id", customer_id)

    def _get_transcripts_by_field(
        self, field_name: str, field_value: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            f"""SELECT document FROM transcripts
            WHERE json_extract(document, '$.{field_name}') = ?
            ORDER BY transcript_id""",
            (field_value,),
        ).fetchall()
        return [
            self._validate(json.loads(row[0])).model_dump(mode="json") for row in rows
        ]

    def delete_transcript(self, transcript_id: str) -> bool:
        """Delete a transcript and return whether a row was removed."""

        cursor = self.connection.execute(
            "DELETE FROM transcripts WHERE transcript_id = ?", (transcript_id,)
        )
        self.connection.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _validate(data: dict[str, Any]) -> ChatTranscript:
        try:
            return ChatTranscript.model_validate_json(json.dumps(data))
        except ValidationError as error:
            raise TranscriptValidationError(str(error)) from error
