"""Every prompt in one file, so you can tune wording without touching logic."""

TWITTER_MAX = 240   # characters, text plus hashtags

RULES = {
    "linkedin": "Professional tone. 90 to 150 words. Start with a hook line. "
                "End with a question. 3 to 5 hashtags.",
    "instagram": "Friendly, energetic tone. Under 120 words. A few emojis are fine. "
                 "6 to 10 hashtags.",
    "twitter": f"Short and punchy. Text plus hashtags must be {TWITTER_MAX} characters or fewer. "
               "1 or 2 hashtags.",
}

FACT_RULE = ("Use only facts found in the summary and key points. "
             "Do not invent numbers, quotes or names.")


def research_prompt(title: str, content: str) -> str:
    return (
        "You are a research assistant for a tech news account.\n"
        f"Article title: {title}\n"
        f"Article text:\n{content}\n\n"
        "Summarize the article in 3 or 4 plain sentences, list 2 to 4 key facts, and give a "
        "relevance score from 1 to 10 for a tech-curious audience "
        "(10 = important and interesting, 1 = off topic or empty). "
        "Explain the score in one sentence."
    )


def write_prompt(platform: str, title: str, url: str, summary: str, key_points: list[str],
                 previous_text: str = "", feedback: str = "") -> str:
    points = "\n".join(f"- {p}" for p in key_points)
    prompt = (
        f"Write a {platform} post about this article.\n"
        f"Title: {title}\nLink: {url}\nSummary: {summary}\nKey points:\n{points}\n\n"
        f"Rules: {RULES[platform]}\n{FACT_RULE}\n"
        "Do not put hashtags inside the text. Return them separately without the # sign."
    )
    if previous_text:
        prompt += (f"\n\nYour previous draft:\n{previous_text}\n"
                   f"A reviewer said: {feedback}\nRewrite it and fix that problem.")
    return prompt


def critic_prompt(platform: str, title: str, summary: str, text: str, hashtags: list[str]) -> str:
    return (
        f"You review {platform} posts. Score the draft from 1 to 10 for clarity, "
        "accuracy against the summary, and fit for the platform.\n"
        f"Platform rules: {RULES[platform]}\n"
        f"Article title: {title}\nSummary: {summary}\n\n"
        f"Draft:\n{text}\nHashtags: {', '.join(hashtags)}\n\n"
        "Give the score and one or two sentences on what to fix."
    )
