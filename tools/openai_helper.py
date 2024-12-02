import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_random_exponential

from .misc import trim_tokens

backend_dir = Path(__file__).parent.parent.parent

sys.path.append(str(backend_dir))
from tools.misc import num_tokens_from_string

# https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models?tabs=python-secure%2Cglobal-standard%2Cstandard-chat-completions#gpt-4o-and-gpt-4-turbo
GPT_4_MINI_MAX_INPUT_TOKENS = 128000
GPT_4_MINI_MAX_OUTPUT_TOKENS = 16000
EMBEDDING_ADA_002_MAX_INPUT_TOKENS = 8191


class OpenAIHelper:
    def __init__(
        self,
        openai_client,
        AZURE_OPENAI_CHATGPT_DEPLOYMENT,
        AZURE_OPENAI_EMB_DEPLOYMENT,
        language="English",
    ):
        self.openai_client = openai_client
        self.AZURE_OPENAI_CHATGPT_DEPLOYMENT = AZURE_OPENAI_CHATGPT_DEPLOYMENT
        self.AZURE_OPENAI_EMB_DEPLOYMENT = AZURE_OPENAI_EMB_DEPLOYMENT
        self.language = language

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def generate_embeddings(self, text: str):
        tokens = num_tokens_from_string(text, "text-embedding-ada-002")

        if tokens >= EMBEDDING_ADA_002_MAX_INPUT_TOKENS:
            text = text[:EMBEDDING_ADA_002_MAX_INPUT_TOKENS]

        return self.openai_client.embeddings.create(input=[text], model=self.AZURE_OPENAI_EMB_DEPLOYMENT).data[0].embedding

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def outline_webpage(self, content, website_url):
        """Outline a Webpage"""

        print(f"Outlining: {website_url}")

        try:
            tokens = num_tokens_from_string(content, "gpt-4")

            if tokens >= GPT_4_MINI_MAX_INPUT_TOKENS:
                raise ValueError(f"Content too long, tokens found {tokens}")

            messages = [
                {
                    "role": "user",
                    "content": f"Provide a thorough outline of all content but html tags from the provided HTML code. Format web links using this example: [Start Free Trial](https://clo3d.com). The url of the website is {website_url}. ###HTML Code###: {content}",
                }
            ]

            chat_completion = self.openai_client.chat.completions.create(
                model=self.AZURE_OPENAI_CHATGPT_DEPLOYMENT, messages=messages, temperature=0, max_tokens=GPT_4_MINI_MAX_OUTPUT_TOKENS, n=1
            )

            outline = chat_completion.choices[0].message.content
            # outline = re.sub(r"\[https.*\]", "", outline)
            # outline = outline.replace("[", "").replace("]", "").replace("(", "[").replace(")", "]")

            return outline
        except Exception as e:
            print("OpenAI Outline Webpage Error: ", e)
            return ""

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def scrape_webpage(self, content, website_url):
        """Scrape a Webpage"""

        try:
            tokens = num_tokens_from_string(content, "gpt-4")

            if tokens >= GPT_4_MINI_MAX_INPUT_TOKENS:
                raise ValueError(f"Content too long for {website_url}, tokens found {tokens}")

            messages = [
                {
                    "role": "user",
                    "content": f"Provide detailed instructions to effectively navigate and utilize the features of a website based on the provided HTML code. Instructions must include web links from the provided HTML code, for example: [Start Free Trial](https://clo3d.com). Instructions must exclude any html tags. The url of the website is {website_url}. ###HTML Code###: {content}",
                }
            ]

            chat_completion = self.openai_client.chat.completions.create(
                model=self.AZURE_OPENAI_CHATGPT_DEPLOYMENT, messages=messages, temperature=0, max_tokens=GPT_4_MINI_MAX_OUTPUT_TOKENS, n=1
            )

            scraped_content = chat_completion.choices[0].message.content
            scraped_content = re.sub(r"\[https.*\]", "", scraped_content)
            scraped_content = scraped_content.replace("[", "").replace("]", "").replace("(", "[").replace(")", "]")

            return scraped_content
        except Exception as e:
            print("OpenAI Scrape Webpage Error: ", e)
            return ""

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def create_webpage_title(self, content) -> str:
        """Scrape a Webpage"""

        tokens = num_tokens_from_string(content, "gpt-4")

        if tokens >= GPT_4_MINI_MAX_INPUT_TOKENS:
            raise ValueError(f"Content too long, tokens found {tokens}")

        messages = [{"role": "user", "content": f"Generate a title for a web page based on the following content: {content}"}]

        chat_completion = self.openai_client.chat.completions.create(
            model=self.AZURE_OPENAI_CHATGPT_DEPLOYMENT, messages=messages, temperature=0.7, max_tokens=GPT_4_MINI_MAX_OUTPUT_TOKENS, n=1
        )

        outline = chat_completion.choices[0].message.content

        return outline
