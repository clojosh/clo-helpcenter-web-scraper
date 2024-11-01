import os
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv
from openai import AzureOpenAI

from tools.openai_helper import OpenAIHelper


class Environment:
    backend_dir = Path(__file__).parent.parent
    zendesk_article_api_endpoint = (
        "https://{0}.zendesk.com/api/v2/help_center/en-us/articles.json?page={1}&per_page=30&sort_by=updated_at&sort_order=desc"
    )
    zendesk_article_section_api_endpoint = "https://{0}.zendesk.com/api/v2/help_center/en-us/sections/{1}.json"
    zendesk_article_category_api_endpoint = "https://{0}.zendesk.com/api/v2/help_center/en-us/categories/{1}.json"
    zendesk_article_attachment_api_endpoint = "https://support.{0}.com/api/v2/help_center/{1}/articles/{2}/attachments"

    def __init__(self, env="dev", brand="", language="English"):
        self.env = env
        self.brand = brand
        self.language = language

        if self.env == "prod":
            load_dotenv(os.path.join(self.backend_dir, ".env.prod"))
        else:
            load_dotenv(os.path.join(self.backend_dir, ".env.dev"))

        self.AZURE_SEARCH_SERVICE = os.environ.get("AZURE_SEARCH_SERVICE")
        self.INDEX_NAME = os.environ.get(f"{self.brand.upper()}_AZURE_SEARCH_INDEX")

        self.SEARCH_CLIENT_ENDPOINT = f"https://{self.AZURE_SEARCH_SERVICE}.search.windows.net"
        self.AZURE_KEY_CREDENTIAL = AzureKeyCredential(os.environ.get("AZURE_SEARCH_KEY"))

        self.search_client = SearchClient(
            endpoint=f"https://{self.AZURE_SEARCH_SERVICE}.search.windows.net",
            index_name=self.INDEX_NAME,
            credential=self.AZURE_KEY_CREDENTIAL,
        )

        self.AZURE_OPENAI_SERVICE = os.environ.get("AZURE_OPENAI_SERVICE")
        self.AZURE_OPENAI_CHATGPT_DEPLOYMENT = os.environ.get("AZURE_OPENAI_CHATGPT_DEPLOYMENT")
        self.AZURE_OPENAI_EMB_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMB_DEPLOYMENT")
        self.openai_client = AzureOpenAI(
            api_version="2023-07-01-preview",
            azure_endpoint=f"https://{self.AZURE_OPENAI_SERVICE}.openai.azure.com",
            api_key=os.environ.get("AZURE_OPENAI_KEY"),
        )

        self.URI = os.environ.get("MONGO_URI")
        self.DB_NAME = os.environ.get(f"{self.brand.upper()}_MONGO_DB_NAME")
        self.COLLECTION_NAME = os.environ.get("MONGO_COLLECTION_CHATHISTORY")
        self.COLLECTION_USERS = os.environ.get("MONGO_COLLECTION_USERS")
        self.COLLECTION_ARTICLE = os.environ.get("MONGO_COLLECTION_ARTICLES")
        self.COLLECTION_FEEDBACK = os.environ.get("MONGO_COLLECTION_FEEDBACK")

        self.openai_helper = OpenAIHelper(
            self.openai_client,
            self.AZURE_OPENAI_CHATGPT_DEPLOYMENT,
            self.AZURE_OPENAI_EMB_DEPLOYMENT,
            language=language,
        )
