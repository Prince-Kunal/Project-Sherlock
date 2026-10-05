from app.workers.settings import WorkerSettings, poll_sources


def test_worker_registers_poll_sources_every_6_hours() -> None:
    [job] = WorkerSettings.cron_jobs
    assert job.name == "cron:poll_sources"
    assert job.coroutine is poll_sources
    assert job.hour == {0, 6, 12, 18}
    assert job.run_at_startup is False
