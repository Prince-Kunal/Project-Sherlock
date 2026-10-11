from app.workers.settings import WorkerSettings, poll_sources


def test_worker_registers_poll_sources_every_6_hours() -> None:
    job = next(j for j in WorkerSettings.cron_jobs if j.name == "cron:poll_sources")
    assert job.coroutine is poll_sources
    assert job.hour == {0, 6, 12, 18}
    assert job.run_at_startup is False


def test_worker_registers_matching_tasks() -> None:
    names = {getattr(f, "__name__", None) or f.name for f in WorkerSettings.functions}
    assert {"poll_sources", "embed_new_jobs", "match_jobs_for_users"} <= names
    expire = next(j for j in WorkerSettings.cron_jobs if j.name == "expire_matches")
    assert expire.hour == {1}


def test_worker_runs_build_daily_drafts_hourly() -> None:
    names = {getattr(f, "__name__", None) or f.name for f in WorkerSettings.functions}
    assert "build_daily_drafts" in names
    job = next(j for j in WorkerSettings.cron_jobs if j.name == "cron:build_daily_drafts")
    assert job.hour is None  # every hour: each user's batch runs when it's 07:00 for them
    assert job.minute == {2}
