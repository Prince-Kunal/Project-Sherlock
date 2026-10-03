from app.workers.settings import WorkerSettings, noop


async def test_noop_cron_logs_summary() -> None:
    assert await noop({}) == {"processed": 0, "succeeded": 0, "failed": 0}


def test_worker_registers_noop_cron() -> None:
    assert [job.name for job in WorkerSettings.cron_jobs] == ["cron:noop"]
