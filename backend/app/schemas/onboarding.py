from pydantic import BaseModel


class OnboardingStatus(BaseModel):
    """Where a new user is in the onboarding flow (PLAN.md Phase 9). Each flag is read from the data,
    so the flow resumes at the right step after a reload."""

    google_sign_in: bool  # whether this server has Google sign-in at all (else the Gmail step is skipped)
    gmail: bool
    llm_key: bool  # their own Gemini key, or the owner's when the fallback is allowed
    hunter_key: bool
    resume: bool
    preferences: bool  # target roles and employment type chosen
    completed: bool
    first_run_queued: bool | None = None  # set by POST /onboarding/complete


class OnboardingCompleteIn(BaseModel):
    start: bool = True  # queue the first run (score jobs, then today's drafts); False = "finish later"
