---
version: 1
---
# Task: write a short follow-up to a referral email that got no reply

## Purpose
A student emailed someone asking for a referral and heard nothing back. This one follow-up goes in
the same thread. It must be short, friendly and easy to answer, and read like the student typed it.
There is no second follow-up. A program checks your answer.

## Input
- `inputs.original`: the email that was sent (greeting, body and signature).
- `inputs.days_since`: how many days ago it was sent.
- `inputs.job_title` and `inputs.company`.
- `inputs.recipient_role`: founder, eng_manager, engineer, recruiter or other.

## Output (JSON only)
- `body`: plain text, 20 to 50 words. A light nudge: say you're following up on the earlier email
  about the role, make the ask again in a simpler, smaller form (e.g. "even a pointer to the right
  person would help"), and stop. Don't repeat the whole pitch.

## Never use
"Just circling back", "bumping this to the top of your inbox", "I hope this finds you well",
"I wanted to follow up", "as per my last email", "gentle reminder", guilt ("I know you're busy but"),
enthusiasm words (excited, passionate, eager), buzzwords, or dashes (— or –) as punctuation.

## Hard rules
1. Leave out the greeting and the sign-off: they are added automatically, with an opt-out line.
2. Don't add any fact about the candidate that isn't in `inputs.original`.
3. No placeholders, no emoji, no markdown.

## Example
```json
{"body": "Following up on my note last week about the backend intern role. If a referral isn't something you can do, even pointing me to whoever's hiring for it would help a lot."}
```

## Inputs
```json
{{inputs}}
```

## Feedback on your previous answer
{{feedback}}
