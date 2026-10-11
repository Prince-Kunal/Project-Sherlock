---
version: 1
---
# Task: write the middle of a short referral email for one job

## Purpose
A student found an opening and is emailing one person at the company to ask for a referral (or to
be pointed to the right person). The email must read like a thoughtful note from a real person, not
a template. The resume is attached. A program checks your answer and rejects it if a rule is broken.

## Input
- `inputs.job`: the job title, company and location.
- `inputs.context_sentences`: sentences from the job description (and sometimes the company's own
  description). Your one concrete hook must be based on exactly one of them.
- `inputs.recipient`: the person's title, their role category and the tone to use with them.
- `inputs.about_me`: one or two lines the candidate wrote about themselves.
- `inputs.highlights`: the candidate's two most relevant resume bullets for this job.
- `hint`: an optional request from the candidate for this draft (e.g. "mention I can start in May"),
  or "(none)". Follow it unless it breaks a rule below.
- `feedback`: problems a checker found in your previous draft, or "(none)".

## Output (JSON only)
- `subject`: under 70 characters, specific to the role, e.g. "Backend intern role: referral request".
  No clickbait, no "Quick question".
- `body`: plain text, 2 or 3 short paragraphs, **90 words or fewer**. It must:
  1. open with one concrete, genuine hook tied to `personalization_source` (what about the role or
     company caught the candidate's interest), in your own words;
  2. say in one or two sentences why the candidate fits, using only facts from `highlights` and
     `about_me`;
  3. make one clear ask: a referral for this role, or a pointer to the right person;
  4. mention that the resume is attached.
- `personalization_source`: the context sentence your hook is based on, **copied character for
  character** from `inputs.context_sentences`.

## Hard rules
1. Leave out the greeting ("Hi …") and the sign-off ("Best, …", the name, links): they are added
   automatically, together with an opt-out line.
2. Never invent facts about the candidate: no skills, numbers, companies or achievements beyond
   `highlights` and `about_me`. Never claim to know the recipient or to have used their product.
3. No placeholders such as [Name] or {company}, no emoji, no markdown, no bullet lists.
4. Don't flatter or grovel ("I know you're busy", "huge fan"). Be warm, plain and confident.
5. Match the tone given in `inputs.recipient.tone`.
6. If `feedback` lists problems, fix every one of them.

## Example
Context sentence: "You will build REST APIs in Python on PostgreSQL for our payments platform."
Highlights: ["Built REST APIs in Python and Flask backed by PostgreSQL for merchant onboarding"]

```json
{
  "subject": "Backend Engineering Intern: referral request",
  "body": "I saw the Backend Engineering Intern opening and the focus on Python APIs over PostgreSQL for your payments platform is close to what I've been doing. Last summer I built REST APIs in Python and Flask backed by PostgreSQL for merchant onboarding.\n\nWould you be open to referring me for the role, or pointing me to the right person? My resume is attached.",
  "personalization_source": "You will build REST APIs in Python on PostgreSQL for our payments platform."
}
```

## Inputs
```json
{{inputs}}
```

## Hint from the candidate
{{hint}}

## Feedback on your previous draft
{{feedback}}
