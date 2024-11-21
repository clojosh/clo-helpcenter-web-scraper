import asyncio
import json
import multiprocessing
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import questionary
import requests
import shortuuid
from bs4 import BeautifulSoup, NavigableString, Tag, element
from playwright.async_api import Page, async_playwright
from requests_html import HTMLSession

from tools.azure_env import AzureEnv

scraped_urls = set()
project_path = os.path.dirname(os.path.abspath(__file__))
scraped_html_path = os.path.join(project_path, "websites", "closet_dashboard", "scraped_html")
openai_html_path = os.path.join(project_path, "websites", "closet_dashboard", "openai_html")


class CLOSET:
    def __init__(self, azure_env: AzureEnv):
        self.azure_env = azure_env
        self.brand = azure_env.brand
        self.language = azure_env.language
        self.search_client = azure_env.search_client
        self.openai_helper = azure_env.openai_helper

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
            "poster",
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
            .replace(' href="/', ' href="https://style.clo-set.com/')
            .replace("cd7a0ffabc84f4fe498b", "[user id]")
            .replace("joshua.lee@clo3d.com", "[user email]")
            .replace("joshua.lee", "[user name]")
            .replace("joshua.lee%40clo3d.com", "[user email]")
            .replace("jlee7772@gmail.com", "[user email]")
            .replace("jlee7772%40gmail.com", "[user email]")
            .replace("jlee7772", "[user name]")
        )

        soup = self.remove_unnecessary_tags(html)
        contents = self.remove_tag_attributes(soup.find("body"))

        return contents

    async def playwright_scrape_all_page_urls(self, website: str):
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False, args=["--start-maximized"])
            page = await browser.new_page(no_viewport=True)

            await page.goto(website, wait_until="networkidle")

            await self.login(page, "joshua.lee@clo3d.com", "Boxerlee2015!13")
            await self.cookie_consent(page)
            await self.scrape_all_page_urls(page, website)

            await browser.close()

    async def cookie_consent(self, page: Page):
        cookie = await page.wait_for_selector("//html/body/div[2]/div/div/div/button", timeout=3000)

        if cookie:
            await cookie.click()

    async def login(self, page: Page, email: str, password: str):
        await page.fill("input[type='email']", email)
        await page.fill("input[type='password']", password)
        await page.click("body > div.css-eru734 > div.css-1pjas8e > div.css-1p6caij > div > div.css-bxpdjb > button.round.css-11ms28s.elfce4j0")

    async def scrape_all_page_urls(self, page: Page, website: str):
        """
        Recursively scrape every page URL from the website

        Args:
            website (str): The URL of the website to scrape

        Returns:
            None
        """

        excluded_pages = [
            "https://style.clo-set.com/service/solutions-individuals",
            "https://style.clo-set.com/service/features",
            "https://style.clo-set.com/service/pricing",
            "https://style.clo-set.com/service/solutions-manufacturers",
            "https://style.clo-set.com/service/solutions-brands",
            "https://style.clo-set.com/service/contactus",
            "https://style.clo-set.com/aboutus]",
        ]

        await page.goto(website, wait_until="networkidle")

        try:
            anchors = await page.locator("a").all()

            for tag in anchors:
                href = await tag.get_attribute("href") or ""
                href = "https://style.clo-set.com" + href.strip() if href.startswith("/") else href.strip()
                print(href)

                if href in scraped_urls or href == "" or href.startswith("#") or "https://style.clo-set.com" not in href or href in excluded_pages:
                    continue
                else:
                    scraped_urls.add(href)
                    # Recursively call the function on the new URL
                    await self.scrape_all_page_urls(page, href)
        except Exception as e:
            print(e)
            return

    async def scrape_all_pages(self, scraped_urls=[]):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
            page = await browser.new_page(no_viewport=True)

            for url in scraped_urls:
                print("Scraping " + url)

                await page.goto(url, wait_until="networkidle")
                await self.login(page, "joshua.lee@clo3d.com", "Boxerlee2015!13")
                await self.cookie_consent(page)

                page_content = await page.content()
                formatted_content = self.format_html(url, page_content)

                if formatted_content is None:
                    print("Nothing Found" + "\n")
                    continue

                if not os.path.exists(os.path.join(scraped_html_path)):
                    os.makedirs(os.path.join(scraped_html_path))

                file_name = url.replace("https://style.clo-set.com/", "").replace("/", "_").replace("\n", "").replace("?", "_")
                with open(os.path.join(scraped_html_path, f"{file_name}.html"), "w+", encoding="utf-8") as f:
                    f.write("<html>\n" + formatted_content.prettify() + "\n" + "</html>")

    @staticmethod
    def generate_openai_document(stage: str, brand: str, page: str):
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
        azure_env = AzureEnv(stage, brand)

        print("Creating Navigation for " + page)
        with open(os.path.join(scraped_html_path, page), "r", encoding="utf-8") as f:
            scraped_content = CLOSET.reduce_tokens(f.read())

            url = "https://style.clo-set.com/" + page.replace(".html", "").replace("_", "/").replace("/userType", "?userType")

            try:
                navigate = azure_env.openai_helper.scrape_webpage(scraped_content, url)
            except Exception as e:
                print(e)

            outline = azure_env.openai_helper.outline_webpage(scraped_content, url)
            outline = re.sub(r"<.*?>", "", scraped_content)

            if not os.path.exists(openai_html_path):
                os.makedirs(openai_html_path)

            with open(os.path.join(openai_html_path, page.replace(".html", ".txt")), "w+", encoding="utf-8") as f:
                f.write(navigate + "\n\n" + outline.replace("\n", " ").strip())

    def mp_generate_openai_documents(self):
        navigate_html_openai_params = []

        for page in os.listdir(os.path.join(scraped_html_path)):
            navigate_html_openai_params.append((self.azure_env.stage, self.brand, page))

        with multiprocessing.Pool(3) as p:
            p.starmap_async(CLOSET.generate_openai_document, navigate_html_openai_params, error_callback=lambda e: print(e))
            p.close()
            p.join()

    @staticmethod
    def upload_document(stage: str, brand: str, page: str):
        """
        Uploads the OpenAI HTML to Azure Search.

        Args:
            stage : The stage in which the scraper is running.
            brand (str): The brand associated with the scraping task.
            openai_html_path (str): The path to the OpenAI HTML file.
            page (str): Name of the page to be uploaded.
        """
        print("\nUploading " + page)
        azure_env = AzureEnv(stage, brand)

        with open(os.path.join(openai_html_path, page), "r", encoding="utf-8") as f:
            # Read the content of the OpenAI HTML file
            content = f.read()

            # Extract the title from the OpenAI HTML file
            title = (
                azure_env.openai_helper.create_webpage_title(content)
                .replace('"', "")
                .replace("*", "")
                .replace("Title: ", "")
                .replace("#", "")
                .strip()
            )
            # title = "Guide to Features, Patch Notes, and Latest Bug Fixes"

            # Create the Azure Search document
            document = {
                "@search.action": "mergeOrUpload",
                "ArticleId": shortuuid.uuid(),
                "Title": title,
                "Content": re.sub(r"\s+", " ", content.replace("\n", " ")),
                "Source": "https://style.clo-set.com/"
                + re.sub(r"_\d+", "", page).replace(".txt", "").replace("_", "/").replace("/userType", "?userType"),
                "YoutubeLinks": [],
            }

            # Generate the embeddings for the title and content
            document["TitleVector"] = azure_env.openai_helper.generate_embeddings(title)
            document["ContentVector"] = azure_env.openai_helper.generate_embeddings(content)

            # Upload the document to Azure Search
            azure_env.search_client.upload_documents([document])
            print("Done" + page)

    def mp_upload_documents(self):
        """
        Uploads all OpenAI HTML documents to Azure Search.

        This function is run in parallel using multiprocessing to speed up the upload process.
        """
        upload_openai_html_params = []

        # Loop through all OpenAI HTML files in the openai_html directory
        for page in os.listdir(os.path.join(openai_html_path)):
            # Create a tuple of parameters to pass to the upload_openai_html function
            upload_openai_html_params.append((self.azure_env.stage, self.brand, page))

        # Upload all OpenAI HTML documents in parallel using multiprocessing
        with multiprocessing.Pool(5) as p:
            p.starmap_async(CLOSET.upload_document, upload_openai_html_params, error_callback=lambda e: print(e))
            p.close()
            p.join()


