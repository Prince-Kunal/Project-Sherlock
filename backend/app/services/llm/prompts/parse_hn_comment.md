---
version: 1
---
# Task: extract job postings from "Ask HN: Who is hiring?" comments

## Purpose
Each comment is one company's hiring post, usually starting with a header line like
`Company | Role(s) | Location | REMOTE/ONSITE | Full-time | URL`. Turn each comment into one entry per
distinct role so people can find and apply to them. Accuracy matters more than coverage.

## Input
A JSON array of comments: `{"comment_id", "text"}`. Email addresses and phone numbers were replaced
with `[email]` / `[phone]`; ignore them.

## Output (JSON only)
An array of jobs. Each job: `comment_id` (from the input), `company`, `title` (one role per entry;
split "Senior/Staff Backend Engineer, Frontend Engineer" into separate entries; at most 5 per
comment), `location` (as written, e.g. "Bengaluru, India" or "Remote (US)"; null if not stated),
`remote` (true if remote work is offered, false if explicitly onsite-only, null if unclear),
`employment_type` ("internship", "full_time", "part_time", "contract", or null if unclear),
`url` (the application or careers URL from the comment, or null).

## Hard rules
1. Only use what the comment says. Never invent companies, roles, locations or URLs.
2. Skip comments that are not hiring posts (questions, replies, complaints): output nothing for them.
3. "Intern", "internship", "new grad" roles: use the role name as written.
4. Output JSON only.

## Example
Input:
```json
[{"comment_id": 101, "text": "Acme Robotics | Backend Engineer, ML Intern | Bengaluru, India | ONSITE | https://acme.example/jobs\nWe build warehouse robots... Email [email]"}]
```
Output:
```json
[{"comment_id": 101, "company": "Acme Robotics", "title": "Backend Engineer", "location": "Bengaluru, India",
  "remote": false, "employment_type": "full_time", "url": "https://acme.example/jobs"},
 {"comment_id": 101, "company": "Acme Robotics", "title": "ML Intern", "location": "Bengaluru, India",
  "remote": false, "employment_type": "internship", "url": "https://acme.example/jobs"}]
```

## Comments
```json
{{comments}}
```
