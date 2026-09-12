<h1 align="center">
  <a href="https://meetchatty.vercel.app/">
    <img src="docs/assets/chatty-heading.svg" width="330" alt="Chatty — visit website">
  </a>
</h1>

<p align="center">
  <strong>Less searching. More conversation.</strong><br>
  Your project. In the conversation.
</p>

<p align="center">
  <a href="https://aitinkerers.org/">
    <img src="landing/dist/assets/ai-tinkerers.png" width="220" alt="AI Tinkerers">
  </a>
</p>

[![Meet Chatty — Your AI meeting companion. Keep the conversation moving.](landing/dist/assets/chatty-poster.jpg)](landing/dist/assets/chatty-intro.mp4)

## The idea

**Your team is talking. The answers are somewhere else.**

A meeting pauses. Someone asks what changed, which pull requests are open, or what needs to happen next. The context is in GitHub; the conversation is happening somewhere else.

Chatty is an AI meeting companion in development, built to bring that project context into the conversation. Ask a question, follow the source, and turn a decision into a next step—without losing the thread.

Chatty explores a simple idea: the tools your team uses should support the conversation while it is happening.

## From a question to a next step

| In the conversation | What Chatty is being built to bring back |
| --- | --- |
| Can you create/close an issue? | Create or close a GitHub issue at your request. |
| Can you summarize the project? | A concise overview of the project and its recent activity. |
| How many issues in github repo? | The number of issues in the GitHub repository. |
| What issues are still open? | A list of open issues with links to their original records. |

These are examples of the intended conversation flow, not a list of currently available features. The complete meeting experience is still in development.

### Catch up. Stay in the flow.

Bring commits, pull requests, and issues into the same context as your team’s questions.

### Find the answer. Follow the source.

Read the original record when you need the detail. GitHub results include source links, authors, and timestamps.

### A next step. At your request.

Keep the decision to act with the people in the conversation. Chatty prepares the requested repository or project change, reads its proposal aloud, and asks for spoken approval. Say yes or Chatty confirm to approve, or no, Chatty cancel, or Chatty stop to cancel. No browser approval click is needed. The durable call ledger prevents blind duplicate writes when calls are redelivered.

## What works today

| Area | Status in this checkout |
| --- | --- |
| GitHub reads | Repository, commits, issues, comments, pull requests, branches, files, and workflow context, with source links. |
| GitHub and project changes | 17 supported mutations with saved proposals, spoken approval, validated inputs, and durable call deduplication. |
| Repository scope | GitHub tools target `vaishnavJa/Chatty` and one optional server-configured project; GitHub permissions still apply. |
| Landing page | Static site with the intro video, responsive layout, and reduced-motion support. |
| Meeting companion | Local OpenAI Live backend and meeting UI; virtual-microphone replies without outgoing screen presentation, Chatty wake/stop, and optional requested screen snapshots. |

The prototype trusts its local browser and meeting participants; it does not authenticate individual speakers. Speech timing and the final voice-approval flow still require a live rehearsal. Setup and limits are in the [local demo guide](docs/local-demo.md), [meeting setup](docs/meeting-setup.md), and [spoken approval contract](docs/voice-approval.md).

---

<p align="center"><strong>Keep the conversation moving.</strong></p>
