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

backend_dir = Path(__file__).parent.parent

sys.path.append(str(os.path.join(backend_dir, "ai_search")))
from tools.environment import Environment

urls = []


class WebScraper:
    def __init__(self, environment: Environment):
        self.env = environment.env
        self.environment = environment
        self.brand = environment.brand
        self.language = environment.language
        self.search_client = environment.search_client
        self.openai_helper = environment.openai_helper
        self.web_scraper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "websites")

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
                with open(os.path.join(self.web_scraper_path, "clo3d.com", "scraped_content", f"{url.strip()}.txt"), "w+", encoding="utf-8") as f:
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

        return soup

    def format_html(self, url: str, html: str):
        html = (
            html.replace("<!--[-->", "")
            .replace("<!--]-->", "")
            .replace("<!--", "")
            .replace("-->", "")
            .replace(' href="/', ' href="https://clo3d.com/')
        )
        soup = self.remove_unnecessary_tags(html)

        if url == "https://clo3d.com/en/":
            contents = self.remove_tag_attributes(soup.find("body"))
        else:
            contents = self.remove_tag_attributes(soup.find("main"))

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
        excluded_pages = [
            "legal/archives",
            "articles",
            "clo-users/stories/",
            "clo-users/summits/",
            "jobs/recruit/",
            "resources/esg/list?",
            "resources/notices/",
        ]

        # Find all 'a' tags with a href attribute
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")

            # Check if the URL is relative or absolute
            if (
                (href.startswith("https://clo3d.com") or href.startswith("/"))
                and any(page in href for page in excluded_pages) is False
                and "#" not in href
                and re.search(r"resources/esg/\d+", href) is None
            ):
                # If the URL is relative, add the base URL
                if not href.startswith("https://clo3d.com"):
                    href = "https://clo3d.com" + href

                # If the URL is not already in the list, add it
                if href not in urls and href != "https://clo3d.com/en/support":
                    print(href.strip())
                    urls.append(href.strip())

                    # Recursively call the function on the new URL
                    self.scrape_all_page_urls(href)
            else:
                continue

    def scrape_all_pages(self, scraped_urls=[]):
        session = HTMLSession()

        if len(scraped_urls) == 0:
            with open(os.path.join(self.web_scraper_path, "clo3d.com", "scraped_urls.txt"), "r") as f:
                scraped_urls = f.readlines()

        for url in scraped_urls:
            # Skip the download page because it has dynamic content
            if url == "https://clo3d.com/en/clo/download/installer" or url == "https://clo3d.com/en/company/partners":
                continue

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

            file_name = url.replace("https://clo3d.com/", "").replace("/", "_").replace("\n", "").replace("?", "_")
            with open(os.path.join(self.web_scraper_path, "clo3d.com", "scraped_html", f"{file_name}.html"), "w+", encoding="utf-8") as f:
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
        with open(os.path.join(self.web_scraper_path, "clo3d.com", "scraped_html", f"{file_name}.html"), "w+", encoding="utf-8") as f:
            f.write("<html>\n" + content.prettify() + "\n" + "</html>")

        await browser.close()

    @staticmethod
    def generate_navigation_outline_html_openai(env: Environment, brand: str, scraped_html_path: str, page: str):
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
        with open(os.path.join(scraped_html_path, "clo3d.com", "scraped_html", page), "r", encoding="utf-8") as f:
            scraped_content = WebScraper.reduce_tokens(f.read())

            url = "https://clo3d.com/" + page.replace(".html", "").replace("_", "/").replace("/userType", "?userType")

            try:
                navigate = environment.openai_helper.scrape_webpage(scraped_content, url)
            except Exception as e:
                print(e)

            # outline = environment.openai_helper.outline_webpage(scraped_content, url)

            outline = re.sub(r"<.*?>", "", scraped_content)
            with open(os.path.join(scraped_html_path, "clo3d.com", "openai_html", page.replace(".html", ".txt")), "w+", encoding="utf-8") as f:
                f.write(navigate + "\n\n" + outline)

    def mp_generate_navigation_outline_html_openai(self):
        navigate_html_openai_params = []

        for page in os.listdir(os.path.join(self.web_scraper_path, "clo3d.com", "scraped_html")):
            navigate_html_openai_params.append((self.env, self.brand, self.web_scraper_path, page))

        with multiprocessing.Pool(3) as p:
            p.starmap_async(WebScraper.generate_navigation_outline_html_openai, navigate_html_openai_params, error_callback=lambda e: print(e))
            p.close()
            p.join()

    @staticmethod
    def upload_openai_html(env: Environment, brand: str, openai_html_path: str, page: str):
        print("Uploading " + page)
        environment = Environment(env, brand)

        with open(openai_html_path, "r", encoding="utf-8") as f:
            content = f.read()
            title = environment.openai_helper.create_webpage_title(content).replace('"', "").replace("*", "").replace("Title: ", "").replace("#", "")

            document = {
                "@search.action": "mergeOrUpload",
                "ArticleId": shortuuid.uuid(),
                "Title": title,
                "Content": re.sub(r"\s+", " ", content.replace("\n", " ")),
                "Source": "https://clo3d.com/" + page.replace(".txt", "").replace("_", "/").replace("/userType", "?userType"),
                "YoutubeLinks": [],
            }

            document_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "websites",
                "clo3d.com",
                "ai_documents",
                environment.env,
                datetime.today().strftime("%Y_%m_%d"),
            )
            if not os.path.exists(document_dir):
                os.mkdir(document_dir)

            with open(os.path.join(document_dir, page.replace(".txt", ".json")), "w+", encoding="utf-8") as f:
                json.dump(document, f)

            document["TitleVector"] = environment.openai_helper.generate_embeddings(title)
            document["ContentVector"] = environment.openai_helper.generate_embeddings(content)

            environment.search_client.upload_documents([document])

    def mp_upload_openai_html(self):
        upload_openai_html_params = []

        for page in os.listdir(os.path.join(self.web_scraper_path, "clo3d.com", "openai_html")):
            upload_openai_html_params.append((self.env, self.brand, os.path.join(self.web_scraper_path, "clo3d.com", "openai_html", page), page))

        with multiprocessing.Pool(5) as p:
            p.starmap_async(WebScraper.upload_openai_html, upload_openai_html_params, error_callback=lambda e: print(e))
            p.close()
            p.join()

    def delete_ai_search_html_documents(self):
        ai_document_path = os.path.join(self.web_scraper_path, "clo3d.com", "ai_documents", self.env)

        # most_recent_uploaded_folder = os.listdir(ai_document_path)[-1]
        for folder in os.listdir(ai_document_path):
            for file in os.listdir(os.path.join(ai_document_path, folder)):
                with open(os.path.join(ai_document_path, folder, file), "r", encoding="utf-8") as f:
                    document = json.load(f)
                    document["@search.action"] = "delete"
                    self.environment.search_client.upload_documents([document])

    def delete_ai_search_html_document(self, article_id):
        document = {"@search.action": "delete", "ArticleId": article_id}
        self.environment.search_client.upload_documents([document])


