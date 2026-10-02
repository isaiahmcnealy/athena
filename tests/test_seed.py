import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from athena import cli
from athena.ingestion.seed import seed_plan


def test_plan_balances_topics_and_sources_with_bounded_budget():
    plan = seed_plan()
    assert len({job["topic"] for job in plan}) == 20
    assert len(plan) == 40
    assert sum(job["limit"] for job in plan) == 5000
    for source in ("arxiv", "openalex"):
        selected = seed_plan(250, source)
        assert len(selected) == 20
        assert {job["source"] for job in selected} == {source}
        assert sum(job["limit"] for job in selected) == 5000


def test_dry_run_never_connects_to_database_or_provider(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: pytest.fail("Read settings during dry run"))
    cli.main(["seed", "--dry-run", "--start-at", "39"])
    output = json.loads(capsys.readouterr().out)
    assert output["requested_records"] == 250
    assert [job["job"] for job in output["queries"]] == [39, 40]


@pytest.mark.parametrize(
    "arguments",
    [["--per-query", "0"], ["--per-query", "1001"], ["--start-at", "0"], ["--start-at", "41"]],
)
def test_invalid_seed_bounds_are_rejected(arguments):
    with pytest.raises(SystemExit) as error:
        cli.main(["seed", "--dry-run", *arguments])
    assert error.value.code == 2


def test_seed_reports_actual_insertions_and_spaces_queries(monkeypatch, capsys):
    result = {
        "status": "completed",
        "processed": 125,
        "inserted": 100,
        "updated": 25,
        "rejected": 0,
    }
    importer = Mock(return_value=result)
    monkeypatch.setattr(cli, "import_query", importer)
    http = SimpleNamespace(sleep=Mock())
    assert cli.run_seed(http, None, seed_plan(), 39) == 0
    assert importer.call_count == 2
    http.sleep.assert_called_once_with(3)
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert summary["inserted"] == 200
    assert summary["updated"] == 50


def test_failure_stops_batch_and_reports_restart_without_leaking_secrets(monkeypatch, capsys):
    importer = Mock(side_effect=RuntimeError("api_key=secret"))
    monkeypatch.setattr(cli, "import_query", importer)
    assert cli.run_seed(SimpleNamespace(sleep=Mock()), None, seed_plan(), 7) == 1
    assert importer.call_count == 1
    error = capsys.readouterr().err
    assert "secret" not in error
    assert json.loads(error)["job"] == 7
    assert "--start-at 7" in error


def test_identity_conflicts_stop_with_partial_status(monkeypatch, capsys):
    importer = Mock(
        return_value={
            "status": "partial",
            "processed": 5,
            "inserted": 4,
            "updated": 0,
            "rejected": 1,
        }
    )
    monkeypatch.setattr(cli, "import_query", importer)
    assert cli.run_seed(SimpleNamespace(sleep=Mock()), None, seed_plan(), 1) == 1
    assert importer.call_count == 1
    assert json.loads(capsys.readouterr().err)["rejected"] == 1
