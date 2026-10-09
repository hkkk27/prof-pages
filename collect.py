"""Bulk collection: every professor on the faculty lists -> collected/<slug>.json and a photo.

No AI and no pasting. For each professor it reads their university page, the Google Scholar
profile that page links to, and their ORCID record, and saves what it found. `profpages.py bulk`
then turns the saved files into pages.

It only makes plain, slow requests. A site that answers with a browser check or a CAPTCHA is
left alone and reported, never worked around.
"""
import csv
import glob
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from profpages import (DATA, DEGREE, EMPTY, ROOT, UA, Blocked, clean, fetch, from_csv_designation, orcid_works,
                       parse_ahduni, slugify)

OUT = ROOT / "collected"
LISTS = os.environ.get("FACULTY_CSVS", r"D:\fun projects\*faculty*.csv")
TRACKER = ROOT.parent / "Outreach tracker.xlsx"
RANK = re.compile(r"\b(assistant |associate )?professor\b", re.I)
NOT_CORE = re.compile(r"visiting|adjunct|emerit|of practice|honorary|ph\.?d|year -|former", re.I)
TITLE = re.compile(r"^(prof(essor)?|dr|mr|mrs|ms)\.?\s+", re.I)
ORCID = re.compile(r"(\d{4})[-\s](\d{4})[-\s](\d{4})[-\s](\d{3}[\dXx])")
PAUSE = {"scholar.google.com": 9.0}  # seconds between two requests to the same site; 1.2 for the rest
_last = {}
scholar_off = ""  # set to the reason once Google Scholar refuses; nothing more is asked of it in this run


def polite(url):
    host = urlparse(url).netloc
    wait = _last.get(host, 0) + PAUSE.get(host, 1.2) - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()


def get(url, **kw):
    polite(url)
    return requests.get(url, headers=UA, timeout=45, **kw)


def blank():
    return json.loads(json.dumps(EMPTY))


def page_text(soup):
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        t.decompose()
    return re.sub(r"\n\s*\n+", "\n", (soup.find("main") or soup.body or soup).get_text("\n"))


def find_ids(soup, rec):
    """Scholar and ORCID links as the page writes them: scholar.google.de, spaces in the iD, 'my-orcid?orcid='."""
    rec["links"]["scholar"] = rec["links"]["orcid"] = ""
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        m = re.search(r"scholar\.google\.[a-z.]+/citations\?.*?user=([\w-]{8,16})", h)
        if m and not rec["links"]["scholar"]:
            rec["links"]["scholar"] = f"https://scholar.google.com/citations?user={m.group(1)}&hl=en"
        m = ORCID.search(h) if "orcid" in h.lower() else None
        if m and not rec["links"]["orcid"]:
            rec["links"]["orcid"] = "https://orcid.org/" + "-".join(m.groups()).upper()
        if re.search(r"linkedin\.com/(in|pub)/", h) and not rec["links"]["linkedin"]:
            rec["links"]["linkedin"] = h


# ---------- who to collect ----------

def contacted():
    """Email addresses already written to, from the outreach tracker."""
    if not TRACKER.exists():
        return {}
    import openpyxl
    rows = list(openpyxl.load_workbook(TRACKER, read_only=True)["Tracker"].iter_rows(values_only=True))
    head = [str(h) for h in rows[0]]
    e, s, d = head.index("Email"), head.index("Status"), head.index("Date sent")
    return {str(r[e]).strip().lower(): str(r[s] or "") for r in rows[1:] if r[e] and r[d]}


