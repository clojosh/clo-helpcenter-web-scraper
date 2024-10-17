import asyncio
import json
import multiprocessing
import os
import re
import sys
from pathlib import Path

import questionary
import requests
import shortuuid
from bs4 import BeautifulSoup, NavigableString, Tag, element
from pyppeteer import launch

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
        self.web_scraper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)))

    def reduce_tokens(scraped_content):
        scraped_content = re.sub(r">\s+<", "><", scraped_content)
        scraped_content = re.sub(r"\s{2,}", " ", scraped_content)
        scraped_content = scraped_content.replace("<div></div>", "")
        scraped_content = scraped_content.replace(" <", "<")
        scraped_content = scraped_content.replace(" />", "/>")
        scraped_content = scraped_content.replace(" >", ">")
        scraped_content = scraped_content.replace("<picture>", "")
        scraped_content = scraped_content.replace("</picture>", "")
        scraped_content = scraped_content.replace('target="_self"', "")

        return scraped_content

    def remove_tag_attributes(self, tag) -> Tag:
        # REMOVE_ATTRIBUTES = [
        #     'lang', 'language', 'onmouseover', 'onmouseout', 'script', 'style', 'font', 'dir', 'face', 'size', 'color', 'style', 'class', 'width', 'height', 'hspace', 'border',
        #     'valign', 'align', 'background', 'bgcolor', 'text', 'link', 'vlink', 'alink', 'cellpadding', 'cellspacing'
        # ]
        REMOVE_ATTRIBUTES = ['class', 'style', 'target', 'tabindex', 'rel']

        for t in tag.descendants:
            if isinstance(t, element.Tag):
                t.attrs = {key: value for key, value in t.attrs.items() if key not in REMOVE_ATTRIBUTES}

        for t in tag.find_all(lambda t: any(i.startswith('data-') for i in t.attrs)):
            for attr in list(t.attrs):
                if attr.startswith('data-'):
                    del t.attrs[attr]

        return tag

    async def recursively_scrape_urls(self, url):
        """
        Recursively scrape all URLs from every page
        """

        soup = await self.scrape_html(url)

        excluded_pages = []
        for tag in soup.find_all('a', href=True):
            href = tag.get("href")
            print(href)
            if (href.startswith("https://style.clo-set.com/") or href.startswith("./")) and any(page in href for page in excluded_pages) is False:

                if not href.startswith("https://clo3d.com"):
                    href = "https://landing.clo-set.com/" + href.replace("./", "")

                if href not in urls:
                    urls.append(href.strip())
                    await self.recursively_scrape_urls(href)
            else:
                continue

        return urls

    async def scrape_html(self, url):
        browser = await launch()
        page = await browser.newPage()
        await page.goto(url)

        # await page.waitForSelector('iframe')
        # iframe_element = await page.querySelector('iframe')
        # iframe = await iframe_element.contentFrame()
        # await iframe.waitForSelector('body')

        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        # iframe_tag = soup.find('iframe')

        # iframe_soup = BeautifulSoup(await iframe.content(), "html.parser")
        # main_tag = iframe_soup.find('div', id='main')

        # iframe_tag.append(main_tag)

        await browser.close()

        tags = soup.find_all("svg") + soup.find_all("link") + soup.find_all("script") + soup.find_all("noscript") + soup.find_all("style")
        for tag in tags:
            tag.decompose()

        soup = self.remove_tag_attributes(soup.find("body"))

        return soup

    def navigate_html_openai(env, brand, web_scraper_path, page):
        environment = Environment(env, brand)

        print("Creating Navigation for " + page)
        with open(os.path.join(web_scraper_path, "clo3d.com", "scraped_html", page), "r", encoding="utf-8") as f:
            scraped_content = WebScraper.reduce_tokens(f.read())

            url = "https://style.clo-set.com//" + page.replace('.html', '').replace('_', '/').replace('/userType', '?userType')
            try:
                navigate = environment.openai_helper.scrape_webpage(scraped_content, url)
                outline = environment.openai_helper.outline_webpage(scraped_content, url)
                with open(os.path.join(web_scraper_path, "clo3d.com", "openai_html", page.replace('.html', '.txt')), "w+", encoding="utf-8") as f:
                    # navigate = re.findall(r"\d+\.\s.*", navigate)
                    # f.write("\n".join(navigate))
                    f.write(navigate + "\n\n" + outline)
            except Exception as e:
                print(e)

    def mp_navigate_html_openai(self):
        navigate_html_openai_params = []

        for page in os.listdir(os.path.join(self.web_scraper_path, "clo3d.com", "scraped_html")):
            navigate_html_openai_params.append((self.env, self.brand, self.web_scraper_path, page))

        with multiprocessing.Pool(5) as p:
            p.starmap_async(WebScraper.navigate_html_openai, navigate_html_openai_params, error_callback=lambda e: print(e))
            p.close()
            p.join()

    def upload_openai_html(env, brand, openai_html_path, page):
        environment = Environment(env, brand)

        with open(openai_html_path, "r", encoding="utf-8") as f:
            content = f.read()
            title = environment.openai_helper.create_webpage_title(content).replace('"', '')

            document = {
                "@search.action": "mergeOrUpload",
                "ArticleId": shortuuid.uuid(),
                "Title": title,
                "Content": content,
                "Source": "https://style.clo-set.com//" + page.replace('.txt', '').replace('_', '/').replace('/userType', '?userType'),
                "Labels": [],
                "YoutubeLinks": [],
            }

            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "clo3d.com", "ai_documents", page.replace(".txt", ".json")), "w+", encoding="utf-8") as f:
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
        ai_document_path = os.path.join(self.web_scraper_path, "clo3d.com", "ai_documents")
        for page in os.listdir(ai_document_path):
            with open(os.path.join(ai_document_path, page), "r", encoding="utf-8") as f:
                document = json.load(f)
                document["@search.action"] = "delete"
                self.environment.search_client.upload_documents([document])
        # document = {"@search.action": "delete", "ArticleId": "9t8pGkiamT4GjHn9nCC8vn"}
        # self.environment.search_client.upload_documents([document])