if __name__ == "__main__":
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

    if task in ["Scrape All URLs", "Scrape HTML Page", "Scrape All HTML Pages"]:
        web_scraper = CLOSET(AzureEnv("dev", "closet"))

        if task == "Scrape All URLs":
            asyncio.run(web_scraper.playwright_scrape_all_page_urls("https://style.clo-set.com/en/account/signin"))

            if not os.path.exists(os.path.join(project_path, "websites", "closet_dashboard")):
                os.makedirs(os.path.join(project_path, "websites", "closet_dashboard"), exist_ok=True)

            with open(os.path.join(project_path, "websites", "closet_dashboard", "scraped_urls.txt"), "w+") as f:
                for url in scraped_urls:
                    f.write(url + "\n")

        elif task == "Scrape HTML Page":
            urls = []
            if os.path.exists(os.path.join(project_path, "websites", "closet_dashboard", "scraped_urls.txt")):
                with open(os.path.join(project_path, "websites", "closet_dashboard", "scraped_urls.txt"), "r") as f:
                    urls = [url.strip() for url in f.readlines()]

            if len(urls) > 0:
                url = questionary.select("Which URL?", choices=urls).ask()
            else:
                url = questionary.text("URL").ask()

            asyncio.run(web_scraper.scrape_all_pages([url]))

        elif task == "Scrape All HTML Pages":
            urls = []
            if os.path.exists(os.path.join(project_path, "websites", "closet_dashboard", "scraped_urls.txt")):
                with open(os.path.join(project_path, "websites", "closet_dashboard", "scraped_urls.txt"), "r") as f:
                    urls = [url.strip() for url in f.readlines()]

            asyncio.run(web_scraper.scrape_all_pages(urls))

    else:
        stage = questionary.select("Which stage?", choices=["dev", "prod"]).ask()
        brand = questionary.select("Which brand?", choices=["allinone", "clo3d", "closet", "md"]).ask()
        web_scraper = CLOSET(AzureEnv(stage, brand))

        if task == "Generate OpenAI Document":
            page = questionary.select(
                "Which HTML page?",
                choices=sorted(os.listdir(scraped_html_path)),
            ).ask()

            web_scraper.generate_openai_document(
                stage,
                brand,
                page,
            )

        elif task == "Generate All OpenAI Documents":
            web_scraper.mp_generate_openai_documents()

        elif task == "Upload Document":
            page = questionary.select(
                "Which OpenAI page?",
                choices=sorted(os.listdir(openai_html_path)),
            ).ask()

            web_scraper.upload_document(
                stage,
                brand,
                page,
            )

        elif task == "Upload All Documents":
            web_scraper.mp_upload_documents()
