---
version: 1
---
# Task: tailor a resume for a cold email to a company with no job posted, by selecting, ordering and lightly rephrasing existing bullets

## Purpose
A student is emailing someone at a company that hasn't posted an opening, asking whether the team
takes interns or would talk to them. The attached resume should put the real experience closest to
what this company builds first and fit on one page. You may only choose from what the resume already
says. A program checks your answer: anything new (a skill, number, tool or outcome) gets the whole
plan rejected.

## Input
- `brief`: the roles the student wants, the company's name, what it does in its own words (from its
  directory entry and website, may be cut off) and an `angle`: one sentence on where the student's
  work overlaps with the company.
- `resume`: the candidate's resume with an `id` on every bullet. Each bullet lists the `skills` it
  shows and whether it is `pinned` (must be kept). Personal details are removed.
- `feedback`: problems a checker found in your previous plan for this company, or "(none)".

## Output (JSON only)
- `section_order`: which sections to show and in what order, from "education", "experience",
  "projects", "skills", "achievements". A student usually leads with education or experience.
- `selected_bullet_ids`: every bullet worth showing to this company, **most relevant first** (this
  order also sets the order within each entry and of projects); the bullets behind the `angle` come
  first. Leave out only bullets that add nothing here. Don't cut for length: if the page overflows,
  the lowest-ranked bullets are dropped automatically. Include every `pinned` bullet of each section
  you show.
- `rephrasings`: optional `{bullet_id, text}` for selected bullets that read better for this company.
  Leave a bullet out of this list to keep it as written.
- `skills_to_show`: skills from the resume's skills (or bullet skills), most relevant first.
- `summary`: an adapted version of the resume's summary, or null to keep it (always null if the
  resume has no summary). Never mention a specific opening or role at the company: none is posted.
- `jd_keywords`: up to 15 technical skills, tools, languages or frameworks the company's text names,
  **spelled exactly as in that text** (e.g. "PostgreSQL", "React.js"). Empty if it names none.

## Hard rules for rephrasing
1. Keep the same facts. Never add a number, percentage, tool, technology, team size, user count or
   outcome that the original bullet doesn't state (naming the bullet's own project, role or company
   is fine). Never change a number.
2. You may use the company text's name for a skill only if that skill is in the bullet's `skills`
   list (e.g. the bullet's skills include "postgresql" and the company writes "PostgreSQL").
3. Keep each bullet under 200 characters and no longer than 1.3× the original.
4. Use only ids from the input. Don't merge or split bullets.
5. If `feedback` lists problems, fix every one of them.

## Example
Bullet `{"id": "exp1-b2", "text": "Made the search API faster with Redis caching, cutting p95 latency by
30%", "skills": ["redis", "rest api"]}` for a company that mentions "Redis" and "REST APIs" →
`{"bullet_id": "exp1-b2", "text": "Cut p95 latency of a REST API by 30% with Redis caching"}`.
Not allowed: "...by 40%" (changed number), "...with Redis and Kafka" (new tool).

## Brief
```json
{{brief}}
```

## Resume
```json
{{resume}}
```

## Feedback on your previous plan
{{feedback}}
