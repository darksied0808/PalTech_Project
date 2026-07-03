from src import gemini_client


def check_model_available(model: str | None = None) -> tuple[bool, str]:
    return gemini_client.check_model_available(model)


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> dict | list:
    return gemini_client.chat_json(
        system_prompt,
        user_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
