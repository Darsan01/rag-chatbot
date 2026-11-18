from rag_chatbot.ui.ui import LocalChatbotUI


def test_explicit_image_command_extracts_prompt():
    assert LocalChatbotUI._image_generation_prompt("/image a red bicycle") == (
        "a red bicycle"
    )


def test_natural_image_request_extracts_prompt():
    assert (
        LocalChatbotUI._image_generation_prompt(
            "Generate an image of a lighthouse at sunset"
        )
        == "a lighthouse at sunset"
    )


def test_regular_chat_is_not_treated_as_image_generation():
    assert LocalChatbotUI._image_generation_prompt("Make this code faster") is None


def test_follow_up_generation_uses_previous_description():
    history = [
        ["Describe this image\n\n[Image: source.jpg]", "A certificate."],
        ["A floating tea shop above the Himalayas", "That sounds beautiful."],
    ]

    assert (
        LocalChatbotUI._resolve_image_generation_prompt("generate the image", history)
        == "A floating tea shop above the Himalayas"
    )


def test_generation_without_context_requests_a_prompt():
    assert LocalChatbotUI._resolve_image_generation_prompt("create an image", []) == ""


def test_short_follow_up_uses_previous_description():
    assert (
        LocalChatbotUI._resolve_image_generation_prompt(
            "create it", [["A watercolor mountain village", "Nice idea."]]
        )
        == "A watercolor mountain village"
    )
