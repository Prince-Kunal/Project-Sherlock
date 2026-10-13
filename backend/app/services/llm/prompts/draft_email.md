---
version: 4
---
# Task: write the middle of a short email asking someone for a referral

## Purpose
A student is emailing one person at a company to ask for a referral for an opening (or to be
pointed to the right person). People who get these emails can spot machine-written text instantly,
and they delete it. Your email has to read like the student typed it themselves in five minutes:
plain, specific, a little informal, and short. A program checks your answer and rejects it if a
rule below is broken.

## Input
- `inputs.job`: the job title, company and location.
- `inputs.context_sentences`: sentences from the job posting, and sometimes from the company's own
  description, website or latest blog post. Use the one closest to the candidate's work to decide
  which of their work to mention. Sentences from the company's site or blog steer the choice the
  same way; never say the candidate read them (Sherlock did, not the candidate).
- `inputs.recipient`: the person's title, their role category and how to pitch it to them.
- `inputs.about_me`: a line or two the candidate wrote about themselves.
- `inputs.highlights`: the candidate's two most relevant resume bullets for this job.
- `hint`: a request from the candidate for this draft (e.g. "mention I can start in May"), or
  "(none)". Follow it unless it breaks a rule below.
- `feedback`: problems a checker found in your previous draft, or "(none)".

## Output (JSON only)
- `subject`: what a person would type: short and plain, e.g. "Backend intern role at Ledgerline"
  or "Referral for the backend internship?". Not "X: Referral Request", not "Quick question".
- `body`: plain text, 50 to 90 words, one or two short paragraphs. It needs:
  1. what the candidate wants (a referral for this role) early, not after a warm-up;
  2. one or two concrete things they've done that matter for this job, retold the way you'd say
     them out loud to someone, not in resume wording;
  3. an easy way out of the ask (e.g. "or point me to whoever's hiring for it");
  4. a mention that the resume is attached.
- `personalization_source`: the context sentence that decided which work you mention,
  **copied character for character** from `inputs.context_sentences`. It is only for the checker;
  don't quote or paraphrase it in the body.

## How real people write these
- They get to the point. The ask is in the first or second sentence.
- They use contractions (I'm, I've, it's) and ordinary words. Sentences vary in length; some are
  short.
- They mention the posting by name only ("the backend intern role"). They never summarise it back
  to the person who wrote it ("since your team is improving its CI pipeline…"): the recipient knows
  what their own job post says.
- They don't explain why they fit ("this seemed relevant", "this matches what I do", "which
  connects to your work"). They say what they did and let the reader connect it.
- They follow the shape given under "Shape of this email" below, in their own words. Two emails
  with the same shape still never share sentences.
- They describe their own work casually and specifically: "I built a parser and put it behind a
  REST API" rather than "Exposed the parser as a REST API, CLI and web visualiser".
- They don't perform enthusiasm or flatter. One plain sentence of genuine interest at most.

## Never use (the checker rejects these)
- Openers: "I hope this email finds you well", "I came across", "I noticed that X is looking for",
  "I'm writing to", "I wanted to reach out", "As a third-year student, …" (any "As a …," start).
- Enthusiasm and flattery: excited, thrilled, passionate, eager, keen to, "would love the
  opportunity", "stood out", "caught my eye", "resonated", "impressed by".
- Explaining the fit: "since your team…", "seeing that you…", "this seemed relevant", "this
  matches", "connects to", "directly relevant", "relevant experience", "hands-on experience".
- Buzzwords: leverage, delve, align with, "great fit", "perfect fit", "well-suited", skill set,
  hone, showcase, foster, cutting-edge, innovative, fast-paced, journey, landscape, seamless,
  "add value", "make an impact", "contribute to your team".
- Essay words: furthermore, moreover, additionally, "not only … but also".
- Stock closers: "thank you for your time and consideration", "I look forward to hearing from you",
  "at your earliest convenience", "don't hesitate", "feel free to".
- Dashes as punctuation (— or –). Use a full stop or a comma.
- Eight or more words in a row copied from the job posting or from `highlights`.

## Hard rules
1. Leave out the greeting ("Hi …") and the sign-off ("Best, …", the name, links): they are added
   automatically, together with an opt-out line.
2. Never invent anything about the candidate: no skills, numbers, companies, feelings ("work I
   enjoy") or experiences beyond `highlights` and `about_me`. Keep every number exactly as given. Never claim
   to know the recipient, to have used the product, or to follow the company.
3. No placeholders such as [Name] or {company}, no emoji, no markdown, no bullet lists.
4. Pitch it as `inputs.recipient.tone` says.
5. If `feedback` lists problems, fix every one of them and keep everything else natural.

## Examples (each one is fine; don't reuse their wording or structure)
To an engineering manager, highlights about a Django API on PostgreSQL and a CI test suite:

```json
{
  "subject": "Backend intern role at Ledgerline",
  "body": "I'm applying for the backend intern role and wanted to ask if you'd refer me. Most of what I've built is Python on Postgres, including a Django API for a college project, and I set up a 90-question test set that runs in CI and stops merges when accuracy drops.\n\nIf you're not the right person for this, a pointer to whoever's hiring would help a lot. Resume's attached.",
  "personalization_source": "Build and maintain REST APIs in Python (Django) backed by PostgreSQL."
}
```

To a founder of a small company, shorter:

```json
{
  "subject": "Referral for the platform internship?",
  "body": "Would you be open to referring me for the platform internship? I've spent the last year writing Go services and running them on a small Kubernetes cluster I set up myself, so this is close to what I already do for fun. My resume's attached in case it's useful.",
  "personalization_source": "You will own our internal platform: Kubernetes clusters, Terraform modules and the Go services that provision them."
}
```

What NOT to write (every part of this is a giveaway):

"I hope this email finds you well! I came across the Backend Engineering Intern position and was
excited to see that Ledgerline is looking to build REST APIs in Python. As a passionate computer
science student, I have honed my skills in backend development, which aligns perfectly with your
team's needs. I would love the opportunity to contribute to your innovative team. Thank you for
your time and consideration."

## Shape of this email
{{style}}

## Inputs
```json
{{inputs}}
```

## Hint from the candidate
{{hint}}

## Feedback on your previous draft
{{feedback}}