def targets():
    seen, out, sent = set(), [], contacted()
    for path in sorted(glob.glob(LISTS)):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                cell = row.get("Designation_Profession") or ""
                first = cell.split(";")[0]
                email = (row.get("Email") or "").strip().lower()
                url = (row.get("Profile_URL") or "").replace("\n", "").replace(" ", "")
                own_site = any(p.strip().lower().startswith("http") and not re.search(r"scholar\.google|orcid\.org|linkedin\.com", p, re.I)
                               for p in cell.split(";"))
                if (not RANK.search(first) or NOT_CORE.search(first) or not email or ";" in email or "@" not in email
                        or not url or own_site or email in seen):
                    continue
                name = TITLE.sub("", clean(row["Name"]))
                # A shared mailbox (amsom@, info.ime@) or a garbled address is not this person's own.
                local = re.sub(r"[^a-z]", "", email.split("@")[0])
                initials = "".join(w[0] for w in re.findall(r"[a-z]+", name.lower()))
                if not any(w[:4] in local for w in re.findall(r"[a-z]{3,}", name.lower())) and local != initials:
                    continue
                seen.add(email)
                out.append({"name": name, "slug": slugify(name), "university": clean(row["University"]), "email": email,
                            "url": url, "cell": cell, "department": clean(row.get("Department_School")),
                            "contacted": sent.get(email, "")})
    return out


# ---------- one reader per university ----------

def read_ahduni(t):
    polite(t["url"])
    soup = fetch(t["url"])
    rec = parse_ahduni(soup, t["url"])
    find_ids(soup, rec)
    return rec, page_text(soup)


def read_vidyashilp(t):
    polite(t["url"])
    soup = fetch(t["url"])
    rec = blank()
    rec["university"] = "Vidyashilp University"
    h4 = soup.find("h4", class_="custom-p") or soup.find("h4")
    card = h4.find_parent("div") if h4 else None
    lines = [clean(x).rstrip(",") for x in card.get_text("\n").split("\n") if clean(x)] if card else []
    for i, line in enumerate(lines[1:]):
        low = line.lower()
        if i == 0:
            role, _, school = line.partition(", School of")
            rec["role"], rec["department"] = role, ("School of" + school if school else "")
        elif low.startswith(("school of", "department of")) and not rec["department"]:
            rec["department"] = line
        elif low.startswith("former "):
            title, _, org = line[7:].partition(", ")
            if not org:
                title, _, org = line[7:].partition(" at ")
            if org:
                rec["positions"].append({"title": title, "org": org, "start": "", "end": "", "note": "Former"})
        elif DEGREE.match(line.replace(".", "")):
            rec["education"].append({"degree": line, "org": "", "year": ""})
    words = re.findall(r"[a-z]{3,}", t["name"].lower())
    for img in soup.find_all("img"):  # the portrait is the picture whose caption carries the person's name
        alt = (img.get("alt") or "").lower()
        src = next((s for s in (img.get("src"), img.get("data-src")) if s and "/uploads/" in s), "")
        if src and words and (words[0] in alt or words[-1] in alt) and not re.search(r"mail|icon|logo|phone|linkedin", src + alt, re.I):
            rec["photo"] = urljoin(t["url"], src)
            break
    # The tabs: Biography, Professional Education, Teaching Courses, Research Interests, Selected Publications.
    parts, title = {}, "Biography"
    for box in soup.select(".custom-content"):
        for el in box.find_all(["h3", "h4", "h5", "h6", "p", "li"]):
            text = clean(el.get_text(" "))
            if not text or (el.name == "p" and el.find(["p", "li"])):
                continue
            if el.name.startswith("h"):
                title = text
            elif text not in parts.setdefault(title, []):
                parts[title].append(text)
    for title, items in parts.items():
        low = title.lower()
        if len(items) == 1 and ("interest" in low or "course" in low or "teaching" in low):
            items = [clean(x) for x in re.split(r"[,;]", items[0]) if clean(x)]  # one comma-separated line
        if "biograph" in low:
            rec["bio"] = [x for x in items if len(x) > 60]
        elif "education" in low:  # fuller than the short list under the name, so it replaces it
            rec["education"] = []
            for x in items:
                m = re.search(r"\s*[-–]\s*((?:19|20)\d{2})$", x)
                rec["education"].append({"degree": x[:m.start()] if m else x, "org": "", "year": m.group(1) if m else ""})
        elif "teaching" in low or "course" in low:
            rec["teaching"] = items[:12]
        elif "interest" in low and all(len(x) <= 90 for x in items):
            rec["interests"] = items[:8]
        else:
            rec["sections"].append({"title": title.rstrip(":"), "paragraphs": items[:14]})
    find_ids(soup, rec)
    return rec, page_text(soup)


