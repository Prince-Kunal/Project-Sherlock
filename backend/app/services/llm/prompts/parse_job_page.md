---
version: 1
---
# Task: read a job posting web page

## Purpose
A user pasted the URL of a job posting from a company careers page. Extract the posting's basic facts
so it can be added to their job feed. The page text was extracted automatically and may include
navigation or footer noise.

## Output (JSON only)
`{"is_job_posting", "company", "title", "location", "remote", "employment_type"}`
- `is_job_posting`: false if the page is not a single job posting (a list of jobs, a blog post, an
  error page, a login wall). Then the other fields may be null.
- `company`: the hiring company's name.
- `title`: the role title exactly as written.
- `location`: as written (e.g. "Bengaluru, India", "Remote - India"), or null.
- `remote`: true if remote work is offered, false if explicitly onsite/hybrid only, null if unclear.
- `employment_type`: "internship", "full_time", "part_time", "contract", or null if unclear.

## Hard rules
1. Only use what the page says. Never guess a company, title or location.
2. Output JSON only.

## Example
Page title: `Backend Intern - Acme Robotics`
Page text: `Backend Intern. Bengaluru (Hybrid). Acme Robotics builds warehouse robots. 6-month internship...`
Output:
```json
{"is_job_posting": true, "company": "Acme Robotics", "title": "Backend Intern",
 "location": "Bengaluru", "remote": false, "employment_type": "internship"}
```

## Page
URL: {{url}}
Page title: {{page_title}}

```
{{page_text}}
```
