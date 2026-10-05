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

export type EmploymentType =
  "internship" | "full_time" | "part_time" | "contract";

export type Job = {
  id: string;
  title: string;
  company: { id: string; name: string; domain: string | null };
  location: string | null;
  remote: boolean | null;
  employment_type: EmploymentType | null;
  url: string | null;
  source: "greenhouse" | "lever" | "ashby" | "adzuna" | "hn" | "manual";
  posted_at: string | null;
  first_seen_at: string;
  effective_date: string;
  age_days: number;
};

export type JobFeed = { items: Job[]; total: number; max_age_days: number };

export type JobFilters = {
  max_age_days?: number;
  employment_type?: EmploymentType;
  remote?: boolean;
  q?: string;
  limit: number;
  offset: number;
};

export type MatchStatus =
  "new" | "shortlisted" | "hidden" | "in_pipeline" | "expired";

export type VerificationStatus = "valid" | "accept_all" | "unknown" | "invalid";

export type Contact = {
  id: string;
  full_name: string;
  title: string | null;
  email: string;
  role_category: "founder" | "eng_manager" | "engineer" | "recruiter" | "other";
  verification_status: VerificationStatus;
  email_source: "hunter" | "apollo" | "manual" | "pattern" | "hn";
};

export type Outreach = {
  id: string;
  status: string;
  campaign_type: "job" | "open";
  job_id: string | null;
  company: { id: string; name: string; domain: string | null };
  contact: Contact | null;
  failure_reason: string | null;
  failure_message: string | null;
  created_at: string;
};

export type HunterKeyStatus = {
  configured: boolean;
  verified_at: string | null;
  owner_fallback_allowed: boolean;
  searches_this_month: number;
  monthly_limit: number;
};

export type Match = {
  id: string;
  job: Job;
  fit_score: number | null;
  embedding_score: number | null;
  matched_skills: string[];
  missing_skills: string[];
  reasoning: string;
  status: MatchStatus;
  created_at: string;
  outreach: Outreach | null;
};

export type MatchFeed = {
  items: Match[];
  total: number;
  min_score: number;
  scoring: {
    llm_key_configured: boolean;
    calls_last_24h: number;
    daily_limit: number;
  };
};

export type MatchFilters = {
  status: "active" | MatchStatus;
  min_score?: number;
  limit: number;
  offset: number;
};

export type ResumeChange = {
  bullet_id: string;
  change: "added" | "removed" | "reordered" | "rephrased";
  before: string | null;
  after: string | null;
};

export type TailorPreview = {
  match_id: string;
  pdf_url: string;
  filename: string;
  section_order: string[];
  diff: ResumeChange[];
  keyword_coverage: NonNullable<AtsReport["keyword_coverage"]>;
  ats: AtsReport;
  bullets_dropped_to_fit: number;
};
