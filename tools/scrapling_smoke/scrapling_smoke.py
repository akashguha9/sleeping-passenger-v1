from scrapling.fetchers import Fetcher, DynamicFetcher


def main() -> None:
    page = Fetcher.get("https://example.com")
    print("HTTP title:", page.css("h1::text").get())

    browser_page = DynamicFetcher.fetch(
        "https://example.com",
        disable_resources=True,
        block_ads=True,
    )
    print("Browser title:", browser_page.css("h1::text").get())


if __name__ == "__main__":
    main()