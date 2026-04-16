#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parts_db_mcp.py

MCP server for electronic component lookup via the LCSC public API.

Tools provided
  parts_search           Search components by keyword, category, or spec
  parts_get_detail       Get full specifications for a specific part number
  parts_find_alternatives  Find alternative/substitute parts for a given part
  parts_check_stock      Check real-time stock and pricing for a part number

Transport: stdio (for Claude Code / local API environment)

Setup
  pip install mcp httpx pydantic
  Add to .mcp.json — see project root for the generated config file.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Server initialisation
# ---------------------------------------------------------------------------

mcp = FastMCP("parts_db_mcp")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LCSC_SEARCH_URL  = "https://wmsc.lcsc.com/wmsc/search/global"
LCSC_DETAIL_URL  = "https://wmsc.lcsc.com/wmsc/product/detail"
LCSC_STOCK_URL   = "https://wmsc.lcsc.com/wmsc/product/price"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; embedded-engineering-skill/1.0; "
        "parts-lookup-bot)"
    ),
    "Accept": "application/json",
    "Referer": "https://www.lcsc.com/",
}

REQUEST_TIMEOUT = 12.0   # seconds

# ---------------------------------------------------------------------------
# Shared HTTP client (reused across requests)
# ---------------------------------------------------------------------------

_client: Optional[httpx.AsyncClient] = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(headers=HEADERS, timeout=REQUEST_TIMEOUT)
    return _client


# ---------------------------------------------------------------------------
# Shared error handler
# ---------------------------------------------------------------------------

