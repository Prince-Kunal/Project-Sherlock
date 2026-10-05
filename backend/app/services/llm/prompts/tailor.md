---
version: 2
---
# Task: tailor a resume to one job by selecting, ordering and lightly rephrasing existing bullets

## Purpose
A student is asking someone at this company for a referral. The attached resume should put their most
relevant real experience first and fit on one page. You may only choose from what the resume already
says. A program checks your answer: anything new (a skill, number, tool or outcome) gets the whole
plan rejected.

## Input
- `job`: title, company, location and description (may be cut off).
- `resume`: the candidate's resume with an `id` on every bullet. Each bullet lists the `skills` it
  shows and whether it is `pinned` (must be kept). Personal details are removed.
- `feedback`: problems a checker found in your previous plan for this job, or "(none)".

## Output (JSON only)
- `section_order`: which sections to show and in what order, from "education", "experience",
  "projects", "skills", "achievements". A student usually leads with education or experience.
- `selected_bullet_ids`: every bullet worth showing for this job, **most relevant first** (this order
  also sets the order within each entry and of projects). Leave out only bullets that add nothing for
  this job. Don't cut for length: if the page overflows, the lowest-ranked bullets are dropped
  automatically. Include every `pinned` bullet of each section you show.
- `rephrasings`: optional `{bullet_id, text}` for selected bullets that read better for this job.
  Leave a bullet out of this list to keep it as written.
- `skills_to_show`: skills from the resume's skills (or bullet skills), most relevant first.
- `summary`: an adapted version of the resume's summary, or null to keep it (always null if the
  resume has no summary).
- `jd_keywords`: up to 15 must-have technical skills, tools, languages or frameworks from the job
  description, **spelled exactly as in the description** (e.g. "PostgreSQL", "React.js"). Include
  ones the candidate lacks; leave out soft skills and nice-to-haves.

## Hard rules for rephrasing
1. Keep the same facts. Never add a number, percentage, tool, technology, team size, user count or
   outcome that the original bullet doesn't state (naming the bullet's own project, role or company
   is fine). Never change a number.
2. You may use the job description's name for a skill only if that skill is in the bullet's `skills`
   list (e.g. the bullet's skills include "postgresql" and the job says "PostgreSQL").
3. Keep each bullet under 200 characters and no longer than 1.3× the original.
4. Use only ids from the input. Don't merge or split bullets.
5. If `feedback` lists problems, fix every one of them.

## Example
Bullet `{"id": "exp1-b2", "text": "Made the search API faster with Redis caching, cutting p95 latency by
30%", "skills": ["redis", "rest api"]}` for a job asking for "Redis" and "REST APIs" →
`{"bullet_id": "exp1-b2", "text": "Cut p95 latency of a REST API by 30% with Redis caching"}`.
Not allowed: "...by 40%" (changed number), "...with Redis and Kafka" (new tool).

## Job
```json
{{job}}
```

## Resume
```json
{{resume}}
```

## Feedback on your previous plan
{{feedback}}
