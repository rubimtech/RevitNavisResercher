"""
rvtdocs.com HTML page parser — extracts structured markdown from API docs.
"""

import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from server.state import get_http


async def fetch_and_parse_rvtdocs_page(url: str) -> dict:
    """Fetch an rvtdocs.com page and extract structured content as markdown."""
    client = await get_http()
    base_url = url if url.startswith("http") else f"https://rvtdocs.com{url}"
    parsed = urlparse(base_url)
    if parsed.netloc not in ("rvtdocs.com", "www.rvtdocs.com"):
        return {"error": f"URL must be on rvtdocs.com, got: {parsed.netloc}"}
    base_url = base_url.split("?")[0]

    r = await client.get(f"{base_url}?ajax=1", follow_redirects=True)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")
    md_parts: list[str] = []

    # ── Namespace ──
    ns_el = soup.find(class_="card-namespace")
    if ns_el:
        text = ns_el.get_text(strip=True)
        if "Namespace:" in text:
            ns = text.replace("Namespace:", "").strip()
            md_parts.append(f"**Namespace:** {ns}\n")

    # ── Title + Type badge ──
    title_card = soup.find(class_="card-title")
    if title_card:
        h1 = title_card.find("h1")
        if h1:
            md_parts.append(f"# {h1.get_text(strip=True)}\n")
        badge = title_card.find(class_="bg-gray-200")
        if badge:
            md_parts.append(f"**Type:** {badge.get_text(strip=True)}\n")

    # ── Description ──
    desc_el = soup.find(class_="card-description")
    if desc_el:
        html = _extract_inner_html(desc_el)
        html = html.replace("<strong>Description:</strong>", "").strip()
        text = _html_to_markdown(html)
        if text:
            md_parts.append(f"## Description\n\n{text}\n")

    # ── Remarks ──
    remarks_el = soup.find(class_="card-remarks")
    if remarks_el:
        html = _extract_inner_html(remarks_el)
        html = html.replace("<strong>Remarks:</strong>", "").strip()
        text = _html_to_markdown(html)
        if text:
            md_parts.append(f"## Remarks\n\n{text}\n")

    # ── Hierarchy ──
    hierarchy_section = soup.find(
        lambda tag: tag.name == "div"
        and tag.get("class")
        and "hierarchy" in " ".join(tag.get("class", []))
    )
    if hierarchy_section:
        text = hierarchy_section.get_text(" ", strip=True)
        if text:
            md_parts.append(f"## Hierarchy\n\n{text}\n")

    # ── Syntax sections ──
    for card_title in soup.find_all(class_="card-title"):
        if "Syntax" in card_title.get_text():
            parent_card = card_title.find_parent(class_="card")
            if parent_card:
                md_parts.append("## Syntax\n")
                for snippet in parent_card.find_all(class_="code-snippet"):
                    code_el = snippet.find("code")
                    if code_el:
                        code_text = code_el.get_text()
                        code_class = code_el.get("class", "") or ""
                        lang = "vbnet" if "vbnet" in " ".join(code_class) else (
                            "cpp" if "cpp" in " ".join(code_class) else "csharp"
                        )
                        md_parts.append(f"```{lang}\n{code_text}\n```\n")

    # ── Tables ──
    for table in soup.find_all("table"):
        md_table = _extract_markdown_table(table)
        if md_table:
            md_parts.append(md_table)

    markdown = "\n".join(md_parts)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()

    return {
        "url": base_url,
        "markdown": markdown,
        "description": _extract_meta_desc(soup),
    }


def _extract_inner_html(tag: Tag) -> str:
    return "".join(str(child) for child in tag.children)


def _html_to_markdown(html: str) -> str:
    result = html
    result = re.sub(r"<br\s*/?>", "\n", result)
    result = re.sub(r"<p>", "", result)
    result = re.sub(r"</p>", "\n", result)
    result = re.sub(r"<strong>(.*?)</strong>", r"**\1**", result)
    result = re.sub(r"<ul>", "", result)
    result = re.sub(r"</ul>", "", result)
    result = re.sub(r"<ol>", "", result)
    result = re.sub(r"</ol>", "", result)
    result = re.sub(r"<li>(.*?)</li>", r"- \1", result)
    result = re.sub(r"<[^>]+>", "", result)
    result = re.sub(r"\n ", "\n", result)
    return result.strip()


def _extract_markdown_table(table: Tag) -> str:
    lines: list[str] = []
    thead = table.find("thead")
    tbody = table.find("tbody")

    if thead:
        header_row = thead.find("tr")
        if header_row:
            headers = [
                th.get_text(" ", strip=True) for th in header_row.find_all("th")
            ]
            lines.append(f"| {' | '.join(headers)} |")
            lines.append(f"|{'|'.join('---' for _ in headers)}|")

    if tbody:
        for row in tbody.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if cells:
                lines.append(f"| {' | '.join(cells)} |")

    return "\n".join(lines) + "\n" if lines else ""


def _extract_meta_desc(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": "description"})
    return meta.get("content", "")[:500] if meta else ""
