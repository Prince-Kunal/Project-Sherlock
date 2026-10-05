---
version: 2
---
# Task: parse a resume into structured JSON

## Purpose
Convert the plain text of one resume into a structured record. The record becomes the person's
"master resume": every later step may only use facts that appear in it, so it must be complete and
faithful. Do not improve, summarise or invent anything.

## Input
The resume text below was extracted from a PDF or Word file, so line breaks, columns and bullet
glyphs may be messy. Email addresses and phone numbers have been replaced with `[email]` and
`[phone]` on purpose; ignore them. A list of hyperlink targets found in the file follows the text;
some links in the visible text are hidden behind words such as "GitHub" or "LinkedIn".

## Output (JSON only, matching the provided schema)
- `basics`: `name` (as written, but in normal capitalisation if the resume uses ALL CAPS),
  `location`: the person's own city/region/country only if the resume states it in the header or
  contact line; never a street address, and never inferred from a school or employer (null otherwise),
  `links`: profile or portfolio links that belong to the person (LinkedIn, GitHub profile, LeetCode,
  personal website), each with a short `label` and the full `url`. Use the hyperlink targets list.
- `summary`: the summary/objective paragraph verbatim, or null.
- `education`: one item per school/degree. `degree` (e.g. "B.Tech"), `field` (e.g. "Information
  Technology"), `gpa` as written (e.g. "9.21", "8.98 / 10.0", "96.6%"). Coursework or notes become
  `bullets`.
- `experience`: jobs, internships, open-source contribution roles, research positions.
  `role`, `org`, `location`, dates, `bullets`.
- `projects`: `name`, `link` (the project's own URL if one is given, from the text or the hyperlink
  targets), `tech` (the listed tech stack, as written), dates, `bullets`.
- `skills`: one group per category line, e.g. `{"category": "Languages", "items": ["C", "C++", "Python"]}`.
  Keep the person's spelling. Split comma- or pipe-separated lists into items.
- `achievements`: every other bullet-worthy line: awards, certifications, publications, leadership,
  extracurricular activities, competitive programming. When such an entry has a heading line (title,
  organisation, venue, dates) followed by description bullets, output one item for the heading line,
  with its dates exactly as written, and one item per description bullet. Never drop the dates.

Each bullet has `text` and `skills`:
- `text`: the bullet copied verbatim. Only fix extraction damage: join lines broken mid-sentence,
  remove leading bullet glyphs (•, ●, -, ▪), and normalise spacing. Keep numbers, names and wording
  exactly. Never shorten, merge, split or rephrase.
- `skills`: the concrete technical skills the bullet itself shows: languages, frameworks, tools,
  platforms, algorithms or methods (e.g. "flask", "postgresql", "computer vision", "dynamic time
  warping"). Lowercase. Not generic words like "backend", "app", "dashboard" or "schema". Only skills
  supported by that bullet's text; [] if none.

Dates: `start` and `end` as `"YYYY-MM"` when a month is given, `"YYYY"` when only a year is given,
`"present"` for ongoing ("Present", "Ongoing", "Now", "Current"); an entry marked only "Ongoing"
gets `start` null and `end` "present". A single date (e.g. a project dated
"June 2026") goes in `start` with `end` null. Use null when no date is given. Never guess a month.

## Hard rules
1. Use only information in the resume text and hyperlink list. Never invent employers, dates,
   numbers, skills or links.
2. Every bullet, entry and skill in the resume must appear somewhere in the output. Nothing is dropped.
3. Copy bullet text verbatim (rule above). Do not add metrics, adjectives or outcomes.
4. Do not output email addresses, phone numbers or street addresses anywhere.
5. Output JSON only. No commentary.

## Example
Resume text:
```
PRIYA NAIR
[phone] | [email] | Kochi, India | GitHub
EDUCATION
Example College, Kochi   2023 – 2027
B.E. Computer Science   CGPA: 8.4
PROJECTS
Trail Mapper – Hiking Route Planner   March 2026
Tech Stack: Python, Flask, Leaflet
• Built a route planner that suggests trails using
elevation data from 3 public APIs.
SKILLS
Languages: Python, Java | Tools: Git
ACHIEVEMENTS
• Winner, college hackathon 2025
```
Hyperlink targets:
```
- https://github.com/priya-nair
```
Output:
```json
{
  "basics": {"name": "Priya Nair", "location": "Kochi, India",
             "links": [{"label": "GitHub", "url": "https://github.com/priya-nair"}]},
  "summary": null,
  "education": [{"institution": "Example College", "degree": "B.E.", "field": "Computer Science",
                 "location": "Kochi", "start": "2023", "end": "2027", "gpa": "8.4", "bullets": []}],
  "experience": [],
  "projects": [{"name": "Trail Mapper – Hiking Route Planner", "link": null,
                "tech": ["Python", "Flask", "Leaflet"], "start": "2026-03", "end": null,
                "bullets": [{"text": "Built a route planner that suggests trails using elevation data from 3 public APIs.",
                             "skills": ["python", "flask", "rest api"]}]}],
  "skills": [{"category": "Languages", "items": ["Python", "Java"]},
             {"category": "Tools", "items": ["Git"]}],
  "achievements": [{"text": "Winner, college hackathon 2025", "skills": []}]
}
```

## Resume text
```
{{resume_text}}
```

## Hyperlink targets
```
{{links}}
```
