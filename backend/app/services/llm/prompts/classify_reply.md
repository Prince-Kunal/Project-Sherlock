---
version: 1
---
# Task: does this reply ask not to be contacted again?

## Purpose
A student emailed someone asking for a referral. This is the person's reply, with the quoted
original removed. Decide whether they are asking not to be emailed again (an opt-out), or replying
in any other way (yes, no, maybe, "not hiring right now", "talk to X", questions).

## Input
- `reply`: the new text of the reply.

## Output (JSON only)
- `intent`: "opt_out" if they ask not to be contacted again, otherwise "reply".

## Rules
1. "No thanks" or "we're not hiring" on its own is a "reply": it answers the question, it doesn't
   ask to stop. "Please stop emailing me", "don't contact me", "remove me" are "opt_out".
2. If they clearly don't want further emails, even politely, choose "opt_out".

## Example
"Thanks for reaching out, but we have no openings right now. Good luck!" → {"intent": "reply"}
"Please stop, I get too many of these." → {"intent": "opt_out"}

## Reply
{{reply}}
