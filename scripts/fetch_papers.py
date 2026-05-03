#!/usr/bin/env python3
"""
Fetch latest tinnitus / brain noise research papers from multiple sources:
- PubMed E-utilities
- Europe PMC
- Crossref
- Semantic Scholar
- OpenAlex

Targets tinnitus, hyperacusis, misophonia, somatosensory tinnitus, and related comorbidities.
"""

import json
import sys
import argparse
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote_plus, urlencode

PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CROSSREF_SEARCH = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_SEARCH = "https://api.openalex.org/works"

PUBMED_RATE_LIMIT = 0.4

SEARCH_QUERIES = [
    '(("Tinnitus"[Mesh] OR tinnitus[tiab] OR "subjective tinnitus"[tiab] OR "pulsatile tinnitus"[tiab] OR "somatosensory tinnitus"[tiab] OR "somatic tinnitus"[tiab] OR "auditory phantom"[tiab] OR "phantom auditory perception"[tiab] OR "head noise"[tiab] OR "brain noise"[tiab] OR hyperacusis[tiab] OR misophonia[tiab] OR "sound intolerance"[tiab]))',
]

TOPIC_QUERIES = [
    '(("Tinnitus"[Mesh] OR tinnitus[tiab]) AND (CBT[tiab] OR mindfulness[tiab] OR "sound therapy"[tiab] OR "hearing aid"[tiab] OR "tinnitus retraining therapy"[tiab] OR rTMS[tiab] OR tDCS[tiab] OR neuromodulation[tiab] OR "manual therapy"[tiab]))',
    '(("Tinnitus"[Mesh] OR tinnitus[tiab]) AND (distress[tiab] OR anxiety[tiab] OR depression[tiab] OR insomnia[tiab] OR "quality of life"[tiab] OR catastrophizing[tiab] OR coping[tiab]))',
    '(("Tinnitus"[Mesh] OR tinnitus[tiab] OR "somatosensory tinnitus"[tiab]) AND (TMD[tiab] OR TMJ[tiab] OR bruxism[tiab] OR "cervical spine"[tiab] OR "neck pain"[tiab] OR "manual therapy"[tiab] OR "physical therapy"[tiab]))',
    '(("Tinnitus"[Mesh] OR tinnitus[tiab]) AND (diet[tiab] OR nutrition[tiab] OR caffeine[tiab] OR alcohol[tiab] OR magnesium[tiab] OR zinc[tiab] OR "vitamin B12"[tiab] OR "vitamin D"[tiab] OR omega-3[tiab] OR "metabolic syndrome"[tiab]))',
    '(("Tinnitus"[Mesh] OR tinnitus[tiab]) AND ("Exercise"[Mesh] OR "physical activity"[tiab] OR exercise[tiab] OR aerobic[tiab] OR "resistance training"[tiab] OR yoga[tiab] OR "tai chi"[tiab] OR rehabilitation[tiab]))',
    '(("Tinnitus"[Mesh] OR tinnitus[tiab]) AND ("Transcranial Magnetic Stimulation"[Mesh] OR rTMS[tiab] OR "repetitive transcranial magnetic stimulation"[tiab] OR tDCS[tiab] OR "bimodal stimulation"[tiab] OR "vagus nerve stimulation"[tiab] OR neuromodulation[tiab]))',
    '(("Tinnitus"[Mesh] OR tinnitus[tiab]) AND (epidemiology[tiab] OR prevalence[tiab] OR "occupational noise"[tiab] OR veterans[tiab] OR military[tiab] OR disability[tiab] OR "lived experience"[tiab] OR qualitative[tiab]))',
]

