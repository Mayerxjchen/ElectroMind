"""Live tools (human-in-the-loop)."""

from pagent.tool import tool

from .context import ToolContext

_ASK_USER_DESCRIPTION = (
    "Ask the human operator one question and wait for their reply. "
    "Use ONLY when you cannot proceed without information the human must supply "
    "(e.g. preference, approval, missing fact, disambiguation, or choosing among options). "
    "Do NOT use for rhetorical questions, small talk, or when the user already answered "
    "in the conversation. Do NOT use to 'demo' the tool or ask trivia you could answer yourself. "
    "Ask exactly one clear question per call; put choices in the question text if needed."
)


@tool(description=_ASK_USER_DESCRIPTION)
async def ask_user(context: ToolContext, question: str) -> str:
    """Deliver ``question`` to the human UI and return their answer.

    Args:
        question: A single, self-contained question (plain text or markdown). The run blocks until the human replies.
    """
    return await context.request_human(question)
