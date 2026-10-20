import pytest

from heatshield.rag.agent import IDK, HeatShieldAssistant
from heatshield.rag.ingest import CHUNKS

pytestmark = pytest.mark.skipif(not CHUNKS.exists(), reason="run `make -C src rag` first")


@pytest.fixture(scope="module")
def assistant():
    return HeatShieldAssistant()


def test_answer_has_page_level_citations(assistant):
    a = assistant.ask("What time of day should people avoid direct sunlight?")
    assert a.supported and a.citations
    assert any(c["doc_id"] == "ndma_heatwave_advisory_apr2025" and c["page"] == 3 for c in a.citations)
    assert "11:00" in a.text
    # every [n] in the text refers to a listed citation
    import re
    assert {int(n) for n in re.findall(r"\[(\d+)\]", a.text)} <= {c["n"] for c in a.citations}


@pytest.mark.parametrize("q", ["What is the capital of France?", "How do I apply for a Pakistani passport?",
                               "What did the NDMA heatwave advisory of June 2026 say?"])
def test_unsupported_questions_get_i_dont_know(assistant, q):
    a = assistant.ask(q)
    assert not a.supported and a.text == IDK and not a.citations


def test_data_question_cites_gold_row(assistant):
    a = assistant.ask("What was the heat index in Karachi on 2024-06-24?")
    assert any(c.get("row_id") == "karachi-20240624" for c in a.citations)
