import asyncio
import json
import multiprocessing
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import questionary
import requests
import shortuuid
from bs4 import BeautifulSoup, NavigableString, Tag, element
from pyppeteer import launch
from requests_html import HTMLSession

from tools.environment import Environment

urls = []
project_path = os.path.dirname(os.path.abspath(__file__))
scraped_html_path = os.path.join(project_path, "websites", "landing", "scraped_html")
openai_html_path = os.path.join(project_path, "websites", "landing", "openai_html")


class Landing:
    def __init__(self, environment: Environment):
        self.env = environment.env
        self.environment = environment
        self.brand = environment.brand
        self.language = environment.language
        self.search_client = environment.search_client
        self.openai_helper = environment.openai_helper

    @staticmethod
    def reduce_tokens(scraped_content: str):
        """
        Reduces the tokens in the scraped content by removing unnecessary whitespaces and tags.

        Args:
            scraped_content (str): The scraped content

        Returns:
            str: The reduced tokens
        """
        # Remove unnecessary whitespaces between tags
        scraped_content = re.sub(r">\s+<", "><", scraped_content)

        # Replace multiple whitespaces with a single space
        scraped_content = re.sub(r"\s{2,}", " ", scraped_content)

        # Remove leading and trailing whitespaces from tags
        scraped_content = scraped_content.replace(" <", "<")
        scraped_content = scraped_content.replace(" >", ">")

        return scraped_content

    def scrape_text(self, url: str) -> None:
        """
        Scrape all text and links from the given URL and save it to a file.

        Args:
            url (str): The URL to scrape
        """
        response = requests.get(url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "html.parser")

            # Get all tags from the page
            tags = set()
            for tag in soup.find_all():
                # Stop when we reach the footer
                if tag.name == "footer":
                    break

                # Only get text and links from the following tags
                if tag.name in ["a", "span", "h1", "h2", "h3", "h4", "h5", "h6", "p"]:
                    if tag.name == "a":
                        # Get the text and link from the tag
                        text = ""
                        for string in tag.strings:
                            text += string + " "

                        # If the link is relative, add the base URL
                        if tag.get("href").startswith("/") or tag.get("href").startswith("#"):
                            link = "https://clo3d.com" + tag.get("href")

                        # Add the text and link to the set
                        tags.add(text + " " + link)
                    elif tag.get_text() != "":
                        # Add the text to the set
                        tags.add(tag.get_text() + " ")

            # Skip the first 15 tags which are from the nav tag
            tags = list(tags)[15:]

            # Save the tags to a file
            text = ""
            for tag in tags:
                # Replace the URL with a file name
                url = url.replace("https://clo3d.com/", "").replace("/", "_")
                with open(os.path.join(project_path, "landing", "scraped_content", f"{url.strip()}.txt"), "w+", encoding="utf-8") as f:
                    # Remove extra whitespaces from the tag
                    f.write(re.sub(r"\s{2,}", " ", tag))

        else:
            print("Failed to retrieve the webpage")

    def remove_tag_attributes(self, tag: Tag) -> Tag:
        """
        Remove unwanted attributes from the tags in the page

        :param tag: The tag to remove attributes from
        :return: The modified tag
        """
        # List of attributes we don't want to keep
        REMOVE_ATTRIBUTES = [
            "lang",  # Language of the page
            "language",  # Language of the page
            "onmouseover",  # JavaScript code to execute when the mouse is over an element
            "onmouseout",  # JavaScript code to execute when the mouse is moved away from an element
            "script",  # Script to execute when the page loads
            "style",  # CSS style for the element
            "font",  # Font settings for the element
            "dir",  # Direction of the text
            "face",  # Font family for the element
            "size",  # Size of the font
            "color",  # Color of the text
            "style",  # CSS style for the element
            "class",  # Class of the element
            "width",  # Width of the element
            "height",  # Height of the element
            "hspace",  # Horizontal spacing around the element
            "border",  # Border settings for the element
            "valign",  # Vertical alignment of the element
            "align",  # Horizontal alignment of the element
            "background",  # Background color/image for the element
            "bgcolor",  # Background color for the element
            "text",  # Text color for the element
            "link",  # Color of the links
            "vlink",  # Color of the visited links
            "alink",  # Color of the active links
            "cellpadding",  # Space between the cell wall and the cell content
            "cellspacing",  # Space between table cells
            "d",
            "xlink:href",
            "aria-hidden",
            "viewbox",
            "for",
            "modelvalue",
            "target",
        ]

        if tag is None:
            return tag

        # Remove attributes from all tags
        for t in tag.descendants:
            if isinstance(t, element.Tag):
                t.attrs = {key: value for key, value in t.attrs.items() if key not in REMOVE_ATTRIBUTES}

        # Remove data- attributes from all tags
        for t in tag.find_all(lambda t: any(i.startswith("data-") for i in t.attrs)):
            for attr in list(t.attrs):
                if attr.startswith("data-"):
                    del t.attrs[attr]

        return tag

    def remove_unnecessary_tags(self, html: str):
        soup = BeautifulSoup(html, "html.parser")

        for div in soup.find_all("div"):
            # Check if the div has no attributes and only contains another div
            if div.find("div", recursive=False):
                # Replace the current div with its content
                div.unwrap()

        for span in soup.find_all("span"):
            # Check if the div has no attributes and only contains another span
            if span.find("span", recursive=False):
                # Replace the current div with its content
                span.unwrap()

        for svg in soup.find_all("svg"):
            svg.decompose()

        for img in soup.find_all("img"):
            img.decompose()

        for picture in soup.find_all("picture"):
            picture.decompose()

        for script in soup.find_all("script"):
            script.decompose()

        return soup

    def format_html(self, url: str, html: str):
        html = (
            html.replace("<!--[-->", "")
            .replace("<!--]-->", "")
            .replace("<!--", "")
            .replace("-->", "")
            .replace(' href="/', ' href="https://landing.clo-set.com/allatonce')
        )
        soup = self.remove_unnecessary_tags(html)

        contents = self.remove_tag_attributes(soup.find("body"))

        return contents

    def scrape_all_page_urls(self, website: str):
        """
        Recursively scrape every page URL from the website

        Args:
            website (str): The URL of the website to scrape

        Returns:
            None
        """
        response = requests.get(website)
        soup = BeautifulSoup(response.text, "html.parser")

        # Excluded pages
        excluded_pages = []

        # Find all 'a' tags with a href attribute
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")

            # Check if the URL is relative or absolute
            if (
                (href.startswith("https://landing.clo-set.com") or href.startswith("/"))
                and any(page in href for page in excluded_pages) is False
                and "#" not in href
                and re.search(r"resources/esg/\d+", href) is None
            ):
                # If the URL is relative, add the base URL
                if not href.startswith("https://landing.clo-set.com"):
                    href = "https://landing.clo-set.com" + href

                # If the URL is not already in the list, add it
                if href not in urls:
                    print(href.strip())
                    urls.append(href.strip())

                    # Recursively call the function on the new URL
                    self.scrape_all_page_urls(href)
            else:
                continue

    def scrape_all_pages(self, scraped_urls=[]):
        session = HTMLSession()

        for url in scraped_urls:
            # Skip the download page because it has dynamic content

            print("Scraping " + url)

            try:
                resp = session.get(url)
                resp.html.render()
                html = resp.html.html

            except Exception as e:
                print("Error scraping " + url + ": " + str(e))
                continue

            content = self.format_html(url, html)

            if content is None:
                print("No contents found for " + url)
                continue

            if not os.path.exists(scraped_html_path):
                os.makedirs(scraped_html_path)

            file_name = url.replace("https://landing.clo-set.com", "").replace("/", "_").replace("\n", "").replace("?", "_")
            with open(os.path.join(scraped_html_path, f"{file_name}.html"), "w+", encoding="utf-8") as f:
                f.write("<html>\n" + content.prettify() + "\n" + "</html>")

    async def pyppeteer_scraper(self, url: str, tag_to_wait_for: str, tag_to_scrape: str) -> None:
        """
        Uses Pyppeteer to load a webpage, wait for a specific tag to be visible, and then scrape the inner HTML of that tag.
        The scraped HTML is then formatted and saved to a file.

        Args:
            url (str): The URL of the webpage to scrape.
            tag (str): The tag to wait for and scrape.
        """

        browser = await launch()

        page = await browser.newPage()

        await page.goto(url, {"waitUntil": "networkidle0"})

        html = await page.content()
        content = self.format_html(url, html)

        file_name = url.replace("https://clo3d.com/", "").replace("/", "_").replace("\n", "").replace("?", "_")
        with open(os.path.join(scraped_html_path, f"{file_name}.html"), "w+", encoding="utf-8") as f:
            f.write("<html>\n" + content.prettify() + "\n" + "</html>")

        await browser.close()

    @staticmethod
    def generate_openai_document(env: Environment, brand: str, scraped_html_path: str, page: str):
        """
        Navigates and outlines a webpage using OpenAI's API.
        Args:
            env (str): The environment in which the scraper is running.
            brand (str): The brand associated with the scraping task.
            web_scraper_path (str): The base path where the web scraper files are located.
            page (str): The HTML page to be navigated and outlined.
        Returns:
            None
        """
        environment = Environment(env, brand)

        print("Creating Navigation for " + page)
        with open(os.path.join(scraped_html_path, page), "r", encoding="utf-8") as f:
            scraped_content = Landing.reduce_tokens(f.read())

            url = "https://clo3d.com/" + page.replace(".html", "").replace("_", "/").replace("/userType", "?userType")

            try:
                navigate = environment.openai_helper.scrape_webpage(scraped_content, url)
            except Exception as e:
                print(e)

            # outline = environment.openai_helper.outline_webpage(scraped_content, url)

            if not os.path.exists(os.path.join(openai_html_path)):
                os.makedirs(os.path.join(openai_html_path))

            outline = re.sub(r"<.*?>", "", scraped_content)
            with open(os.path.join(openai_html_path, page.replace(".html", ".txt")), "w+", encoding="utf-8") as f:
                f.write(navigate + "\n\n" + outline.replace("\n", " ").strip())

    def mp_generate_openai_documents(self):
        navigate_html_openai_params = []

        for page in os.listdir(scraped_html_path):
            navigate_html_openai_params.append((self.env, self.brand, project_path, page))

        with multiprocessing.Pool(3) as p:
            p.starmap_async(Landing.generate_openai_document, navigate_html_openai_params, error_callback=lambda e: print(e))
            p.close()
            p.join()

    @staticmethod
    def upload_document(env: Environment, brand: str, openai_html_path: str, page: str):
        """
        Uploads the OpenAI HTML to Azure Search.

        Args:
            env (Environment): The environment in which the scraper is running.
            brand (str): The brand associated with the scraping task.
            openai_html_path (str): The path to the OpenAI HTML file.
            page (str): Name of the page to be uploaded.
        """
        print("Uploading " + page)
        environment = Environment(env, brand)

        with open(os.path.join(openai_html_path, page), "r", encoding="utf-8") as f:
            # Read the content of the OpenAI HTML file
            content = f.read()

            # Extract the title from the OpenAI HTML file
            # title = environment.openai_helper.create_webpage_title(content).replace('"', "").replace("*", "").replace("Title: ", "").replace("#", "")
            title = "Guide to Features, Patch Notes, and Latest Bug Fixes"

            # Create the Azure Search document
            document = {
                "@search.action": "mergeOrUpload",
                "ArticleId": shortuuid.uuid(),
                "Title": title,
                "Content": re.sub(r"\s+", " ", content.replace("\n", " ")),
                "Source": "https://clo3d.com/" + page.replace(".txt", "").replace("_", "/").replace("/userType", "?userType"),
                "YoutubeLinks": [],
            }

            # Generate the embeddings for the title and content
            document["TitleVector"] = environment.openai_helper.generate_embeddings(title)
            document["ContentVector"] = environment.openai_helper.generate_embeddings(content)

            # Upload the document to Azure Search
            environment.search_client.upload_documents([document])

    def mp_upload_documents(self):
        """
        Uploads all OpenAI HTML documents to Azure Search.

        This function is run in parallel using multiprocessing to speed up the upload process.
        """
        upload_openai_html_params = []

        # Loop through all OpenAI HTML files in the openai_html directory
        for page in os.listdir(os.path.join(project_path, "landing", "openai_html")):
            # Create a tuple of parameters to pass to the upload_openai_html function
            upload_openai_html_params.append((self.env, self.brand, os.path.join(project_path, "landing", "openai_html", page), page))

        # Upload all OpenAI HTML documents in parallel using multiprocessing
        with multiprocessing.Pool(5) as p:
            p.starmap_async(Landing.upload_document, upload_openai_html_params, error_callback=lambda e: print(e))
            p.close()
            p.join()

    def find_all_ai_search_documents(self):
        results = self.environment.search_client.search(search_fields=["Source"], search_text="https://clo3d.com", search_mode="all")

        documents = []
        for r in results:
            documents.append({"ArticleId": r["ArticleId"], "Source": r["Source"]})

        return documents

    def delete_ai_search_document(self, article_id):
        document = {"@search.action": "delete", "ArticleId": article_id}
        self.environment.search_client.upload_documents([document])

    def delete_all_ai_search_documents(self):
        documents = self.find_all_ai_search_documents()

        for document in documents:
            document["@search.action"] = "delete"
            print("Deleting " + document["ArticleId"])
            self.environment.search_client.upload_documents([document])


