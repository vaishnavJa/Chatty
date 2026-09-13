# Show the decision becoming work

The strongest Chatty demonstration is one complete meeting interaction: the team
changes its mind, Chatty retrieves the discussion and repository evidence, a person
reviews the draft naturally, and one approved action produces a real receipt.
This is a rehearsal guide, not a claim that a particular judging score is assured.

## One-minute live sequence

Prepare one deliberately named demo issue and agree which participants will speak.
Use the [meeting setup](meeting-setup.md) with a fresh server and Live session.
Keep outgoing presentation off and verify audio in both directions before recording.

| Time | What happens | Evidence to show |
| --- | --- | --- |
| 0–10 s | Two people discuss a bug, then correct one detail: the problem is missing summary owners, not missing summary text. Chatty is listening quietly. | The conversation happens in the meeting. |
| 10–23 s | “Chatty, use what we just agreed and check the relevant repository context.” | Session transcript evidence and current GitHub sources support the answer. |
| 23–34 s | “Create an issue for that.” Chatty briefly describes the action and asks for approval. | The saved draft matches the corrected problem; no lengthy readback. |
| 34–44 s | “What would you put in the description?” Then, if needed: “Change the title to Include owners in meeting summaries.” | A draft question gets an answer; a revision receives fresh approval. |
| 44–54 s | “Sounds good, go ahead.” | Exactly one successful issue receipt and its actual GitHub link. |
| 54–60 s | “Chatty, stop.” | One short “Okay,” followed by quiet listening. |

These timings are an editing target, not a latency guarantee. If the live interaction
takes longer, keep an honest continuous workflow recording and use the separate
one-minute promotional film to introduce the product. Do not present animated
example messages or issue cards as evidence that a real GitHub action occurred.

## Readiness evidence

Automated fixtures and live meeting checks answer different questions. Record the
commit, browser, audio route and outcome when doing the live checks below. Do not
mark them passed from unit tests or from a connected-session badge alone.

- A participant on another device can hear Chatty and Chatty can hear them.
- A follow-up works without repeating the wake word, including after a pause.
- A draft question does not approve or cancel the saved action.
- A revision changes the proposed payload and requires a fresh decision.
- A natural approval creates one action; duplicate events do not create another.
- “No,” cancellation, unclear replies and interrupted speech do not authorize a write.
- A permissions error is explained without claiming success or repeating the write.
- An uncertain result preserves its receipt and tells the user to check GitHub.
- “Chatty, stop” acknowledges once, stays quiet and keeps input listening.
- Missing or truncated meeting context is disclosed instead of invented.

## Scope shown to judges

Chatty is a localhost prototype that uses a user-selected meeting tab and virtual
microphone. GitHub tools are limited to the configured repository and optional
project. It does not join calls autonomously, authenticate individual speakers or
guarantee that a retrieved transcript represents group consensus. Zoom/Teams
browser validation and Microsoft Teams data access are separate work items.

See [capabilities](capabilities.md), [voice approval](voice-approval.md) and the
[local demo guide](local-demo.md) for the implemented boundaries and setup.
