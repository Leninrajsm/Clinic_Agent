"""Command line entry point.

    python -m app.cli chat              talk to the agent (seeds the demo clinic on first run)
    python -m app.cli eval              run the eval harness once
    python -m app.cli loop              run the improvement loop (baseline -> fix -> re-run -> gate)
    python -m app.cli seed              re-seed the demo clinic
    python -m app.cli models            list Gemini models your key can use
    python -m app.cli policy list       show policy versions
"""

import asyncio
import json

import typer
from rich.console import Console
from rich.markup import escape

from app.config import get_settings
from app.runtime import DEMO_SANDBOX, build_runtime

app = typer.Typer(add_completion=False, help="2care.ai scheduling agent")
policy_app = typer.Typer(help="Inspect and switch policy versions")
app.add_typer(policy_app, name="policy")
console = Console()


def _short(value, limit: int = 140) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _print_events(events: list[dict], flags: list[str]) -> None:
    for e in events:
        line = f"  [tool] {e['tool']}({_short(e['args'], 90)}) -> {_short(e['result'])}"
        style = "yellow" if e.get("denied_by") else "dim"
        console.print(escape(line + (f"  DENIED by {e['denied_by']}" if e.get("denied_by") else "")), style=style)
    for f in flags:
        if not f.startswith("guard:"):
            console.print(escape(f"  [flag] {f}"), style="magenta")


