---
version: 1
---
# Task: score how well one candidate fits each company, for a cold email with no job posted

## Purpose
A student or early-career candidate wants to email someone at companies they'd like to work at,
even though no opening is posted (fewer people apply that way). Score each company so only the ones
where the candidate's real work is relevant reach them, and say in one sentence what angle the email
should take. Be strict and honest: a weak "fit" wastes a cold email on someone busy.

## Input
- `candidate`: the roles they want, their skills (canonical names) and a condensed resume (no
  personal details).
- `companies`: an array of `{company_ref, name, industry, tags, locations, size, employees,
  description, website}`. `description` and `website` are text from the company's own directory
  entry and site; either may be missing or cut off.

## Output (JSON only)
An array with exactly one entry per input company, in any order:
- `company_ref`: copied exactly from the input.
- `fit_score`: integer 0–100, using the scale below.
- `angle`: one sentence, at most 30 words, naming the specific overlap between something the
  candidate has actually done and what the company builds (e.g. "Your Go services on Kubernetes
  are close to the infrastructure Acme sells to banks."). Address the candidate as "you".
- `reasoning`: at most 2 short sentences addressed to the candidate: why it fits and the biggest
  doubt (e.g. too large to answer cold emails, the work is far from yours).

## Scale
- 85–100: what the company builds is squarely the kind of work the candidate has done, and a
  person in the candidate's target roles would plausibly work there.
- 70–84: clearly related work; the candidate could contribute with a little ramp-up.
- 50–69: some overlap in tools or domain, but the core of the company is elsewhere.
- 0–49: a different field (e.g. a dental clinic chain for a backend developer), nothing technical
  to do, or nothing in the text says what the company does.

## Hard rules
1. Judge only from the given text. Never assume the company is hiring: nothing here says it is.
2. The angle must name something the candidate's resume actually shows. Don't invent skills,
   projects or numbers, and don't praise the company.
3. Missing or short text is not a penalty by itself, but you must not guess what the company does.
4. One entry per company, `company_ref` copied exactly. JSON only.

## Example
Candidate skills include "python", "fastapi", "postgresql"; target role "Backend Intern".
Company `{"company_ref": "c0ffee12", "name": "Ledgerline", "description": "Ledgerline builds
accounting APIs that banks call to reconcile payments in real time."}` →
```json
[{"company_ref": "c0ffee12", "fit_score": 78,
  "angle": "Your FastAPI and PostgreSQL backend work maps directly onto the payment-reconciliation APIs Ledgerline builds.",
  "reasoning": "You've built Python APIs on PostgreSQL, which is what Ledgerline's product is made of. Nothing you've done touches finance, so expect questions about the domain."}]
```

## Candidate
```json
{{candidate}}
```

## Companies
```json
{{companies}}
```