_terms = {}


def ashoka_terms(tax):
    if tax not in _terms:
        r = get(f"https://www.ashoka.edu.in/wp-json/wp/v2/{tax}", params={"per_page": 100, "_fields": "id,name"})
        _terms[tax] = {x["id"]: x["name"] for x in r.json()} if r.status_code == 200 else {}
    return _terms[tax]


def read_ashoka(t):
    """Ashoka's pages and pictures sit behind a browser check. Its public WordPress API still gives the department.

    So an Ashoka record is thin: name, title, department, degree from the list, and papers from ORCID.
    The biography and photo have to come from a paste in the page maker.
    """
    api = "https://www.ashoka.edu.in/wp-json/wp/v2"
    r = get(f"{api}/profile", params={"slug": t["url"].rstrip("/").split("/")[-1], "_fields": "id,title,department_category"})
    if r.status_code != 200 or not r.json():
        raise Blocked(f"Ashoka's API gave nothing for {t['name']} (status {r.status_code}).")
    post = r.json()[0]
    rec = blank()
    rec["university"] = "Ashoka University"
    depts = [ashoka_terms("department_category").get(i, "") for i in post.get("department_category") or []]
    rec["department"] = ", ".join(d for d in depts if d and d != "YIF")
    return rec, ""


READERS = {"ahduni.edu.in": read_ahduni, "vidyashilp.edu.in": read_vidyashilp, "ashoka.edu.in": read_ashoka}


# ---------- research records ----------

def scholar(link):
    """The professor's own Google Scholar profile, first page only (robots.txt allows /citations?user=)."""
    global scholar_off
    if scholar_off:
        return None
    r = get(link)
    low = r.text[:6000].lower()
    if r.status_code != 200 or "unusual traffic" in low or "captcha" in low or "gsc_prf_in" not in r.text:
        scholar_off = f"Google Scholar refused (status {r.status_code}); stopped asking it for this run."
        print("  ! " + scholar_off)
        return None
    s = BeautifulSoup(r.text, "html.parser")
    nums = [clean(td.get_text()) for td in s.select("td.gsc_rsb_std")]
    pubs = []
    for row in s.select("tr.gsc_a_tr"):
        grey = [clean(g.get_text()) for g in row.select(".gs_gray")]
        year = clean(getattr(row.select_one(".gsc_a_y"), "text", ""))
        venue = re.sub(r",?\s*(19|20)\d{2}$", "", grey[1]) if len(grey) > 1 else ""
        pubs.append({"title": clean(getattr(row.select_one(".gsc_a_at"), "text", "")), "authors": grey[0] if grey else "",
                     "venue": venue, "year": year, "url": "", "cited": clean(getattr(row.select_one(".gsc_a_c"), "text", "")).rstrip("*")})
    return {"name": clean(getattr(s.select_one("#gsc_prf_in"), "text", "")),
            "interests": [clean(a.get_text()) for a in s.select("#gsc_prf_int a")],
            "citations": nums[0] if nums else "", "h_index": nums[2] if len(nums) > 2 else "",
            "i10_index": nums[4] if len(nums) > 4 else "", "publications": [p for p in pubs if p["title"]]}


def same_person(a, b):
    """Scholar or ORCID must be about the same name before anything from it is used."""
    x, y = set(re.findall(r"[a-z]{3,}", a.lower())), set(re.findall(r"[a-z]{3,}", b.lower()))
    glued = re.sub(r"[^a-z]", "", a.lower())  # Scholar names are sometimes typed without a space: "ParagPatel PhD"
    return bool(x and y) and (x <= y or y <= x or all(w in glued for w in y))


def orcid_search(name, university):
    """An ORCID iD only when exactly one record has this name and this university."""
    parts = name.split()
    if len(parts) < 2:
        return ""
    q = f'given-names:"{" ".join(parts[:-1])}" AND family-name:"{parts[-1]}" AND affiliation-org-name:"{university}"'
    try:
        polite("https://pub.orcid.org/")
        r = requests.get("https://pub.orcid.org/v3.0/expanded-search/", params={"q": q, "rows": 5},
                         headers={"Accept": "application/json"}, timeout=40)
        found = r.json().get("expanded-result") or []
    except Exception:
        return ""
    return f"https://orcid.org/{found[0]['orcid-id']}" if len(found) == 1 else ""