EUROPEPMC_QUERIES = [
    '(TITLE:"tinnitus" OR ABSTRACT:"tinnitus" OR TITLE:"hyperacusis" OR ABSTRACT:"hyperacusis" OR TITLE:"somatosensory tinnitus" OR ABSTRACT:"somatosensory tinnitus")',
    '(TITLE:"tinnitus" OR ABSTRACT:"tinnitus") AND (CBT OR "cognitive behavioral" OR mindfulness OR "sound therapy")',
    '(TITLE:"tinnitus" OR ABSTRACT:"tinnitus") AND (anxiety OR depression OR insomnia OR "quality of life")',
    '(TITLE:"tinnitus" OR ABSTRACT:"tinnitus") AND (TMD OR TMJ OR bruxism OR "cervical spine" OR "neck pain")',
    '(TITLE:"tinnitus" OR ABSTRACT:"tinnitus") AND (diet OR nutrition OR caffeine OR exercise OR "physical activity")',
    '(TITLE:"tinnitus" OR ABSTRACT:"tinnitus") AND (rTMS OR tDCS OR neuromodulation OR "transcranial magnetic")',
]

CROSSREF_QUERIES = [
    "tinnitus systematic review",
    "tinnitus cognitive behavioral therapy",
    "tinnitus hyperacusis misophonia",
    "tinnitus neuromodulation rTMS tDCS",
    "tinnitus somatosensory temporomandibular cervical",
    "tinnitus diet nutrition exercise",
]

SEMANTIC_QUERIES = [
    "tinnitus treatment intervention",
    "tinnitus neuroplasticity auditory cortex",
    "tinnitus anxiety depression insomnia",
    "tinnitus hearing aid sound therapy",
]

OPENALEX_QUERIES = [
    "tinnitus",
    "tinnitus distress quality of life",
    "tinnitus CBT mindfulness",
    "tinnitus neuromodulation rTMS",
]

HEADERS = {"User-Agent": "TinnitusBrainBot/1.0 (research aggregator)"}
OPENALEX_MAILTO = "tinnitusbrainbot@research.example.com"


def _http_get_json(url: str, headers: dict = None, timeout: int = 30, retries: int = 2) -> dict | None:
    req_headers = {**HEADERS, **(headers or {})}
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=req_headers)
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"[WARN] Rate limited (429), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[ERROR] HTTP {e.code} for {url[:100]}: {str(e)[:200]}", file=sys.stderr)
            return None
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(f"[ERROR] Request failed: {str(e)[:200]}", file=sys.stderr)
            return None
    return None