if __name__ == "__main__":
    env = questionary.select("Which environment?", choices=["dev", "prod"]).ask()
    brand = questionary.select("Which brand?", choices=["clo3d", "closet", "md", "allinone"]).ask()
    task = questionary.select(
        "What task?",
        choices=[
            "Scrape All URLs",
            "Scrape HTML",
            "Scrape All HTML",
            "Generate Navigation Outline - Single Page",
            "Generate Navigation Outline - All Pages",
            "Upload Navigation Outline Documents",
            "Delete AI Search HTML Documents",
        ],
    ).ask()

    web_scraper = WebScraper(Environment(env, brand))

    if task == "Scrape All Page URLs":
        web_scraper.scrape_all_page_urls("https://clo3d.com")
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "clo3d.com", "scraped_urls.txt"), "w+") as f:
            for url in urls:
                f.write(url + "\n")
    elif task == "Scrape All HTML":
        web_scraper.scrape_all_pages()

        # Use pyppeteer to scrape the download page because it has dynamic content
        asyncio.get_event_loop().run_until_complete(web_scraper.pyppeteer_scraper("https://clo3d.com/en/clo/download/installer", "table", "main"))
        # Use pyppeteer to scrape the partners page because it has dynamic content
        asyncio.get_event_loop().run_until_complete(web_scraper.pyppeteer_scraper("https://clo3d.com/en/company/partners", "section", "main"))

    elif task == "Scrape HTML":
        if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "clo3d.com", "scraped_urls.txt")):
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "clo3d.com", "scraped_urls.txt"), "r") as f:
                urls = [url.strip() for url in f.readlines()]
                url = questionary.select("Which URL?", choices=urls).ask()
        else:
            url = questionary.text("URL").ask()
        web_scraper.scrape_all_pages([url])

    elif task == "Generate Navigation Outline - Single Page":
        scraped_html_path = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "websites"), "clo3d.com", "scraped_html")
        page = questionary.select(
            "Which HTML page?",
            choices=os.listdir(scraped_html_path),
        ).ask()

        web_scraper.generate_navigation_outline_html_openai(
            Environment(env, brand), brand, os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "websites")), page
        )
    elif task == "Generate Navigation Outline - All Pages":
        web_scraper.mp_generate_navigation_outline_html_openai()
    elif task == "Upload Navigation Outline Documents":
        web_scraper.mp_upload_openai_html()
    elif task == "Delete AI Search HTML Documents":
        web_scraper.delete_ai_search_html_documents()