def add_scholar(rec, sch):
    rec["metrics"] = {"citations": sch["citations"].replace(",", ""), "h_index": sch["h_index"]}
    if not rec["interests"]:
        rec["interests"] = sch["interests"][:8]
    if not rec["publications"]:
        rec["publications"] = sorted(sch["publications"], key=lambda p: p["year"], reverse=True)
    lines = [f"{p['title']}. {p['authors']}. {p['venue']} {p['year']}" for p in sch["publications"]]
    return (f"\nGoogle Scholar\nCitations {sch['citations']}\nh-index {sch['h_index']}\n"
            + ", ".join(sch["interests"]) + "\n" + "\n".join(lines))


def tidy_sections(rec):
    """Move the page's own 'Teaching' and 'Awards' blocks into the fields the template draws properly."""
    keep = []
    for s in rec["sections"]:
        low, paras = s["title"].lower().strip(), s["paragraphs"]
        short = all(len(x) <= 240 for x in paras)
        if re.fullmatch(r"teachings?|courses taught", low) and short and not rec["teaching"]:
            rec["teaching"] = paras[:12]
        elif re.match(r"(awards?|honou?rs?|recognition)\b", low) and short and not rec["awards"]:
            for x in paras[:12]:
                year = re.search(r"\b(?:19|20)\d{2}\b", x)
                rec["awards"].append({"title": x, "by": "", "year": year.group(0) if year else ""})
        elif re.match(r"publications?$", low) and len(rec["publications"]) >= 5:
            continue  # the same papers are already listed from Scholar or ORCID
        else:
            s["paragraphs"] = paras[:18]  # a demo page shows the start of a long list, not all forty entries
            keep.append(s)
    rec["sections"] = keep


def save_photo(src, slug):
    try:
        r = get(src)
        kind = r.headers.get("Content-Type", "")
        if r.status_code != 200 or not kind.startswith("image/") or len(r.content) < 4000:
            return ""
        ext = {"image/png": ".png", "image/webp": ".webp"}.get(kind.split(";")[0], ".jpg")
        (OUT / f"{slug}{ext}").write_bytes(r.content)
        return str(OUT / f"{slug}{ext}")
    except Exception:
        return ""


# ---------- the run ----------

def collect_one(t, old=None):
    """`old` is the file from an earlier run: its Scholar and ORCID results are kept, only the page is read again."""
    reader = next((fn for host, fn in READERS.items() if host in t["url"]), None)
    if not reader:
        raise Blocked(f"no reader yet for {urlparse(t['url']).netloc}")
    rec, text = reader(t)
    rec["name"] = t["name"]
    rec["university"] = rec["university"] or t["university"]
    rec["department"] = rec["department"] or t["department"]
    rec["contact"]["email"] = t["email"]
    rec["links"]["profile"] = t["url"]
    rec["sources"] = [t["url"]]
    if not rec["role"]:
        from_csv_designation(rec, t["cell"])
    got = {"page": True, "photo": False, "scholar": False, "orcid": False}
    if old and (old["got"]["scholar"] or old["got"]["orcid"]):
        o = old["rec"]
        rec["metrics"], rec["publications"] = o["metrics"], o["publications"]
        rec["interests"] = rec["interests"] or o["interests"]
        rec["links"]["scholar"], rec["links"]["orcid"] = o["links"]["scholar"], o["links"]["orcid"]
        rec["sources"] = o["sources"]
        cut = old["text"].find("\nGoogle Scholar\nCitations")
        text += old["text"][cut:] if cut >= 0 else "\n" + "\n".join(f"{p['title']}. {p['venue']} {p['year']}" for p in rec["publications"])
        got["scholar"], got["orcid"] = old["got"]["scholar"], old["got"]["orcid"]
    elif rec["links"]["scholar"]:
        sch = scholar(rec["links"]["scholar"])
        if sch and same_person(sch["name"], t["name"]):
            text += add_scholar(rec, sch)
            rec["sources"].append(rec["links"]["scholar"])
            got["scholar"] = True
        elif sch:
            print(f"  ! Scholar link on the page is for '{sch['name']}', not used")
            rec["links"]["scholar"] = ""
    if not rec["links"]["orcid"] and not old:
        rec["links"]["orcid"] = orcid_search(t["name"], rec["university"])
    if rec["links"]["orcid"] and not rec["publications"] and not old:
        rec["publications"] = orcid_works(rec["links"]["orcid"])[:25]
        got["orcid"] = bool(rec["publications"])
        text += "\n" + "\n".join(f"{p['title']}. {p['venue']} {p['year']}" for p in rec["publications"])
    tidy_sections(rec)
    photo = save_photo(rec["photo"], t["slug"]) if rec["photo"] and not re.search(r"default|placeholder|avatar|dummy", rec["photo"], re.I) else ""
    got["photo"] = bool(photo)
    return {"target": t, "rec": rec, "text": text, "photo_file": photo, "got": got}