@app.command()
def chat(
    trace: bool = typer.Option(True, help="Show tool calls, guard decisions and state"),
    reset: bool = typer.Option(False, help="Re-seed the demo clinic before starting"),
    policy: str = typer.Option(None, help="Policy version to use (default: active)"),
):
    """Chat with the scheduling agent in the terminal."""

    async def run():
        rt = await build_runtime()
        seeded = await rt.ensure_demo_sandbox(reset=reset)
        agent = rt.agent()
        session = await agent.start_session(DEMO_SANDBOX, policy_version=policy)
        console.print(f"[dim]database: {rt.repo.backend} | policy: {session.policy_version} | "
                      f"model: {agent.model} | today: {rt.clock.now():%a %b %d %Y %I:%M %p}"
                      f"{' | demo clinic seeded' if seeded else ''}[/dim]")
        console.print("[dim]Type 'quit' to exit. Try: Maria Lopez, DOB 1988-03-14.[/dim]\n")
        console.print(f"[bold cyan]Agent:[/bold cyan] {escape(agent.greeting())}")
        while True:
            try:
                text = console.input("[bold green]You:[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in ("quit", "exit"):
                break
            if not text:
                continue
            result = await agent.respond(session.id, text)
            if trace:
                _print_events(result.tool_events, result.flags)
                console.print(escape(f"  [state] stage={result.stage}"), style="dim")
            console.print(f"[bold cyan]Agent:[/bold cyan] {escape(result.reply)}")
        console.print(f"[dim]Session {session.id} saved. LLM usage: {_short(rt.llm.usage_summary(), 300)}[/dim]")

    asyncio.run(run())


def _progress(event: dict) -> None:
    t = event["type"]
    if t == "run_started":
        console.print(f"\n[bold]>> Eval run {event['run_id']}[/bold] ({event['label'] or 'eval'}): policy "
                      f"{event['policy_version']}, {event['scenarios']} scenarios x {event['trials']} trials")
    elif t == "trial_done":
        if event["status"] == "error":
            mark = "[yellow]ERR [/yellow]"
        else:
            mark = "[green]PASS[/green]" if event["passed"] else "[red]FAIL[/red]"
        why = f" {event['critical_failures']}" if event.get("critical_failures") else ""
        err = f" {escape(str(event['error'])[:120])}" if event.get("error") else ""
        console.print(f"  {event['progress']:>7} {mark} {event['scenario_id']} #{event['trial']} "
                      f"score={event['score']}{escape(why)}{err}")
    elif t == "run_finished":
        s = event["summary"]
        console.print(f"  [bold]= {s['overall']['passed']}/{s['overall']['total']} scenarios passed[/bold] "
                      f"(train {s['train']['passed']}/{s['train']['total']}, holdout "
                      f"{s['holdout']['passed']}/{s['holdout']['total']}), mean score {s['overall']['mean_score']}")
    elif t == "iteration_started":
        console.print(f"\n[bold]>> Iteration {event['iteration']}[/bold]: failing train scenarios "
                      f"{event['failing_train'] or 'none'}")
    elif t == "analyzing":
        console.print(f"  analyzer: attempt {event['attempt']} ...")
    elif t == "proposals":
        for p in event["proposals"]:
            console.print(escape(f"  proposal [{p['failure_cluster']}]: {p['root_cause']}"))
        for p in event["code_tickets"]:
            console.print(escape(f"  code ticket [{p['failure_cluster']}]: {p.get('code_change_ticket')}"), style="yellow")
    elif t == "candidate_created":
        console.print(f"  candidate policy [bold]{event['version']}[/bold]:")
        console.print(escape(event["diff"]), style="cyan")
        for r in event["rejected"]:
            console.print(escape(f"  refused edit: {r}"), style="yellow")
    elif t == "rechecking":
        console.print(f"  possible regressions {event['scenarios']}: re-running with extra trials to rule out noise")
    elif t == "gate":
        verdict = "[green]ACCEPTED[/green]" if event["accepted"] else "[red]REJECTED[/red]"
        console.print(f"  gate for {event['version']}: {verdict}")
        for r in event["reasons"]:
            console.print(escape(f"    - {r}"))
    elif t == "analyzer_fallback":
        console.print(escape(f"  analyzer {event['from']} unavailable, using {event['to']} ({event['reason'][:100]})"),
                      style="yellow")
    elif t == "awaiting_review":
        console.print(f"  [bold yellow]{event['version']} passed the gate; held for review[/bold yellow] "
                      f"({event['active']} stays live)")
    elif t == "attempt_failed":
        console.print(escape(f"  attempt failed: {event['reason']}"), style="yellow")
    elif t == "loop_finished":
        console.print(f"\n[bold]>> {escape(event['outcome'])}[/bold]")
        for row in event["before_after"]:
            console.print(f"    {row['scenario_id']:<24} {row['before_pass_rate']:>5} -> {row['after_pass_rate']:<5} "
                          f"{row['change']}")


@app.command("eval")
def eval_cmd(
    policy: str = typer.Option(None, help="Policy version (default: active)"),
    trials: int = typer.Option(None, help="Trials per scenario (default: EVAL_TRIALS, 3)"),
    scenario: list[str] = typer.Option(None, "--scenario", "-s", help="Only these scenario ids (repeatable)"),
    quick: bool = typer.Option(False, help="One trial per scenario (cheap smoke test)"),
):
    """Run the eval harness once and write a report to reports/runs/."""
    from app.evals.report import persist_run
    from app.evals.runner import run_suite
    from app.evals.scenarios import load_scenarios

    async def run():
        rt = await build_runtime()
        n = 1 if quick else (trials or rt.settings.eval_trials)
        version = policy or rt.policies.active_version()
        console.print(f"[dim]database: {rt.repo.backend} | agent: {rt.settings.model_agent} | "
                      f"simulator: {rt.settings.model_simulator} | judge: {rt.settings.model_judge}[/dim]")
        result = await run_suite(rt, version, load_scenarios(ids=scenario or None), n, _progress)
        await persist_run(rt.repo, result)
        console.print(f"Report: reports/runs/{result.run_id}.md")
        console.print(f"[dim]LLM usage: {_short(rt.llm.usage_summary(), 300)}[/dim]")

    asyncio.run(run())


@app.command()
def loop(
    trials: int = typer.Option(None, help="Trials per scenario (default: EVAL_TRIALS, 3)"),
    scenario: list[str] = typer.Option(None, "--scenario", "-s", help="Only these scenario ids (repeatable)"),
    max_attempts: int = typer.Option(3, help="Analyzer attempts per iteration if the gate rejects"),
    iterations: int = typer.Option(1, help="Improvement iterations (each needs a full re-run)"),
    baseline: str = typer.Option(None, help="Reuse a saved run id as the baseline instead of re-running"),
    review: bool = typer.Option(False, "--review",
                                help="Don't activate a passing candidate; wait for 'policy approve' or 'policy reject'"),
):
    """Run the improvement loop: baseline -> analyze failures -> candidate policy -> re-run -> gate."""
    from app.improve.loop import run_loop

    async def run():
        rt = await build_runtime()
        console.print(f"[dim]database: {rt.repo.backend} | active policy: {rt.policies.active_version()} | "
                      f"analyzer: {rt.settings.model_analyzer}"
                      f"{' | review mode: passing candidates wait for approval' if review else ''}[/dim]")
        report = await run_loop(rt, trials or rt.settings.eval_trials, scenario or None, max_attempts,
                                iterations, baseline, _progress, review=review)
        console.print(f"Loop report: reports/loops/{report.loop_id}.md")
        if report.awaiting_review:
            v = report.awaiting_review
            console.print(f"\n[bold yellow]{v} is waiting for your review.[/bold yellow] Inspect it, then decide:")
            console.print(f"  python -m app.cli policy diff {rt.policies.get(v).parent} {v}")
            console.print(f"  python -m app.cli policy approve {v}     (goes live)")
            console.print(f"  python -m app.cli policy reject {v}      (discarded)")
        console.print(f"[dim]LLM usage: {_short(rt.llm.usage_summary(), 300)}[/dim]")

    asyncio.run(run())


@app.command()
def seed():
    """Reset and re-seed the demo clinic (sandbox 'demo')."""

    async def run():
        rt = await build_runtime()
        summary = await rt.ensure_demo_sandbox(reset=True)
        console.print(f"Seeded on {rt.repo.backend}: {summary}")

    asyncio.run(run())


@app.command()
def models():
    """List Gemini models available to your API key."""
    from google import genai

    client = genai.Client(api_key=get_settings().gemini_api_key)
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if not actions or "generateContent" in actions:
            console.print(m.name.removeprefix("models/"))


@policy_app.command("list")
def policy_list():
    """Show all policy versions and which one is active."""
    from app.policy.store import PolicyStore

    store = PolicyStore()
    active = store.active_version()
    for v in store.versions():
        mark = "*" if v.version == active else " "
        console.print(f"{mark} {v.version:<5} {v.status:<11} parent={v.parent or '-':<5} {v.created_at}  {v.notes}")


@policy_app.command("activate")
def policy_activate(version: str):
    """Make a policy version active (instant rollback)."""
    from app.policy.store import PolicyStore

    PolicyStore().activate(version)
    console.print(f"{version} is now active. New conversations will use it.")


@policy_app.command("approve")
def policy_approve(version: str):
    """Approve a candidate that passed the gate in a --review loop: it goes live."""
    from app.policy.store import PolicyStore

    store = PolicyStore()
    try:
        store.approve(version)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{version} approved and live.[/green] New conversations use it. "
                  f"Roll back any time: python -m app.cli policy activate {store.get(version).parent}")


@policy_app.command("reject")
def policy_reject(version: str):
    """Reject a candidate; the live policy is unchanged."""
    from app.policy.store import PolicyStore

    try:
        PolicyStore().reject(version)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(1)
    console.print(f"{version} rejected. The live policy is unchanged.")


@policy_app.command("diff")
def policy_diff(old: str, new: str):
    """Show the diff between two policy versions."""
    from app.policy.store import PolicyStore

    console.print(escape(PolicyStore().diff(old, new) or "(no differences)"))


if __name__ == "__main__":
    app()
