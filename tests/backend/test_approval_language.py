import json

import httpx
import pytest

from chatty.approval_language import ApprovalLanguage, direct_intent, proposal_answer


def response_body(intent):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps({"intent": intent})}
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "reply",
    [
        "yeah",
        "sure",
        "okay",
        "absolutely",
        "sounds good",
        "yes yes yes",
        "Chatty, sure, go ahead",
        "okay okay",
        "Yes, please!",
    ],
)
def test_natural_clear_agreement_fast_path(reply):
    assert direct_intent(reply) == "approve"


@pytest.mark.parametrize(
    "reply,intent",
    [
        ("no thanks", "reject"),
        ("Chatty stop", "reject"),
        ("yes but change the title", "revise"),
        ("yes but not that title", "revise"),
        ("yes if the owner agrees", "unclear"),
        ("someone said yes", "unclear"),
        ("Sure?", None),
        ("Approved?", None),
    ],
)
def test_negation_revision_context_and_uncertain_questions(reply, intent):
    assert direct_intent(reply) == intent


def test_semantic_fallback_uses_structured_no_tools_bounded_context(settings):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_body("approve"))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        language = ApprovalLanguage(settings, http=client)
        assert (
            language.reply_intent(
                "create_issue",
                {"title": "Fix login", "body": "long private draft"},
                "You have my green light to proceed",
            )
            == "approve"
        )
    body = json.loads(requests[0].content)
    assert body["store"] is False
    assert "tools" not in body
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["properties"]["intent"]["enum"] == [
        "approve",
        "reject",
        "revise",
        "question",
        "unclear",
    ]
    assert "long private draft" not in body["input"][0]["content"][0]["text"]
    assert requests[0].extensions["timeout"]["read"] <= 5


@pytest.mark.parametrize("milestone", [17, None])
def test_semantic_revision_context_includes_actual_saved_issue_targets(
    settings, milestone
):
    requests = []
    saved = {
        "issue_number": 42,
        "assignees": ["karimkohel"],
        "labels": ["bug", "demo"],
        "milestone": milestone,
    }

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body("revise"))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            ApprovalLanguage(settings, http=client).reply_intent(
                "update_issue", saved, "I'm happy for you to assign this to Ron"
            )
            == "revise"
        )
    context = json.loads(requests[0]["input"][0]["content"][0]["text"])
    assert context["pending_action"]["target"] == saved
    assert saved["assignees"] == ["karimkohel"]
    assert (
        "proposed values, not a snapshot of current GitHub state"
        in requests[0]["instructions"]
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"assignees": ["a"] * 11},
        {"assignees": "karimkohel"},
        {"labels": ["x" * 101]},
        {"labels": [3]},
        {"milestone": True},
        {"milestone": -1},
    ],
)
def test_invalid_or_unbounded_issue_targets_never_get_semantic_consent(
    settings, invalid
):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_body("approve"))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            ApprovalLanguage(settings, http=client).reply_intent(
                "update_issue",
                {"issue_number": 42, **invalid},
                "You have my green light",
            )
            == "unclear"
        )
    assert not requests


@pytest.mark.parametrize(
    "kind",
    ["timeout", "failure", "refusal", "incomplete", "invalid_enum", "invalid_json"],
)
def test_failed_semantic_checks_never_grant_consent(settings, kind):
    def handle(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private details", request=request)
        if kind == "failure":
            return httpx.Response(503, text="private details")
        if kind == "refusal":
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "refusal", "refusal": "no"}],
                        }
                    ],
                },
            )
        if kind == "incomplete":
            return httpx.Response(200, json={"status": "incomplete"})
        if kind == "invalid_enum":
            return httpx.Response(200, json=response_body("sure"))
        return httpx.Response(200, text="invalid")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        language = ApprovalLanguage(settings, http=client)
        assert (
            language.reply_intent(
                "create_issue", {"title": "Fix login"}, "You have my green light"
            )
            == "unclear"
        )
        assert (
            language.prompt_ready(
                "create_issue",
                {"title": "Fix login"},
                "I'll open a login bug. Sound good?",
            )
            is False
        )


