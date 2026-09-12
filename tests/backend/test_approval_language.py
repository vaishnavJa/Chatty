import json

import httpx
import pytest

from chatty.approval_language import ApprovalLanguage, direct_intent


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
        "unclear",
    ]
    assert "long private draft" not in body["input"][0]["content"][0]["text"]
    assert requests[0].extensions["timeout"]["read"] <= 5


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
