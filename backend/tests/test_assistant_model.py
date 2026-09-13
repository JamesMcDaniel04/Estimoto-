import json

import httpx
import pytest

from estimoto_plus.assistant_model import enhance_advice


BASE = {"reply": "Existing useful guidance.", "intent": "advice", "providers": [], "videos": []}


def model_response(text):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}]}


def test_private_fields_never_sent_and_model_cannot_supply_providers(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    def transport(request):
        body = json.loads(request.content)
        context = json.loads(body["input"])
        assert context["vehicle"] == {"year": 2021, "make": "Toyota", "model": "Tacoma", "mileage": 42000}
        assert body["store"] is False and body["tools"] == [] and body["max_output_tokens"] == 650
        response = model_response("Check the manual for the filter location and replacement interval.")
        response["providers"] = [{"name": "Invented provider"}]
        return httpx.Response(200, json=response)
    result = enhance_advice(BASE, message="What does a cabin air filter do?", vehicle={
        "year": 2021, "make": "Toyota", "model": "Tacoma", "mileage": 42000,
        "vin": "PRIVATE VIN", "insurance": "PRIVATE POLICY", "email": "private@example.test",
    }, transport=httpx.MockTransport(transport))
    assert result["answer_source"] == "AI guidance"
    assert result["providers"] == []


@pytest.mark.parametrize("status", [429, 500, 401, 302])
def test_provider_failure_keeps_guidance(monkeypatch, status):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert enhance_advice(BASE, message="What is a cabin filter?", vehicle=None,
        transport=httpx.MockTransport(lambda _: httpx.Response(status))) == BASE


@pytest.mark.parametrize("text", ["I've booked you an appointment.", "I sent your details to the shop.",
                                    "Read https://unsafe.example", "<script>bad</script>",
                                    "Replace it every 15,000-25,000 miles.", "Inflate tires to 35 psi."])
def test_action_claims_and_untrusted_links_fail_closed(monkeypatch, text):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert enhance_advice(BASE, message="Explain filters", vehicle=None,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=model_response(text)))) == BASE


@pytest.mark.parametrize("message", ["My brakes failed", "The engine is overheating", "Disable my airbag"])
def test_urgent_questions_never_enter_model(monkeypatch, message):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    def forbidden(_):
        pytest.fail("Urgent guidance must not call the model")
    assert enhance_advice(BASE, message=message, vehicle=None, transport=httpx.MockTransport(forbidden)) == BASE


def test_tire_pressure_has_a_real_labeled_video_without_model_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = enhance_advice(BASE, message="How do I check tire pressure?", vehicle=None)
    assert result["reply"] == BASE["reply"]
    assert result["videos"][0]["url"] == "https://www.youtube.com/watch?v=dn0ShsQRgho"
    assert "Michelin USA" in result["videos"][0]["source"]


def test_incomplete_and_oversized_model_output_keep_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for body in [b"x" * 66000, b'{}', b'{"status":"incomplete"}', b'not json']:
        assert enhance_advice(BASE, message="Explain filters", vehicle=None,
            transport=httpx.MockTransport(lambda _, body=body: httpx.Response(200, content=body))) == BASE
