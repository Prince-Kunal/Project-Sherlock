// Mirrors backend/app/schemas (resume.py, preferences.py, settings.py) and ats_check.AtsReport.

export type Link = { label: string; url: string };

export type Basics = {
  name: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  links: Link[];
};

export type Bullet = {
  id: string; // "" for new bullets; the server assigns one on save
  text: string;
  skills: string[];
  pinned: boolean;
};

/** "YYYY-MM", "YYYY", "present", or null. */
export type ResumeDate = string | null;

export type Education = {
  id: string;
  institution: string;
  degree: string | null;
  field: string | null;
  location: string | null;
  start: ResumeDate;
  end: ResumeDate;
  gpa: string | null;
  bullets: Bullet[];
};

export type Experience = {
  id: string;
  org: string;
  role: string;
  location: string | null;
  start: ResumeDate;
  end: ResumeDate;
  bullets: Bullet[];
};

export type Project = {
  id: string;
  name: string;
  link: string | null;
  tech: string[];
  start: ResumeDate;
  end: ResumeDate;
  bullets: Bullet[];
};

export type MasterResume = {
  basics: Basics;
  summary: string | null;
  education: Education[];
  experience: Experience[];
  projects: Project[];
  skills: Record<string, string[]>;
  achievements: Bullet[];
};

export type ResumeOut = { version: number; data: MasterResume };

export type ResumeVersion = {
  version: number;
  is_current: boolean;
  created_at: string;
};

export type AtsReport = {
  passed: boolean;
  failures: string[];
  page_count: number;
  keyword_coverage: {
    score: number;
    matched: string[];
    missing: string[];
  } | null;
};

export type Preferences = {
  target_roles: string[];
  employment_types: ("internship" | "full_time")[];
  locations: string[];
  remote_ok: boolean;
  company_stages: ("startup" | "mid" | "large")[];
  min_fit_score: number;
  max_job_age_days: number;
  daily_draft_batch: number;
  open_outreach_share: number;
  daily_send_cap: number;
  followup_after_days: number;
  send_window_start: string; // "HH:MM:SS"
  send_window_end: string;
  paused: boolean;
  about_me: string;
  timezone: string;
};

export type LLMKeyStatus = {
  configured: boolean;
  provider: string | null;
  verified_at: string | null;
  owner_fallback_allowed: boolean;
  notice: string;
};
