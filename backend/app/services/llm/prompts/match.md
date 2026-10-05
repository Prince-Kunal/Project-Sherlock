---
version: 2
---
# Task: score how well each job fits one candidate

## Purpose
A student or early-career candidate wants referrals for jobs that genuinely fit them. Score each job
so only relevant ones reach them. Be strict and honest: a wrong "great fit" wastes a referral ask.

## Input
- `candidate`: target roles, wanted employment types and locations, whether remote is OK, their
  skills (canonical names), and a condensed resume (no personal details).
- `jobs`: an array of `{job_ref, title, company, location, remote, employment_type, description}`.
  `employment_type` and `remote` may be null (unknown). Descriptions may be cut off.

## Output (JSON only)
An array with exactly one entry per input job, in any order:
- `job_ref`: copied exactly from the input.
- `fit_score`: integer 0–100, using the scale below.
- `employment_type`: what the job is (not what the candidate wants):
  - "internship" for internships, co-ops, apprenticeships, trainee and summer student roles;
  - "contract" for contract, freelance, temporary or part-time work;
  - "full_time" for any other regular role (e.g. "Software Engineer", "Account Executive"), even
    when the posting doesn't say "full-time";
  - "unknown" only when it really could be either an internship or a full-time role (e.g.
    "Software Engineer (graduates and interns)").
- `matched_skills`: skills from the candidate's `skills` list that this job asks for or clearly uses.
  Use the candidate's spelling. Never list a skill the candidate doesn't have.
- `missing_must_haves`: up to 6 short names of required skills or qualifications the job states that
  the candidate lacks (e.g. "kubernetes", "3+ years experience", "go"). Leave out nice-to-haves.
- `reasoning`: at most 2 short sentences addressed to the candidate ("You ..."): the strongest reason
  it fits and the biggest gap.

## Scale
- 85–100: the role matches a target role and the candidate's level, and they have most must-haves.
- 70–84: a good fit with one or two learnable gaps.
- 50–69: related work, but clear gaps or a level mismatch.
- 0–49: a different field, or it needs far more experience than the candidate has (e.g. "senior",
  "staff", "5+ years"), or the candidate can't work where the job requires (e.g. "Remote - US only"
  for someone in India).

## Hard rules
1. Judge only from the given text. Don't assume skills or experience that aren't stated.
2. A job whose employment type isn't one the candidate wants still gets an honest score; just report
   its `employment_type` correctly.
3. Unknown fields (null location, cut-off description) are not a penalty by themselves.
4. One entry per job, `job_ref` copied exactly. JSON only.

## Example
Candidate skills include "python", "fastapi", "postgresql"; target role "Backend Intern".
Job `{"job_ref": "a1b2c3d4", "title": "Backend Engineering Intern", "description": "Build APIs in
Python and PostgreSQL. Experience with Docker is required."}` →
```json
[{"job_ref": "a1b2c3d4", "fit_score": 82, "employment_type": "internship",
  "matched_skills": ["python", "postgresql"], "missing_must_haves": ["docker"],
  "reasoning": "You've built Python APIs on PostgreSQL, which is the core of this internship. Docker is required and isn't on your resume."}]
```

## Candidate
```json
{{candidate}}
```

## Jobs
```json
{{jobs}}
```