if __name__ == "__main__":
    url = 'https://style.clo-set.com/aboutus'

    web_scraper = WebScraper(Environment("dev", "clo3d"))

    task = questionary.select(f"What task?", choices=["Scrape All URLs", "Scrape HTML", "Navigate HTML", "Upload HTML", "Delete AI Search HTML Documents"]).ask()

    if task == "Scrape All URLs":
        loop = asyncio.get_event_loop()
        urls = loop.run_until_complete(web_scraper.recursively_scrape_urls("https://style.clo-set.com/"))

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "clo-set.com", "scraped_urls.txt"), "w+") as f:
            for url in urls:
                f.write(url + "\n")

    elif task == "Scrape HTML":
        loop = asyncio.get_event_loop()
        html = loop.run_until_complete(web_scraper.scrape_html("https://style.clo-set.com/service/features"))
        file_name = url.replace('https://style.clo-set.com/', '').replace('/', '_').replace('\n', '').replace('?', '_')

        with open(os.path.join(web_scraper.web_scraper_path, "clo-set.com", "scraped_html", f"{file_name}.html"), "w+", encoding="utf-8") as f:
            f.write(html.prettify())

    elif task == "Navigate HTML":
        web_scraper.mp_navigate_html_openai()
    elif task == "Upload HTML":
        web_scraper.mp_upload_openai_html()
    elif task == "Delete AI Search HTML Documents":
        web_scraper.delete_ai_search_html_documents()

    # loop = asyncio.get_event_loop()
    # html = loop.run_until_complete(web_scraper.scrape_iframe_html(url))
    # with open(os.path.join(web_scraper.web_scraper_path, "clo-set.com", "scraped_html", f"{file_name}.html"), "w+", encoding="utf-8") as f:
    #     f.write(html)

    # soup = web_scraper.scrape_html(url)
    # with open(os.path.join(web_scraper.web_scraper_path, "clo-set.com", "scraped_html", f"{file_name}.html"), "w+", encoding="utf-8") as f:
    #     f.write("<html>\n" + soup.prettify() + "\n" + "</html>")

    # with open(os.path.join(web_scraper.web_scraper_path, "clo-set.com", "scraped.html"), "r", encoding="utf-8") as f:
    #     html = f.read()
    #     web_scraper.scrape_urls(html)
    # with open(os.path.join(web_scraper.web_scraper_path, "clo-set.com", "scraped_urls.txt"), "w+") as f:
    #     for url in urls:
    #         f.write(url + "\n")