def cmd_collect(a):
    OUT.mkdir(exist_ok=True)
    todo = [t for t in targets() if not a.university or a.university.lower() in t["university"].lower()]
    if a.limit:
        todo = todo[:a.limit]
    print(f"  {len(todo)} professor(s) on the lists")
    for n, t in enumerate(todo, 1):
        path = OUT / f"{t['slug']}.json"
        if path.exists() and not a.redo:
            old = json.loads(path.read_text(encoding="utf-8"))
            # A Scholar profile that was refused last time is asked for again, and nothing else.
            if old["rec"]["links"]["scholar"] and not old["got"]["scholar"] and not scholar_off:
                sch = scholar(old["rec"]["links"]["scholar"])
                if sch and same_person(sch["name"], t["name"]):
                    old["text"] += add_scholar(old["rec"], sch)
                    old["got"]["scholar"] = True
                    path.write_text(json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8")
                    print(f"  [{n}/{len(todo)}] {t['name']}: Google Scholar added")
            continue
        try:
            c = collect_one(t, json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)
        except Exception as e:
            print(f"  [{n}/{len(todo)}] {t['name']}: ! {type(e).__name__}: {e}")
            continue
        path.write_text(json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
        r, g = c["rec"], c["got"]
        print(f"  [{n}/{len(todo)}] {t['name']}: {len(r['bio'])} bio, {len(r['sections'])} sections, "
              f"{len(r['publications'])} publications" + "".join(f", {k}" for k in ("photo", "scholar", "orcid") if g[k]))
    report()


def report():
    rows = []
    for t in targets():
        path = OUT / f"{t['slug']}.json"
        c = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        r, g = (c["rec"], c["got"]) if c else (blank(), {})
        rows.append([t["name"], t["university"], t["email"], "yes" if c else "", "yes" if g.get("photo") else "",
                     len(r["bio"]), len(r["sections"]), len(r["publications"]), "yes" if g.get("scholar") else ("linked" if r["links"]["scholar"] else ""),
                     "yes" if r["links"]["orcid"] else "", "yes" if (DATA / f"{t['slug']}.json").exists() else "", t["contacted"]])
    with open(OUT / "_report.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Name", "University", "Email", "Collected", "Photo", "Bio paragraphs", "Sections", "Publications",
                    "Google Scholar", "ORCID", "Page built", "Already emailed"])
        w.writerows(rows)
    done = [x for x in rows if x[3]]
    print(f"\n  collected {len(done)} of {len(rows)}: {sum(1 for x in done if x[4])} with photo, "
          f"{sum(1 for x in done if x[5])} with a biography, {sum(1 for x in done if x[8] == 'yes')} with Google Scholar, "
          f"{sum(1 for x in done if x[7])} with publications")
    print("  full table: collected/_report.csv")
    if scholar_off:
        print("  " + scholar_off + " Run collect again later to fill those in.")
