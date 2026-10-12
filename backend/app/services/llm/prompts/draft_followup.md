---
version: 2
---
# Task: write a short follow-up to an email that got no reply

## Purpose
A student emailed someone (asking for a referral for a job, or, with no job posted, asking whether
the team takes people) and heard nothing back. This one follow-up goes in
the same thread. It must be short, friendly and easy to answer, and read like the student typed it.
There is no second follow-up. A program checks your answer.

## Input
- `inputs.original`: the email that was sent (greeting, body and signature).
- `inputs.days_since`: how many days ago it was sent.
- `inputs.job_title` and `inputs.company`. `job_title` is null when the first email wasn't about a
  job (`inputs.campaign` is "open").
- `inputs.campaign`: "job" (the first email asked about a posted job) or "open" (no job was posted).
- `inputs.new_opening`: null, or the title of a job the company has posted **since** the first
  email. When it's set, this follow-up mentions that the company has now posted that opening by its
  title, and asks for a referral for it (or a pointer to whoever's hiring for it).
- `inputs.recipient_role`: founder, eng_manager, engineer, recruiter or other.

## Output (JSON only)
- `body`: plain text, 20 to 50 words. A light nudge: say you're following up on the earlier email
  (about the role, or about the team when there was no role), make the ask again in a simpler,
  smaller form (e.g. "even a pointer to the right person would help"), and stop. Don't repeat the
  whole pitch.

## Never use
"Just circling back", "bumping this to the top of your inbox", "I hope this finds you well",
"I wanted to follow up", "as per my last email", "gentle reminder", guilt ("I know you're busy but"),
enthusiasm words (excited, passionate, eager), buzzwords, or dashes (— or –) as punctuation.

## Hard rules
1. Leave out the greeting and the sign-off: they are added automatically, with an opt-out line.
2. Don't add any fact about the candidate that isn't in `inputs.original`.
3. No placeholders, no emoji, no markdown.
4. When `campaign` is "open" and `new_opening` is null, no job is posted: never mention a role,
   position, opening or posting as if one existed.
5. When `new_opening` is set, name it exactly as given.

## Examples
```json
{"body": "Following up on my note last week about the backend intern role. If a referral isn't something you can do, even pointing me to whoever's hiring for it would help a lot."}
```
With `new_opening` "Backend Engineering Intern":
```json
{"body": "Since I wrote, I saw Ledgerline posted a Backend Engineering Intern opening, which is the kind of work I mentioned. Would you be open to referring me for it, or pointing me to whoever's hiring?"}
```

## Inputs
```json
{{inputs}}
```

## Feedback on your previous answer
{{feedback}}