def _http_get_xml(url: str, headers: dict = None, timeout: int = 60, retries: int = 2) -> str | None:
    req_headers = {**HEADERS, **(headers or {})}
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=req_headers)
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode()
        except HTTPError as e:
            if e.code == 429:
                wait = 5 * (attempt + 1)
                print(f"[WARN] Rate limited (429), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 404:
                print(f"[WARN] 404 for {url[:120]}", file=sys.stderr)
                return None
            print(f"[ERROR] HTTP {e.code} for {url[:100]}: {str(e)[:200]}", file=sys.stderr)
            return None
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(f"[ERROR] Request failed: {str(e)[:200]}", file=sys.stderr)
            return None
    return None


def dedup_papers(papers: list[dict]) -> list[dict]:
    seen_titles = set()
    seen_dois = set()
    result = []
    for p in papers:
        doi = p.get("doi", "").lower().strip()
        title_key = p.get("title", "").lower().strip()[:80]
        if doi and doi in seen_dois:
            continue
        if title_key and title_key in seen_titles:
            continue
        if doi:
            seen_dois.add(doi)
        if title_key:
            seen_titles.add(title_key)
        result.append(p)
    return result


def build_pubmed_master_query(days: int) -> str:
    lookback = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y/%m/%d")
    date_part = f'"{lookback}"[Date - Publication] : "3000"[Date - Publication]'
    base = SEARCH_QUERIES[0]
    return f"{base} AND {date_part}"


def build_pubmed_topic_query(topic_query: str, days: int) -> str:
    lookback = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y/%m/%d")
    date_part = f'"{lookback}"[Date - Publication] : "3000"[Date - Publication]'
    return f"{topic_query} AND {date_part}"


def search_pubmed(query: str, retmax: int = 50) -> list[str]:
    time.sleep(PUBMED_RATE_LIMIT)
    params = (
        f"?db=pubmed&term={quote_plus(query)}&retmax={retmax}&sort=date&retmode=json"
    )
    url = PUBMED_SEARCH + params
    data = _http_get_json(url)
    if data is None:
        return []
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_pubmed_details(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    all_papers = []
    batch_size = 50
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        ids = ",".join(batch)
        params = f"?db=pubmed&id={ids}&retmode=xml"
        url = PUBMED_FETCH + params
        time.sleep(PUBMED_RATE_LIMIT)
        xml_data = _http_get_xml(url)
        if xml_data is None:
            print(f"[WARN] PubMed efetch returned None for batch starting at {i}", file=sys.stderr)
            continue

        papers = []
        try:
            root = ET.fromstring(xml_data)
            for article in root.findall(".//PubmedArticle"):
                medline = article.find(".//MedlineCitation")
                art = medline.find(".//Article") if medline else None
                if art is None:
                    continue

                title_el = art.find(".//ArticleTitle")
                title = ""
                if title_el is not None:
                    title = "".join(title_el.itertext()).strip()

                abstract_parts = []
                for abs_el in art.findall(".//Abstract/AbstractText"):
                    label = abs_el.get("Label", "")
                    text = "".join(abs_el.itertext()).strip()
                    if label and text:
                        abstract_parts.append(f"{label}: {text}")
                    elif text:
                        abstract_parts.append(text)
                abstract = " ".join(abstract_parts)[:2000]

                journal_el = art.find(".//Journal/Title")
                journal = ""
                if journal_el is not None and journal_el.text:
                    journal = journal_el.text.strip()

                pub_date = art.find(".//PubDate")
                date_str = ""
                if pub_date is not None:
                    year = pub_date.findtext("Year", "")
                    month = pub_date.findtext("Month", "")
                    day = pub_date.findtext("Day", "")
                    parts = [p for p in [year, month, day] if p]
                    date_str = " ".join(parts)

                pmid_el = medline.find(".//PMID")
                pmid = pmid_el.text if pmid_el is not None else ""
                link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

                doi = ""
                for eid in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
                    if eid.get("IdType") == "doi":
                        doi = (eid.text or "").strip()
                        break

                keywords = []
                for kw in medline.findall(".//KeywordList/Keyword"):
                    if kw.text:
                        keywords.append(kw.text.strip())

                papers.append({
                    "pmid": pmid,
                    "doi": doi,
                    "title": title,
                    "journal": journal,
                    "date": date_str,
                    "abstract": abstract,
                    "url": link,
                    "keywords": keywords,
                    "source": "PubMed",
                })
        except ET.ParseError as e:
            print(f"[ERROR] XML parse failed: {e}", file=sys.stderr)

        all_papers.extend(papers)

    return all_papers


def search_europepmc(query: str, days: int, page_size: int = 50) -> list[dict]:
    lookback = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    full_query = f"{query} AND FIRST_PDATE:[{lookback} TO 3000-12-31]"
    params = urlencode({
        "query": full_query,
        "format": "json",
        "pageSize": page_size,
        "sort": "DATE desc",
    })
    url = f"{EUROPEPMC_SEARCH}?{params}"
    data = _http_get_json(url, timeout=30)
    if data is None:
        return []

    papers = []
    for r in data.get("resultList", {}).get("result", []):
        title = r.get("title", "").strip()
        if not title:
            continue
        pmid = r.get("pmid", "")
        doi = r.get("doi", "")
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else "")
        abstract = r.get("abstractText", "")[:2000] if r.get("abstractText") else ""
        journal = r.get("journalTitle", "")
        date_str = r.get("firstPublicationDate", "")

        papers.append({
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "journal": journal,
            "date": date_str,
            "abstract": abstract,
            "url": link,
            "keywords": [],
            "source": "EuropePMC",
        })
    return papers


def search_crossref(query: str, days: int, rows: int = 30) -> list[dict]:
    lookback = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    params = urlencode({
        "query.bibliographic": query,
        "filter": f"from-pub-date:{lookback}",
        "rows": rows,
        "sort": "published",
        "order": "desc",
    })
    url = f"{CROSSREF_SEARCH}?{params}"
    data = _http_get_json(url, timeout=30)
    if data is None:
        return []

    papers = []
    for item in data.get("message", {}).get("items", []):
        titles = item.get("title", [])
        title = titles[0].strip() if titles else ""
        if not title:
            continue
        doi = item.get("DOI", "")
        link = f"https://doi.org/{doi}" if doi else ""
        journal_list = item.get("container-title", [])
        journal = journal_list[0] if journal_list else ""
        date_parts = item.get("published-print", item.get("published-online", {})).get("date-parts", [[]])
        dp = date_parts[0] if date_parts else []
        date_str = "-".join(str(p) for p in dp) if dp else ""
        abstract = item.get("abstract", "")[:2000] if item.get("abstract") else ""

        papers.append({
            "pmid": "",
            "doi": doi,
            "title": title,
            "journal": journal,
            "date": date_str,
            "abstract": abstract,
            "url": link,
            "keywords": [],
            "source": "Crossref",
        })
    return papers


def search_semantic_scholar(query: str, days: int, limit: int = 25) -> list[dict]:
    lookback_year = (datetime.now(timezone.utc) - timedelta(days=days)).year
    params = urlencode({
        "query": query,
        "limit": limit,
        "fields": "title,year,authors,venue,citationCount,externalIds,url,abstract",
        "year": f"{lookback_year}-",
    })
    url = f"{SEMANTIC_SCHOLAR_SEARCH}?{params}"
    data = _http_get_json(url, timeout=30)
    if data is None:
        return []

    papers = []
    for item in data.get("data", []):
        title = item.get("title", "").strip()
        if not title:
            continue
        ext_ids = item.get("externalIds", {})
        doi = ext_ids.get("DOI", "")
        pmid = str(ext_ids.get("PubMed", ""))
        s2_url = item.get("url", "")
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else s2_url)
        abstract = item.get("abstract", "")[:2000] if item.get("abstract") else ""
        journal = item.get("venue", "")
        year = item.get("year")
        date_str = str(year) if year else ""

        papers.append({
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "journal": journal,
            "date": date_str,
            "abstract": abstract,
            "url": link,
            "keywords": [],
            "source": "SemanticScholar",
        })
    return papers


