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


def test_worker_runs_sending_reply_and_follow_up_tasks() -> None:
    jobs = {j.name: j for j in WorkerSettings.cron_jobs}
    assert jobs["cron:schedule_and_send"].minute == set(range(0, 60, 5))  # every 5 min (PLAN.md §8)
    assert jobs["cron:check_replies"].minute == {11, 41}  # every 30 min
    assert jobs["cron:create_followups"].hour is None  # hourly; 08:00 in each user's timezone


def test_worker_runs_open_outreach_discovery_daily() -> None:
    names = {getattr(f, "__name__", None) or f.name for f in WorkerSettings.functions}
    assert {"discover_prospect_companies", "match_companies_for_users"} <= names
    job = next(j for j in WorkerSettings.cron_jobs if j.name == "cron:discover_prospect_companies")
    assert (job.hour, job.minute) == ({23}, 37)  # daily, before the 07:00 IST drafts
