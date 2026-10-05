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