def _handle_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return json.dumps({"error": "Part not found. Verify the part number."})
        if code == 429:
            return json.dumps({"error": "Rate limit reached. Wait a few seconds and retry."})
        if code == 403:
            return json.dumps({"error": f"Access denied (HTTP 403). The LCSC API may require a session cookie for this endpoint."})
        return json.dumps({"error": f"API error HTTP {code}: {exc.response.text[:200]}"})
    if isinstance(exc, httpx.TimeoutException):
        return json.dumps({"error": "Request timed out. Check network connectivity and retry."})
    if isinstance(exc, httpx.ConnectError):
        return json.dumps({"error": "Cannot connect to LCSC. Check network connectivity."})
    return json.dumps({"error": f"Unexpected error: {type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_part_number(pn: str) -> str:
    """Normalise a part number by stripping whitespace and common prefixes."""
    return pn.strip().upper()


def _format_price_breaks(price_list: List[Dict]) -> List[Dict]:
    """Extract and clean price-break information from LCSC response."""
    breaks = []
    for item in price_list:
        try:
            breaks.append({
                "quantity": item.get("startQty") or item.get("quantity"),
                "unit_price_usd": item.get("usdPrice") or item.get("price"),
                "unit_price_cny": item.get("cnyPrice") or item.get("cnyUnitPrice"),
            })
        except (KeyError, TypeError):
            continue
    return breaks


def _extract_specs(attr_list: List[Dict]) -> Dict[str, str]:
    """Convert LCSC attribute list to a flat key→value dict."""
    specs: Dict[str, str] = {}
    for attr in attr_list or []:
        key = attr.get("nameen") or attr.get("nameZh") or attr.get("name", "")
        val = attr.get("valueEn") or attr.get("valueZh") or attr.get("value", "")
        if key:
            specs[key] = val
    return specs


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON     = "json"


class PartsSearchInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    keyword: str = Field(
        ...,
        description=(
            "Search keyword. Can be a part number prefix, description, or "
            "specification. Examples: 'STM32F103', '10uF 16V capacitor', "
            "'LM358 op-amp', 'NRF24L01'."
        ),
        min_length=2,
        max_length=100,
    )
    category: Optional[str] = Field(
        default=None,
        description=(
            "Optional category filter. Examples: 'Microcontrollers', "
            "'Capacitors', 'Resistors', 'MOSFETs', 'RF Transceivers'."
        ),
    )
    in_stock_only: bool = Field(
        default=True,
        description="If True, return only parts that currently have stock.",
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results to return.",
        ge=1,
        le=50,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for readable summary, 'json' for raw data.",
    )


class PartsDetailInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    part_number: str = Field(
        ...,
        description=(
            "LCSC part number (C-prefixed) or manufacturer part number. "
            "Examples: 'C8734', 'STM32F103C8T6', 'C2040'."
        ),
        min_length=2,
        max_length=60,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format.",
    )


class PartsAlternativesInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    part_number: str = Field(
        ...,
        description="Part number to find alternatives for.",
        min_length=2,
        max_length=60,
    )
    max_price_premium_pct: float = Field(
        default=30.0,
        description=(
            "Maximum acceptable price premium over original part (%). "
            "Default 30 means alternatives up to 30 % more expensive are included."
        ),
        ge=0.0,
        le=500.0,
    )
    limit: int = Field(
        default=5,
        description="Maximum number of alternatives to return.",
        ge=1,
        le=20,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format.",
    )


class PartsStockInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    part_number: str = Field(
        ...,
        description="LCSC part number (C-prefixed) or manufacturer part number.",
        min_length=2,
        max_length=60,
    )
    quantity_needed: Optional[int] = Field(
        default=None,
        description=(
            "Your required quantity. If provided, the response highlights the "
            "applicable price break and whether stock covers your needs."
        ),
        ge=1,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format.",
    )


# ---------------------------------------------------------------------------
# Response formatters
# ---------------------------------------------------------------------------

def _fmt_search_markdown(items: List[Dict], keyword: str) -> str:
    if not items:
        return f"No parts found for **{keyword}**. Try a broader keyword or remove the category filter."

    lines = [f"## Parts Search Results for `{keyword}`\n",
             f"Found {len(items)} result(s).\n"]
    for i, p in enumerate(items, 1):
        mfr_pn  = p.get("productModel") or p.get("mfrPartNumber", "—")
        lcsc_pn = p.get("productCode") or p.get("lcscPartNumber", "—")
        mfr     = p.get("brandNameEn") or p.get("manufacturer", "—")
        desc    = p.get("productIntroEn") or p.get("description", "—")
        stock   = p.get("stockNumber") or p.get("stock", 0)
        price   = (p.get("prices") or [{}])[0].get("usdPrice", "—") if p.get("prices") else "—"

        lines.append(f"### {i}. {mfr_pn}")
        lines.append(f"- **LCSC**: {lcsc_pn}  |  **Manufacturer**: {mfr}")
        lines.append(f"- **Description**: {desc}")
        lines.append(f"- **Stock**: {stock:,} pcs  |  **Unit price (1pc)**: ${price}")
        lines.append("")
    return "\n".join(lines)


def _fmt_detail_markdown(data: Dict, part_number: str) -> str:
    mfr_pn  = data.get("productModel") or part_number
    lcsc_pn = data.get("productCode", "—")
    mfr     = data.get("brandNameEn", "—")
    desc    = data.get("productIntroEn", "—")
    stock   = data.get("stockNumber", 0)
    package = data.get("encapStandard", "—")
    datasheet = data.get("pdfUrl") or data.get("datasheetUrl", "")

    specs = _extract_specs(data.get("paramVOList") or data.get("attributes", []))
    prices = _format_price_breaks(data.get("prices") or [])

    lines = [f"## {mfr_pn} — Full Detail\n",
             f"- **LCSC Part #**: {lcsc_pn}",
             f"- **Manufacturer**: {mfr}",
             f"- **Description**: {desc}",
             f"- **Package**: {package}",
             f"- **Stock**: {stock:,} pcs"]
    if datasheet:
        lines.append(f"- **Datasheet**: {datasheet}")

    if specs:
        lines += ["\n### Specifications"]
        for k, v in list(specs.items())[:20]:
            lines.append(f"- **{k}**: {v}")

    if prices:
        lines += ["\n### Price Breaks (USD)"]
        for pb in prices:
            lines.append(f"- {pb['quantity']}+ pcs: ${pb['unit_price_usd']}")

    return "\n".join(lines)


def _fmt_stock_markdown(data: Dict, part_number: str, qty_needed: Optional[int]) -> str:
    mfr_pn  = data.get("productModel") or part_number
    lcsc_pn = data.get("productCode", "—")
    stock   = data.get("stockNumber", 0)
    prices  = _format_price_breaks(data.get("prices") or [])

    lines = [f"## Stock & Pricing: {mfr_pn}\n",
             f"- **LCSC**: {lcsc_pn}",
             f"- **Current stock**: {stock:,} pcs"]

    if qty_needed is not None:
        if stock >= qty_needed:
            lines.append(f"- **Coverage**: ✅ Stock covers your requirement of {qty_needed:,} pcs")
        else:
            lines.append(
                f"- **Coverage**: ⚠️ Stock ({stock:,}) is below your requirement ({qty_needed:,} pcs)"
            )

    if prices:
        lines += ["\n### Price Breaks (USD)"]
        applicable = None
        for pb in prices:
            qty = pb.get("quantity") or 0
            lines.append(f"- {qty}+ pcs: ${pb['unit_price_usd']}")
            if qty_needed and qty <= qty_needed:
                applicable = pb
        if applicable and qty_needed:
            total = float(applicable.get("unit_price_usd") or 0) * qty_needed
            lines.append(
                f"\n**Estimated cost for {qty_needed:,} pcs**: ${total:.2f} USD"
            )

    if not prices:
        lines.append("\n*Pricing information unavailable — check LCSC directly.*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="parts_search",
    annotations={
        "title": "Search Electronic Components",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def parts_search(params: PartsSearchInput) -> str:
    """Search for electronic components on LCSC by keyword, category, or specification.

    Use this tool to find components when you know a description or partial
    part number. Returns a ranked list with stock and price information.

    Args:
        params (PartsSearchInput): Search parameters including:
            - keyword (str): Search term (part number, description, or spec)
            - category (Optional[str]): Category filter
            - in_stock_only (bool): Filter to in-stock parts only
            - limit (int): Max results (1–50, default 10)
            - response_format (str): 'markdown' or 'json'

    Returns:
        str: Formatted list of matching components with stock and price,
             or an error message if the search fails.
    """
    try:
        client = await _get_client()
        payload = {
            "keyword": params.keyword,
            "currentPage": 1,
            "pageSize": params.limit,
        }
        if params.category:
            payload["catalogNodePid"] = params.category

        resp = await client.post(LCSC_SEARCH_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

        # LCSC wraps results in data.result.productSearchResultVO.productList
        # or similar — handle multiple response shapes
        result = (
            data.get("result") or
            data.get("data") or
            {}
        )
        product_vo = (
            result.get("productSearchResultVO") or
            result.get("productVO") or
            result
        )
        items: List[Dict] = (
            product_vo.get("productList") or
            product_vo.get("products") or
            result.get("productList") or
            []
        )

        if params.in_stock_only:
            items = [p for p in items if (p.get("stockNumber") or p.get("stock") or 0) > 0]

        items = items[:params.limit]

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({"keyword": params.keyword, "count": len(items),
                               "items": items}, ensure_ascii=False, indent=2)
        return _fmt_search_markdown(items, params.keyword)

    except Exception as exc:
        return _handle_error(exc)


@mcp.tool(
    name="parts_get_detail",
    annotations={
        "title": "Get Component Full Specifications",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def parts_get_detail(params: PartsDetailInput) -> str:
    """Retrieve full specifications, datasheet link, and pricing for a specific part.

    Use this tool when you have an exact part number (LCSC C-number or
    manufacturer part number) and need complete electrical specifications,
    package information, and price breaks.

    Args:
        params (PartsDetailInput): Input parameters including:
            - part_number (str): LCSC or manufacturer part number
            - response_format (str): 'markdown' or 'json'

    Returns:
        str: Full component specifications including electrical params,
             package, stock, price breaks, and datasheet URL.
    """
    try:
        client = await _get_client()
        pn = _clean_part_number(params.part_number)

        resp = await client.get(
            LCSC_DETAIL_URL,
            params={"productCode": pn},
        )
        resp.raise_for_status()
        data = resp.json()

        product = (
            data.get("result") or
            data.get("data") or
            data.get("product") or
            {}
        )

        if not product:
            return json.dumps({
                "error": f"No data returned for part number '{pn}'. "
                         "Try searching with parts_search first to confirm the exact LCSC number."
            })

        if params.response_format == ResponseFormat.JSON:
            return json.dumps(product, ensure_ascii=False, indent=2)
        return _fmt_detail_markdown(product, pn)

    except Exception as exc:
        return _handle_error(exc)


@mcp.tool(
    name="parts_find_alternatives",
    annotations={
        "title": "Find Alternative / Substitute Components",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def parts_find_alternatives(params: PartsAlternativesInput) -> str:
    """Find functionally equivalent alternative parts for a given component.

    Use this tool when a part is out of stock, discontinued, or over budget,
    and you need pin-compatible or specification-equivalent substitutes.
    The tool fetches the original part's specs and searches for alternatives
    in the same category with similar key parameters.

    Args:
        params (PartsAlternativesInput): Input parameters including:
            - part_number (str): Original part to find alternatives for
            - max_price_premium_pct (float): Maximum price premium allowed (%)
            - limit (int): Max alternatives to return
            - response_format (str): 'markdown' or 'json'

    Returns:
        str: List of alternative parts with comparison notes,
             or guidance if no close alternatives are found.
    """
    try:
        client = await _get_client()
        pn = _clean_part_number(params.part_number)

        # Step 1: get original part detail
        detail_resp = await client.get(LCSC_DETAIL_URL, params={"productCode": pn})
        detail_resp.raise_for_status()
        original_data = (
            detail_resp.json().get("result") or
            detail_resp.json().get("data") or
            {}
        )

        original_desc = (
            original_data.get("productIntroEn") or
            original_data.get("description") or
            pn
        )
        original_prices = _format_price_breaks(
            original_data.get("prices") or []
        )
        original_unit = float(
            original_prices[0].get("unit_price_usd") or 0
        ) if original_prices else 0.0

        # Step 2: search using key terms from the original description
        # Use first 3–4 words as a search keyword
        search_kw = " ".join(original_desc.split()[:4]) if original_desc else pn
        search_resp = await client.post(LCSC_SEARCH_URL, json={
            "keyword": search_kw,
            "currentPage": 1,
            "pageSize": 30,
        })
        search_resp.raise_for_status()
        search_data = search_resp.json()

        result = search_data.get("result") or search_data.get("data") or {}
        product_vo = (
            result.get("productSearchResultVO") or
            result.get("productVO") or result
        )
        candidates: List[Dict] = (
            product_vo.get("productList") or
            product_vo.get("products") or
            result.get("productList") or []
        )

        # Filter: exclude original, in-stock only, within price premium
        alternatives = []
        for c in candidates:
            c_pn = (c.get("productCode") or "").upper()
            if c_pn == pn:
                continue
            if not (c.get("stockNumber") or c.get("stock") or 0):
                continue
            c_prices = _format_price_breaks(c.get("prices") or [])
            c_price  = float(c_prices[0].get("unit_price_usd") or 0) if c_prices else 0.0
            if original_unit > 0 and c_price > 0:
                premium = (c_price - original_unit) / original_unit * 100.0
                if premium > params.max_price_premium_pct:
                    continue
            alternatives.append(c)
            if len(alternatives) >= params.limit:
                break

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                "original_part": pn,
                "original_description": original_desc,
                "original_unit_price_usd": original_unit,
                "alternatives_found": len(alternatives),
                "alternatives": alternatives,
            }, ensure_ascii=False, indent=2)

        # Markdown output
        lines = [f"## Alternatives for `{pn}`\n",
                 f"**Original**: {original_desc}  |  Price: ${original_unit:.4f}/pc\n"]

        if not alternatives:
            lines.append(
                "No close alternatives found within the price and stock constraints. "
                "Try increasing `max_price_premium_pct` or search manually on LCSC."
            )
            return "\n".join(lines)

        for i, alt in enumerate(alternatives, 1):
            a_mfr_pn = alt.get("productModel", "—")
            a_lcsc   = alt.get("productCode", "—")
            a_mfr    = alt.get("brandNameEn", "—")
            a_desc   = alt.get("productIntroEn", "—")
            a_stock  = alt.get("stockNumber") or alt.get("stock", 0)
            a_prices = _format_price_breaks(alt.get("prices") or [])
            a_price  = a_prices[0].get("unit_price_usd", "—") if a_prices else "—"

            lines.append(f"### {i}. {a_mfr_pn} ({a_mfr})")
            lines.append(f"- **LCSC**: {a_lcsc}  |  **Stock**: {a_stock:,} pcs")
            lines.append(f"- **Description**: {a_desc}")
            lines.append(f"- **Unit price**: ${a_price}")
            lines.append(
                "*Note: Verify pin compatibility, voltage/current ratings, "
                "and package footprint before substitution.*\n"
            )

        return "\n".join(lines)

    except Exception as exc:
        return _handle_error(exc)


@mcp.tool(
    name="parts_check_stock",
    annotations={
        "title": "Check Component Stock and Pricing",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def parts_check_stock(params: PartsStockInput) -> str:
    """Check real-time stock availability and price breaks for a specific component.

    Use this tool to verify whether a part is available in the required
    quantity and to determine the applicable unit price for your order size.

    Args:
        params (PartsStockInput): Input parameters including:
            - part_number (str): LCSC or manufacturer part number
            - quantity_needed (Optional[int]): Your required quantity for price-break calculation
            - response_format (str): 'markdown' or 'json'

    Returns:
        str: Current stock level, price breaks (USD and CNY), and
             coverage assessment for the requested quantity.
    """
    try:
        client = await _get_client()
        pn = _clean_part_number(params.part_number)

        resp = await client.get(LCSC_DETAIL_URL, params={"productCode": pn})
        resp.raise_for_status()
        data = resp.json()

        product = (
            data.get("result") or
            data.get("data") or
            data.get("product") or
            {}
        )

        if not product:
            return json.dumps({
                "error": f"Part '{pn}' not found. Use parts_search to find the correct part number."
            })

        stock  = product.get("stockNumber", 0)
        prices = _format_price_breaks(product.get("prices") or [])

        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                "part_number": pn,
                "stock": stock,
                "prices": prices,
                "quantity_needed": params.quantity_needed,
                "stock_sufficient": (
                    stock >= params.quantity_needed if params.quantity_needed else None
                ),
            }, ensure_ascii=False, indent=2)

        return _fmt_stock_markdown(product, pn, params.quantity_needed)

    except Exception as exc:
        return _handle_error(exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()   # stdio transport by default