def search_openalex(query: str, days: int, per_page: int = 30) -> list[dict]:
    lookback = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    params = urlencode({
        "search": query,
        "filter": f"from_publication_date:{lookback}",
        "sort": "publication_date:desc",
        "per_page": per_page,
        "mailto": OPENALEX_MAILTO,
    })
    url = f"{OPENALEX_SEARCH}?{params}"
    data = _http_get_json(url, timeout=30)
    if data is None:
        return []

    papers = []
    for item in data.get("results", []):
        title = item.get("title", "").strip()
        if not title:
            continue
        doi_url = item.get("doi", "")
        doi = doi_url.replace("https://doi.org/", "") if doi_url else ""
        pmid = ""
        ids = item.get("ids", {})
        pmid_url = ids.get("pmid", "")
        if pmid_url:
            pmid = pmid_url.replace("https://pubmed.ncbi.nlm.nih.gov/", "")
        link = pmid_url or doi_url or item.get("id", "")
        abstract_inv = item.get("abstract_inverted_index")
        abstract = ""
        if abstract_inv:
            word_positions = []
            for word, positions in abstract_inv.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort()
            abstract = " ".join(w for _, w in word_positions)[:2000]

        journal = ""
        source = item.get("primary_location", {}) or {}
        src = source.get("source", {}) or {}
        journal = src.get("display_name", "")
        date_str = item.get("publication_date", "")

        papers.append({
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "journal": journal,
            "date": date_str,
            "abstract": abstract,
            "url": link,
            "keywords": [],
            "source": "OpenAlex",
        })
    return papers


