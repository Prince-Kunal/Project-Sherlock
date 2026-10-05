---
version: 1
---
# Task: tag resume bullets with the skills they show

## Purpose
Each resume bullet carries a list of skills it demonstrates. Later steps use these tags to decide
which bullets match a job, and to make sure a rephrased bullet never claims a skill it didn't show.
So tags must be supported by the bullet's own text.

## Input
A numbered list of bullets (JSON array of `{"index", "text"}`), plus the person's skills section for
reference spelling.

## Output (JSON only)
An array with one object per input bullet, in the same order: `{"index": <int>, "skills": [<string>]}`.
- Skills are lowercase: languages, frameworks, tools, platforms, methods (e.g. "python", "postgresql",
  "computer vision", "ros 2", "data structures").
- Include a skill only if the bullet's text clearly shows it. A bullet with no technical skill gets [].

## Hard rules
1. Never tag a skill that the bullet's text does not support, even if it's in the skills section.
2. One output object per input bullet, same `index` values.
3. Output JSON only.

## Example
Input bullets:
```json
[{"index": 0, "text": "Built a Flask API backed by PostgreSQL for 2k daily users"},
 {"index": 1, "text": "Led a team of 5 volunteers at the college fest"}]
```
Output:
```json
[{"index": 0, "skills": ["flask", "postgresql", "rest api"]}, {"index": 1, "skills": []}]
```

## Skills section
```
{{skills_section}}
```

## Bullets
```json
{{bullets}}
```