if __name__ == "__main__":
    env = questionary.select("Which environment?", choices=["dev", "prod"]).ask()
    brand = questionary.select("Which brand?", choices=["allinone", "clo3d", "closet", "md"]).ask()
    task = questionary.select(
        "What task?",
        choices=[
            "Scrape All URLs",
            "Scrape HTML Page",
            "Scrape All HTML Pages",
            "Generate OpenAI Document",
            "Generate All OpenAI Documents",
            "Find All AI Search Documents",
            "Delete AI Search Document",
            "Delete All AI Search Documents",
            "Upload Document",
            "Upload All Documents",
        ],
    ).ask()

    web_scraper = Landing(Environment(env, brand))

    if task == "Scrape All URLs":
        web_scraper.scrape_all_page_urls("https://landing.clo-set.com/allatonce")

        if not os.path.exists(os.path.join(project_path, "websites", "landing")):
            os.makedirs(os.path.join(project_path, "websites", "landing"), exist_ok=True)

        with open(os.path.join(project_path, "websites", "landing", "scraped_urls.txt"), "w+") as f:
            for url in urls:
                f.write(url + "\n")

    elif task == "Scrape HTML Page":
        urls = []
        if os.path.exists(os.path.join(project_path, "websites", "landing", "scraped_urls.txt")):
            with open(os.path.join(project_path, "websites", "landing", "scraped_urls.txt"), "r") as f:
                urls = [url.strip() for url in f.readlines()]

        if len(urls) > 0:
            url = questionary.select("Which URL?", choices=urls).ask()
        else:
            url = questionary.text("URL").ask()

        web_scraper.scrape_all_pages([url])

    elif task == "Scrape All HTML Pages":
        urls = []
        if os.path.exists(os.path.join(project_path, "websites", "landing", "scraped_urls.txt")):
            with open(os.path.join(project_path, "websites", "landing", "scraped_urls.txt"), "r") as f:
                urls = [url.strip() for url in f.readlines()]

        web_scraper.scrape_all_pages(urls)

    elif task == "Generate OpenAI Document":
        page = questionary.select(
            "Which HTML page?",
            choices=os.listdir(scraped_html_path),
        ).ask()

        web_scraper.generate_openai_document(
            Environment(env, brand),
            brand,
            scraped_html_path,
            page,
        )
    elif task == "Generate All OpenAI Documents":
        web_scraper.mp_generate_openai_documents()

    elif task == "Upload Document":
        page = questionary.select(
            "Which OpenAI page?",
            choices=os.listdir(openai_html_path),
        ).ask()

        web_scraper.upload_document(
            Environment(env, brand),
            brand,
            openai_html_path,
            page,
        )

    elif task == "Upload All Documents":
        web_scraper.mp_upload_documents()

    elif task == "Delete AI Search Document":
        article_id = questionary.text("Article ID?").ask()
        web_scraper.delete_ai_search_document(article_id)

    elif task == "Delete All AI Search Documents":
        web_scraper.delete_all_ai_search_documents()

    elif task == "Find All AI Search Documents":
        web_scraper.find_all_ai_search_documents()
