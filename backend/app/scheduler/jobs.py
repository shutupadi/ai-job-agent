"""
APScheduler daemon — runs twice a day in the configured TZ.

CLI:
  python -m app.scheduler.jobs daemon       # foreground scheduler loop
  python -m app.scheduler.jobs run-once     # execute pipeline immediately
"""

from __future__ import annotations

import signal
import sys

import typer
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.pipeline import run_pipeline
from app.utils.logger import log

cli = typer.Typer(help="Pipeline scheduler / runner")


def _make_cron(expr: str) -> CronTrigger:
    """Convert a 5-field cron expr to a CronTrigger in the configured TZ."""
    minute, hour, dom, month, dow = expr.split()
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=dom,
        month=month,
        day_of_week=dow,
        timezone=settings.tz,
    )


def _morning_run():
    log.info("Cron trigger: morning")
    try:
        run_pipeline(trigger="cron-morning")
    except Exception:
        log.exception("Morning pipeline crashed")


def _evening_run():
    log.info("Cron trigger: evening")
    try:
        run_pipeline(trigger="cron-evening")
    except Exception:
        log.exception("Evening pipeline crashed")


@cli.command()
def daemon():
    """Block forever, running the pipeline on schedule."""
    sched = BlockingScheduler(timezone=settings.tz)
    sched.add_job(
        _morning_run,
        _make_cron(settings.schedule_cron_morning),
        id="morning",
        replace_existing=True,
    )
    sched.add_job(
        _evening_run,
        _make_cron(settings.schedule_cron_evening),
        id="evening",
        replace_existing=True,
    )
    log.info(
        f"Scheduler started (tz={settings.tz}): "
        f"morning='{settings.schedule_cron_morning}' "
        f"evening='{settings.schedule_cron_evening}'"
    )

    def _shutdown(signum, frame):  # noqa: D401
        log.info(f"Caught signal {signum}; shutting down scheduler")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    sched.start()


@cli.command("run-once")
def run_once(trigger: str = typer.Option("manual", help="Trigger label to record.")):
    """Execute the pipeline once and exit."""
    rid = run_pipeline(trigger=trigger)
    typer.echo(f"Run {rid} finished")


if __name__ == "__main__":
    cli()