@pytest.mark.parametrize(
    "prompt",
    [
        "I'll open an issue about login. Sound good?",
        "I'll open an issue about login. Okay with you?",
        "I'll open an issue about login. Should I?",
    ],
)
def test_natural_consent_questions_reach_semantic_check(settings, prompt):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_body("ready"))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            ApprovalLanguage(settings, http=client).prompt_ready(
                "create_issue", {"title": "Fix login"}, prompt
            )
            is True
        )
    assert len(requests) == 1


def test_unrelated_approval_question_does_not_arm(settings):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=response_body("not_ready"))
        )
    ) as client:
        assert (
            ApprovalLanguage(settings, http=client).prompt_ready(
                "create_issue",
                {"title": "Fix login"},
                "We should order pizza. Do you approve?",
            )
            is False
        )


@pytest.mark.parametrize(
    "reply,intent",
    [
        ("What will you write?", "question"),
        ("Who is assigned?", "question"),
        ("Chatty, read the full draft", "question"),
        ("Could you show me the description?", "question"),
        ("What would you change instead?", "question"),
        ("Yes, but what is the title?", "question"),
        ("Can you assign it to Karim?", "revise"),
        ("Actually assign it to Karim", "revise"),
        ("Yes but use a different description", "revise"),
        ("Could you please rename it?", "revise"),
    ],
)
def test_questions_are_information_and_requested_changes_are_revisions(reply, intent):
    assert direct_intent(reply) == intent


def test_assignee_answer_uses_only_saved_assignment():
    saved = {"issue_number": 17, "title": "Fix login", "assignees": ["karimkohel"]}
    answer = proposal_answer("update_issue", saved, "Who is assigned?")
    assert answer == {
        "answer": "Assignees: karimkohel",
        "details": {"assignees": ["karimkohel"]},
    }
    assert "Fix login" not in answer["answer"]


@pytest.mark.parametrize("name", ["create_issue", "update_issue"])
def test_absent_field_does_not_claim_remote_state(name):
    answer = proposal_answer(name, {"title": "Fix login"}, "Who is assigned?")
    assert answer["details"] == {}
    assert answer["answer"] == "This draft does not include an assignment change."
    assert "unassigned" not in answer["answer"]


def test_explicit_description_and_full_draft_detail_are_exact():
    saved = {
        "issue_number": 17,
        "title": "Fix login",
        "body": "Reproduce with an expired session.\nKeep this exact detail.",
        "assignees": ["karimkohel"],
    }
    answer = proposal_answer("update_issue", saved, "What will you write?")
    assert answer["details"] == {"title": saved["title"], "body": saved["body"]}
    assert saved["body"] in answer["answer"]
    full = proposal_answer("update_issue", saved, "Read the full draft")
    assert full["details"] == saved
    assert all(
        str(value) in full["answer"] for value in [17, saved["body"], saved["title"]]
    )


def test_large_requested_content_is_complete_in_details_and_honest_in_speech():
    saved = {"path": "a.py", "content": "word " * 10_000}
    answer = proposal_answer("update_repository_file", saved, "Read the full draft")
    assert answer["details"] == saved
    assert len(answer["answer"]) < 1200
    assert "excerpt" in answer["answer"]
    assert "complete requested fields" in answer["answer"]


@pytest.mark.parametrize(
    "question",
    ["Why did this bug happen?", "What are the sources?", "Who created this issue?"],
)
def test_unknown_question_does_not_invent_explanation_or_sources(question):
    answer = proposal_answer(
        "create_issue", {"title": "Fix login", "assignees": ["karimkohel"]}, question
    )
    assert "draft doesn't establish the answer" in answer["answer"]
    assert answer["details"] == {}


def test_empty_field_means_clearing_and_omitted_field_does_not():
    assert (
        "will be cleared"
        in proposal_answer("update_issue", {"assignees": []}, "Who is assigned?")[
            "answer"
        ]
    )
    assert (
        "will be cleared"
        not in proposal_answer(
            "update_issue", {"title": "Fix login"}, "Who is assigned?"
        )["answer"]
    )
