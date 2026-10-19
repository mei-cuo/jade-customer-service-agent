from shopdesk.evaluation import evaluate


def test_benchmark_reports_measured_cases():
    report = evaluate()
    assert len(report["cases"]) == 32
    assert 0 <= report["full"]["answer_fact_hit"] <= 1
    assert report["full"]["intent_accuracy"] == 1
    assert report["full"]["route_accuracy"] == 1
    assert report["full"]["p50_latency_ms"] > 0
    assert "baseline" in report