def main():
    parser = argparse.ArgumentParser(description="Fetch tinnitus papers from multiple sources")
    parser.add_argument("--days", type=int, default=7, help="Lookback days")
    parser.add_argument("--max-papers", type=int, default=100, help="Max papers to fetch")
    parser.add_argument("--output", default="-",
                        help="Output file (- for stdout)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    all_papers = []

    print(f"[INFO] === Source 1: PubMed ===", file=sys.stderr)
    all_pmids = set()
    master_query = build_pubmed_master_query(days=args.days)
    print(f"[INFO] PubMed master query for last {args.days} days...", file=sys.stderr)
    master_ids = search_pubmed(master_query, retmax=args.max_papers)
    all_pmids.update(master_ids)
    print(f"[INFO] PubMed master: {len(master_ids)} PMIDs", file=sys.stderr)

    per_topic = max(5, 20)
    for i, tq in enumerate(TOPIC_QUERIES):
        topic_q = build_pubmed_topic_query(tq, days=args.days)
        ids = search_pubmed(topic_q, retmax=per_topic)
        new_ids = [pid for pid in ids if pid not in all_pmids]
        all_pmids.update(new_ids)
        print(f"[INFO] PubMed topic {i + 1}/{len(TOPIC_QUERIES)}: +{len(new_ids)} new", file=sys.stderr)

    print(f"[INFO] PubMed total unique PMIDs: {len(all_pmids)}", file=sys.stderr)
    if all_pmids:
        pmid_list = list(all_pmids)[:args.max_papers]
        pubmed_papers = fetch_pubmed_details(pmid_list)
        print(f"[INFO] PubMed fetched details: {len(pubmed_papers)} papers", file=sys.stderr)
        all_papers.extend(pubmed_papers)

    print(f"[INFO] === Source 2: Europe PMC ===", file=sys.stderr)
    for i, eq in enumerate(EUROPEPMC_QUERIES):
        ep_papers = search_europepmc(eq, days=args.days, page_size=25)
        print(f"[INFO] EuropePMC query {i + 1}/{len(EUROPEPMC_QUERIES)}: {len(ep_papers)} papers", file=sys.stderr)
        all_papers.extend(ep_papers)
        time.sleep(0.3)

    print(f"[INFO] === Source 3: Crossref ===", file=sys.stderr)
    for i, cq in enumerate(CROSSREF_QUERIES):
        cr_papers = search_crossref(cq, days=args.days, rows=20)
        print(f"[INFO] Crossref query {i + 1}/{len(CROSSREF_QUERIES)}: {len(cr_papers)} papers", file=sys.stderr)
        all_papers.extend(cr_papers)
        time.sleep(0.3)

    print(f"[INFO] === Source 4: Semantic Scholar ===", file=sys.stderr)
    for i, sq in enumerate(SEMANTIC_QUERIES):
        ss_papers = search_semantic_scholar(sq, days=args.days, limit=20)
        print(f"[INFO] SemanticScholar query {i + 1}/{len(SEMANTIC_QUERIES)}: {len(ss_papers)} papers", file=sys.stderr)
        all_papers.extend(ss_papers)
        time.sleep(0.5)

    print(f"[INFO] === Source 5: OpenAlex ===", file=sys.stderr)
    for i, oq in enumerate(OPENALEX_QUERIES):
        oa_papers = search_openalex(oq, days=args.days, per_page=25)
        print(f"[INFO] OpenAlex query {i + 1}/{len(OPENALEX_QUERIES)}: {len(oa_papers)} papers", file=sys.stderr)
        all_papers.extend(oa_papers)
        time.sleep(0.3)

    print(f"[INFO] Total raw papers before dedup: {len(all_papers)}", file=sys.stderr)
    all_papers = dedup_papers(all_papers)
    print(f"[INFO] After dedup: {len(all_papers)} papers", file=sys.stderr)

    all_papers = all_papers[:args.max_papers]
    print(f"[INFO] Final (capped at {args.max_papers}): {len(all_papers)} papers", file=sys.stderr)

    output_data = {
        "date": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
        "count": len(all_papers),
        "papers": all_papers,
    }

    out_str = json.dumps(output_data, ensure_ascii=False, indent=2)

    if args.output == "-":
        print(out_str)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_str)
        print(f"[INFO] Saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
