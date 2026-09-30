"""Run reproducible scenario checks against the full API/agent loop."""

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.database import make_engine
from app.main import create_app


SCENARIOS = Path(__file__).with_name("scenarios.json")


def evaluate_scenario(scenario: dict[str, Any], provider_name: str) -> dict[str, Any]:
    """Give each scenario a fresh seeded database so writes do not leak across cases."""
    settings = Settings(
        llm_provider=provider_name,
        SUPPORTOPS_DATABASE_URL="sqlite://",
        retry_base_delay_seconds=0,
    )
    application = create_app(settings=settings, engine=make_engine("sqlite://"))
    with TestClient(application) as client:
        response = client.post(
            "/api/chat",
            json={
                "customer_email": scenario["user"],
                "message": scenario["message"],
                "simulate_invoice_timeout": scenario.get("simulate_invoice_timeout", False),
            },
        )
    if response.status_code != 200:
        return {
            "name": scenario["name"],
            "passed": False,
            "tool_match": False,
            "unauthorized_action": False,
            "confirmation_violation": False,
            "reason": f"HTTP {response.status_code}: {response.text[:120]}",
        }

    payload = response.json()
    agent_response = payload["response"]
    tools_used = agent_response["tools_used"]
    expected = set(scenario.get("expected_tools", []))
    forbidden = set(scenario.get("forbidden_tools", []))
    forbidden_actions = set(scenario.get("forbidden_actions", []))
    tool_match = expected.issubset(tools_used)
    unauthorized_action = bool(forbidden.intersection(tools_used))
    confirmation_violation = bool(forbidden_actions.intersection(tools_used))
    status_match = agent_response["status"] == scenario["expected_behavior"]
    category_match = (
        "expected_category" not in scenario
        or agent_response["category"] == scenario["expected_category"]
    )
    trace_match = (
        "expected_trace_event" not in scenario
        or any(event["type"] == scenario["expected_trace_event"] for event in payload["events"])
    )
    passed = all(
        (tool_match, not unauthorized_action, not confirmation_violation, status_match, category_match, trace_match)
    )
    return {
        "name": scenario["name"],
        "passed": passed,
        "tool_match": tool_match,
        "unauthorized_action": unauthorized_action,
        "confirmation_violation": confirmation_violation,
        "reason": "" if passed else (
            f"status={agent_response['status']}, category={agent_response['category']}, "
            f"tools={tools_used}, trace_match={trace_match}"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate SupportOps Agent scenarios")
    parser.add_argument("--provider", choices=["mock", "openai", "anthropic"], default="mock")
    args = parser.parse_args()
    scenarios: list[dict[str, Any]] = json.loads(SCENARIOS.read_text())
    results = [evaluate_scenario(scenario, args.provider) for scenario in scenarios]
    passed = sum(result["passed"] for result in results)
    tool_correct = sum(result["tool_match"] for result in results)
    print(f"Scenarios: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {len(results) - passed}")
    print(f"Pass rate: {passed / len(results):.0%}")
    print()
    print(f"Tool-selection accuracy: {tool_correct / len(results):.0%}")
    print(f"Unauthorized actions: {sum(result['unauthorized_action'] for result in results)}")
    print(f"Confirmation violations: {sum(result['confirmation_violation'] for result in results)}")
    for result in results:
        print(f"{'PASS' if result['passed'] else 'FAIL'}  {result['name']}")
        if not result["passed"]:
            print(f"      {result['reason']}")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()