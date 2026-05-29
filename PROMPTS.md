# Sample prompts

These are the actual prompt templates the system sends to the LLM
(AiCredits / `anthropic/claude-3-haiku` by default, Groq fallback; Gemini/Claude
optional). They live in `backend/prompts/*.txt` so you can edit them without
touching code.

## 1. Resume tailoring
**File:** `backend/prompts/tailor_resume.txt`

Inputs filled at runtime:
- `{master_resume_json}` — your `data/master_resume.json`.
- `{job_title}`, `{company}`, `{job_description}` — from the Job row.

Output: a JSON object with the same schema as the master resume, plus
`ats_keywords`.

Guardrails: the LLM is told it must not invent skills, employers, dates,
metrics or projects. Identity fields (name, email, phone) are also force-
restored to the master values in `resume_engine._validate`.

## 2. Cover letter
**File:** `backend/prompts/cover_letter.txt`

Inputs: tailored resume JSON, JD.
Output: ~200-word, three-paragraph plain-text letter starting with
"Dear Hiring Team," and ending with "Best regards," + your name.

## 3. Job ranking
**File:** `backend/prompts/rank_job.txt`

Inputs: a compact candidate profile (marked as a **fresher**), the JD.
Hard rule baked in: senior titles or roles needing >2 years must score
`shortlist_likelihood` < 30 and `overall` ≤ 35 — a backstop behind the
deterministic experience filter that already drops most such roles pre-ranking.
Output (strict JSON):
```json
{
  "overall": 78,
  "breakdown": {
    "salary_estimate": 80, "company_quality": 90, "ats_match": 70,
    "growth_opportunity": 75, "remote_flexibility": 60, "shortlist_likelihood": 65
  },
  "reasoning": "...",
  "ats_keywords": ["...", "..."]
}
```

## 4. ATS keyword extraction
**File:** `backend/prompts/extract_keywords.txt`

Used standalone when the dashboard wants a fast keyword list without a full
ranking pass.

## 5. Screening-question answers
**File:** `backend/prompts/screening_answer.txt`

Used by the Playwright form filler when it encounters an unknown text input.
Heavily constrained: short, honest, no invented visa/citizenship/CTC.

## Tips when editing

- Keep the IMPORTANT/ABSOLUTE RULES blocks at the top — the LLM follows
  early-positioned instructions more reliably.
- For JSON outputs, end the prompt with the exact schema you expect and
  the word "STRICT JSON".
- If you change a prompt's variable placeholders, also update the
  `.format(...)` call site in `services/`.
