"""Unit tests for utils.extractors — feature 013 US2 deterministic post-check."""

from __future__ import annotations


class TestToolExtractor:
    """T026 — whole-word matches, case-insensitive."""

    def test_tool_extractor_whole_word_match(self) -> None:
        from bewerbungs_agent.utils.extractors import tool_names_in_text

        registry = {"AWS", "Kafka", "Python"}
        # AWS inside AWS-managed → match (hyphen is non-word)
        assert "AWS" in tool_names_in_text("Built AWS-managed pipelines", registry)
        # AWS inside AWSome → NOT a match (alphanum-internal)
        assert "AWS" not in tool_names_in_text("That's so AWSome", registry)
        # Kafka inside kafkaesque → NOT a match
        assert "Kafka" not in tool_names_in_text("a kafkaesque debugging session", registry)
        # Kafka as standalone → match
        assert "Kafka" in tool_names_in_text("worked with Kafka clusters", registry)

    def test_tool_extractor_case_insensitive(self) -> None:
        from bewerbungs_agent.utils.extractors import tool_names_in_text

        registry = {"Python", "Kafka"}
        assert tool_names_in_text("python is my favourite", registry) == {"Python"}
        assert tool_names_in_text("PYTHON in production", registry) == {"Python"}
        assert tool_names_in_text("Python AND PYTHON", registry) == {"Python"}


class TestEmployerExtractor:
    """T026 — capitalised multi-word phrases after at/bei/with."""

    def test_employer_extractor_after_at_bei(self) -> None:
        from bewerbungs_agent.utils.extractors import employer_names_in_text

        text = "I worked at Acme Corp on infrastructure."
        assert "Acme Corp" in employer_names_in_text(text)

        text_de = "während meiner Zeit bei Bayer AG"
        assert "Bayer AG" in employer_names_in_text(text_de)

        # No prefix → not extracted
        text_no = "Acme Corp is a great company."
        assert "Acme Corp" not in employer_names_in_text(text_no)

        # Multi-word company name
        text_multi = "at JP Morgan Chase as a director"
        assert "JP Morgan Chase" in employer_names_in_text(text_multi)


class TestNumericExtractor:
    """T026 — digit sequences with punctuation normalised."""

    def test_numeric_extractor_normalises_punctuation(self) -> None:
        from bewerbungs_agent.utils.extractors import numeric_tokens_in_text

        # All map to "1000"
        assert numeric_tokens_in_text("1000 jobs/day") == {"1000"}
        assert numeric_tokens_in_text("1,000 events") == {"1000"}
        assert numeric_tokens_in_text("~1000 ops/s") == {"1000"}
        assert numeric_tokens_in_text("1000+ tasks") == {"1000"}
        assert numeric_tokens_in_text("99.9% uptime") == {"99.9"}

        # 1000 and 1500 are different
        tokens = numeric_tokens_in_text("processed 1000 and 1500 records")
        assert "1000" in tokens
        assert "1500" in tokens

        # 1.5 stays "1.5"
        assert numeric_tokens_in_text("waited 1.5 hours") == {"1.5"}


class TestPostCheck:
    """T026 — subset check on the three extractors."""

    def test_post_check_passes_on_subset(self) -> None:
        from bewerbungs_agent.utils.extractors import post_check

        registry = {"Python", "Kafka"}
        draft = "I worked at Acme Corp with Python and Kafka for 1000 jobs/day."
        polished = "I leveraged Python and Kafka at Acme Corp, handling 1000 jobs/day."
        result = post_check(draft, polished, registry)
        assert result.passed is True
        assert result.added_tools == []
        assert result.added_employers == []
        assert result.added_numerics == []

    def test_post_check_fails_on_added_tool(self) -> None:
        from bewerbungs_agent.utils.extractors import post_check

        registry = {"Python", "Kafka", "Spark"}
        draft = "Built with Python and Kafka."
        polished = "Built with Python, Kafka, and Spark."  # Spark added
        result = post_check(draft, polished, registry)
        assert result.passed is False
        assert "Spark" in result.added_tools

    def test_post_check_fails_on_added_employer(self) -> None:
        from bewerbungs_agent.utils.extractors import post_check

        registry = {"Python"}
        draft = "worked at Acme Corp with Python."
        polished = "worked at Acme Corp and at Bayer AG with Python."
        result = post_check(draft, polished, registry)
        assert result.passed is False
        assert "Bayer AG" in result.added_employers

    def test_post_check_fails_on_added_numeric(self) -> None:
        from bewerbungs_agent.utils.extractors import post_check

        registry = {"Python"}
        draft = "Handled 1000 jobs/day with Python."
        polished = "Handled 1000 jobs/day and 2000 events with Python."
        result = post_check(draft, polished, registry)
        assert result.passed is False
        assert "2000" in result.added_numerics
