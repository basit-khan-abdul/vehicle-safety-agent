"""Citation reconciliation + excerpt formatting (pure units, no client).

The loop tags every tool result with a marker and later scans the model's answer
for those markers. Only markers backed by a real tool call become citations;
invented markers are dropped. Excerpts summarize the underlying result.
"""

from app.agent.loop import _excerpt, _extract_citations


def _recall_record():
    return {
        "marker": "recalls:1",
        "tool": "get_recalls",
        "args": {"make": "Honda", "model": "Civic", "model_year": 2020},
        "result": {
            "count": 5,
            "recalls": [
                {"NHTSACampaignNumber": "21V215000", "Component": "FUEL SYSTEM"},
                {"NHTSACampaignNumber": "23V458000", "Component": "SERVICE BRAKES"},
            ],
        },
    }


def test_only_real_markers_become_citations():
    records = [_recall_record()]
    answer = (
        "The 2020 Honda Civic has 5 recall campaigns [recalls:1], including "
        "21V215000. (An invented reference [recalls:9] should be ignored.)"
    )

    citations = _extract_citations(answer, records)

    assert len(citations) == 1
    cite = citations[0]
    assert cite["marker"] == "recalls:1"
    assert cite["tool"] == "get_recalls"
    assert cite["args"]["model_year"] == 2020
    # The excerpt carries the ground-truth campaign numbers.
    assert "21V215000" in cite["excerpt"]
    assert "23V458000" in cite["excerpt"]


def test_markers_deduplicated_in_first_seen_order():
    records = [_recall_record()]
    answer = "recalls [recalls:1] ... and again [recalls:1]."
    citations = _extract_citations(answer, records)
    assert len(citations) == 1


def test_uncited_answer_yields_no_citations():
    records = [_recall_record()]
    assert _extract_citations("No markers here at all.", records) == []


def test_excerpt_relays_unavailable_payload():
    unavailable = {
        "error": "NHTSA returned a server error (HTTP 503).",
        "available": False,
        "source": "NHTSA",
    }
    excerpt = _excerpt("get_recalls", unavailable)
    assert "503" in excerpt


def test_excerpt_summarizes_complaints_top_component():
    result = {
        "total_complaints": 2743,
        "complaints_by_component": {"ENGINE": 802, "STEERING": 256},
        "recent_complaints": [],
    }
    excerpt = _excerpt("get_complaints", result)
    assert "2743" in excerpt
    assert "ENGINE" in excerpt
