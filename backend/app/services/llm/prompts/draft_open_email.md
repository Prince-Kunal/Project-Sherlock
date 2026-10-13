---
version: 2
---
# Task: write the middle of a short cold email to someone at a company that hasn't posted a job

## Purpose
A student is emailing one person at a company they'd like to work at. **No opening is posted**: the
email must not claim or hint that one exists. Instead it makes a small, easy ask that depends on who
the person is (see `inputs.recipient.ask`). People who get these delete anything that reads as
machine-written, so it has to sound like the student typed it in five minutes: plain, specific, a
little informal, and short. A program checks your answer and rejects it if a rule below is broken.

## Input
- `inputs.company`: the company's name.
- `inputs.context_sentences`: sentences from the company's own description and website. Use the
  one closest to the candidate's work to decide which of their work to mention.
- `inputs.angle`: one sentence on where the candidate's work overlaps with what the company does.
- `inputs.looking_for`: what the candidate is after (e.g. "a backend internship").
- `inputs.recipient`: the person's title, their role category, how to pitch it, and `ask`: the one
  question to ask them.
- `inputs.about_me`: a line or two the candidate wrote about themselves.
- `inputs.highlights`: the candidate's two most relevant resume bullets for this company.
- `hint`: a request from the candidate for this draft, or "(none)". Follow it unless it breaks a rule.
- `feedback`: problems a checker found in your previous draft, or "(none)".

## Output (JSON only)
- `subject`: short and plain, the way a person would type it, e.g. "Backend internships at
  Ledgerline?" or "Question about the payments team". Not "Opportunity", not "Quick question".
- `body`: plain text, 50 to 90 words, one or two short paragraphs. It needs:
  1. one or two concrete things the candidate has done that relate to what the company builds,
     retold the way you'd say them out loud, not in resume wording;
  2. the ask from `inputs.recipient.ask`, once, plainly;
  3. an easy way out (e.g. "or point me to whoever handles hiring");
  4. a mention that the resume is attached.
- `personalization_source`: the context sentence that decided which work you mention,
  **copied character for character** from `inputs.context_sentences`. It's only for the checker;
  don't quote or paraphrase it in the body.

## No opening exists (the checker rejects these)
- Never say or imply there's a job, role, position, opening, vacancy or posting: no "your opening",
  "the role you posted", "the position", "the backend intern role", "you're hiring", "applying for",
  "open role". Ask whether the team takes people, or about future openings, instead.
- Don't name a job title as if it were advertised. "I'm looking for a backend internship" is fine;
  "the Backend Intern role" is not.

## How real people write these
- They follow the shape given under "Shape of this email" below, in their own words.
- Contractions and ordinary words. Sentences vary in length; some are short.
- They don't summarise the company back to the person who works there, and they don't explain why
  they fit ("this aligns with", "which connects to"). They say what they did and let the reader
  connect it.
- No flattery, no performed enthusiasm. One plain sentence of genuine interest at most.

## Never use
- Openers: "I hope this email finds you well", "I came across", "I'm writing to", "I wanted to reach
  out", "As a third-year student, …" (any "As a …," start).
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
- Eight or more words in a row copied from the context sentences or from `highlights`.

## Hard rules
1. Leave out the greeting ("Hi …") and the sign-off ("Best, …", the name, links): they are added
   automatically, together with an opt-out line.
2. Never invent anything about the candidate: no skills, numbers, companies, feelings or experiences
   beyond `highlights` and `about_me`. Keep every number exactly as given. Never claim to know the
   recipient, to have used the product, or to follow the company.
3. No placeholders such as [Name] or {company}, no emoji, no markdown, no bullet lists.
4. Pitch it as `inputs.recipient.tone` says and ask what `inputs.recipient.ask` says.
5. If `feedback` lists problems, fix every one of them and keep everything else natural.

## Examples (each one is fine; don't reuse their wording or structure)
To a founder, ask "whether the team takes interns", highlights about a Go service on Kubernetes:

```json
{
  "subject": "Interns on the platform side at Corvid?",
  "body": "I'm a second-year CS student and most of what I build is infrastructure: a few Go services running on a small Kubernetes cluster I set up myself. Does Corvid ever take interns on the platform side? If it's not something you do, a pointer to the right person would help just as much. My resume's attached.",
  "personalization_source": "Corvid runs the Kubernetes clusters that regional banks deploy on."
}
```

To an engineering manager, ask "for a 15-minute chat or to pass the resume on":

```json
{
  "subject": "Question about the data team at Ledgerline",
  "body": "I built a reconciliation script for a college fest's payments, Python and Postgres, that matched about 3,000 UPI transactions against the bank statement. Would you be open to a 15-minute chat about the data team, or passing my resume to whoever handles hiring? It's attached.",
  "personalization_source": "Ledgerline builds accounting APIs that banks call to reconcile payments in real time."
}
```

What NOT to write: "I came across Ledgerline and was excited to see you're hiring for the Backend
Intern role. I'd love to apply for the position, as my skills align perfectly with your team."

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
