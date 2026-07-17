# Demo script: voice + document reasoning walkthrough

Use this for the Loom recording. It uses claim **CL-1003** (Anil Kumar), which is
already seeded in `claims.json` in a "queried" state, missing exactly two documents -
`discharge_summary` and `pan_card`. No setup needed, just start talking.

The two documents you need are already in the repo:
- `src/data/documents/discharge_summary.png`
- `src/data/documents/pan_card.png`

Upload them straight from there when the script calls for it.

---

## Part 1 - Claim status by voice (proves speaking + retrieval)

Start a call, say (in English or Hindi/Malayalam if you want to show language handling):

> "Hi, I want to check the status of my claim. My policy number is SMP-HL-500125 and
> claim ID is CL-1003."

**Expected:** the assistant calls `get_claim_status`, replies with something like:
"Your reimbursement claim CL-1003 for treatment at PRS Hospital, Thiruvananthapuram is
currently under query. We still need your discharge summary and PAN card before we can
process it." The source tag under the reply should show `get_claim_status`.

Follow up in the same call:

> "What exactly is still pending?"

**Expected:** re-calls `check_document_completeness` (not a memorized answer - watch the
source tag change), and names the same two documents. This is the fix for the earlier
bug where a follow-up question got answered from memory instead of a fresh tool call -
worth calling out live if you want to demonstrate the guardrail.

---

## Part 2 - Document upload + reasoning (proves document understanding)

Say:

> "How do I send these documents?"

**Expected:** the assistant calls `send_document_upload_link`, tells you it's sent a
secure upload link, and the app surfaces the document upload screen.

Now upload `discharge_summary.png` (from `src/data/documents/`).

**What's actually happening under the hood** (worth narrating for a pre-sales
audience): the image is sent to Sarvam Vision for OCR/digitization, the extracted text
is handed to Sarvam-105B with no filename hint at all, and the model reasons over the
*content* - patient name, hospital, diagnosis, procedure - to decide this is a discharge
summary, not a bill or prescription. It isn't pattern-matching on the filename.

**Expected reply:** confirms it recognized the discharge summary, and says the PAN card
is still needed.

Now upload `pan_card.png`.

**Expected reply:** confirms the PAN card, and tells you the claim is now complete and
has been moved forward for processing (no more pending documents).

---

## Part 3 - Denial explanation (proves the guardrail - explains, never invents)

Start a new claim lookup:

> "Can you check claim CL-1004 for me? Policy SMP-HL-500126."

Then:

> "Why was money deducted from my claim?"

**Expected:** calls `get_denial_reason`, explains the room-rent cap deduction in plain
language, references the specific policy clause. This is a good moment to point out
that the explanation is a deterministic template filled with real claim data - the LLM
never freehands the reason, it only decides *which* template applies.

---

## Part 4 - Out-of-scope escalation (proves the guardrail has edges)

> "Can you help me file my income tax returns?"

**Expected:** clean escalation to a human agent (`create_grievance_case` with
`out_of_scope_request`), not a hallucinated attempt to answer. Good moment to say
"notice it doesn't try to be helpful by making something up - it recognizes the edge of
its knowledge and hands off."

---

## Talking points to layer in as you go (pre-sales / GTM framing, not just features)

- **Anti-hallucination architecture**: the LLM only ever picks a tool; the actual words
  spoken are deterministic templates filled with real data, then translated. Call this
  out explicitly once - it's the single most important thing a buyer's risk/compliance
  team will ask about.
- **Source-tagging as a trust mechanic**: every reply shows which tool produced it. This
  is your answer to "how do you know it's not making things up" - point at the UI.
- **Guardrail regression you caught and fixed**: mention (briefly, don't dwell) that a
  session-history bug once let a follow-up question get answered from stale context
  instead of a fresh lookup, and that you caught and closed it - this shows you test for
  the failure modes a real deployment would hit, not just the happy path.
- **Document understanding is semantic, not filename-based**: emphasize this during
  Part 2. It's the difference between OCR-as-a-feature and OCR-as-actual-reasoning.
- **Escalation is a designed outcome, not a failure state**: frame Part 4 as "knowing
  when to hand off is part of the product," not "the bot got stuck."
