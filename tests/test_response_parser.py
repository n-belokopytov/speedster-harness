"""Unit tests for ResponseParser."""

from __future__ import annotations

import json

import pytest

from speedster.agent_client import AgentResponse
from speedster.response_parser import ResponseParser


class TestResponseParser:
    def test_parse_valid_json(self) -> None:
        parser = ResponseParser()
        result = parser.parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_invalid_json(self) -> None:
        parser = ResponseParser()
        result = parser.parse_json("not json")
        assert result is None

    def test_parse_none(self) -> None:
        parser = ResponseParser()
        result = parser.parse_json(None)  # type: ignore[arg-type]
        assert result is None

    def test_parse_qa_approved(self) -> None:
        parser = ResponseParser()
        response = AgentResponse(
            session_id="test",
            output=json.dumps({
                "status": "approved",
                "rejection_reasons": [],
            }),
            tokens_used=100,
            latency_ms=50,
        )
        result = parser.parse_qa(response)
        assert result.approved is True
        assert result.feedback == ["All criteria met"]

    def test_parse_qa_rejected(self) -> None:
        parser = ResponseParser()
        response = AgentResponse(
            session_id="test",
            output=json.dumps({
                "status": "rejected",
                "rejection_reasons": ["Missing tests"],
            }),
            tokens_used=100,
            latency_ms=50,
        )
        result = parser.parse_qa(response)
        assert result.approved is False
        assert "Missing tests" in result.feedback
