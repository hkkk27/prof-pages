"""Faculty demo pages.

One professor in, one static page out:

    python profpages.py add --email someone@ahduni.edu.in   # look up the profile URL in your CSV
    python profpages.py add https://.../faculty/name/        # or give the profile page directly
    python profpages.py add --text pasted.txt --name "A B"   # for sites that block automated reading
    python profpages.py build                                # rebuild every page from data/*.json
    python profpages.py deploy                               # publish site/ to Vercel
    python profpages.py list                                 # show every page and its link

Each professor is one file in data/. Edit that file by hand to correct anything, then run build.
"""
import argparse
import csv
import html
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from template import render

ROOT = Path(__file__).resolve().parent
DATA, RAW, SITE, ASSETS, PHOTOS = ROOT / "data", ROOT / "raw", ROOT / "site", ROOT / "assets", ROOT / "photos"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en"}
MAKER_NAME, MAKER_URL = "Harshit Singh", "https://harshit-singh-two.vercel.app"
CUSTOM = ROOT / "custom"
EMPTY = {"slug": "", "name": "", "role": "", "department": "", "university": "", "location": "", "tagline": "", "photo": "",
         "bio": [], "interests": [], "positions": [], "education": [], "publications": [], "teaching": [],
         "awards": [], "sections": [], "metrics": {}, "contact": {"email": "", "phone": "", "office": ""},
         "links": {"profile": "", "scholar": "", "orcid": "", "linkedin": "", "website": ""}, "sources": []}


class Blocked(Exception):
    """The site refused an automated request."""


# ---------- small helpers ----------

def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def esc(s):
    return html.escape(str(s or ""), quote=True)


def tokens(s):
    return re.findall(r"[a-z0-9]{4,}", (s or "").lower())


def grounded(text, source_tokens, ratio=0.75):
    """True when most of the words in `text` also occur in the source. Guards against invented facts."""
    t = tokens(text)
    if not t:
        return True
    return sum(1 for w in t if w in source_tokens) / len(t) >= ratio


# ---------- reading a profile page ----------

def fetch(url):
    r = requests.get(url, headers=UA, timeout=45)
    head = r.text[:3000].lower()
    if r.status_code != 200 or "just a moment" in head or "checking your browser" in head:
        raise Blocked(f"{urlparse(url).netloc} refused an automated request (status {r.status_code}).")
    return BeautifulSoup(r.text, "html.parser")


def page_links(soup, base):
    links = dict(EMPTY["links"])
    contact = dict(EMPTY["contact"])
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        low = h.lower()
        if low.startswith("mailto:") and not contact["email"]:
            contact["email"] = h[7:].split("?")[0]
        elif low.startswith("tel:") and not contact["phone"]:
            contact["phone"] = h[4:]
        elif "scholar.google" in low and "user=" in low and not links["scholar"]:
            links["scholar"] = re.sub(r"&citsig=[^&]+", "", h)
        elif "orcid.org/" in low and re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dxX]", h) and not links["orcid"]:
            links["orcid"] = h
        elif re.search(r"linkedin\.com/(in|pub)/", low) and not links["linkedin"]:
            links["linkedin"] = h
    links["profile"] = base
    return links, contact


def parse_ahduni(soup, url):
    rec = json.loads(json.dumps(EMPTY))
    rec["university"] = "Ahmedabad University"
    bio = soup.select_one(".person-bio") or soup
    rec["name"] = clean(getattr(bio.select_one(".person-name"), "text", ""))
    rec["role"] = clean(getattr(bio.select_one(".person-desg"), "text", ""))
    rec["department"] = clean(getattr(soup.select_one("h1.block-head"), "text", ""))
    degree = clean(getattr(bio.select_one(".position-desg"), "text", ""))
    if degree:
        rec["education"].append({"degree": degree, "org": "", "year": ""})
    rec["links"], rec["contact"] = page_links(soup.select_one(".faculty-unit") or soup, url)
    img = soup.select_one(".faculty-unit img")
    if img and (img.get("src") or img.get("data-src")):
        rec["photo"] = urljoin(url, img.get("src") or img.get("data-src"))
    for p in soup.find_all("p"):
        t = clean(p.get_text(" "))
        if t.lower().startswith("research interests:"):
            rec["interests"] = [clean(x) for x in re.split(r"[,;]", t.split(":", 1)[1]) if clean(x)]
            break
    for card in soup.select(".accordion .card"):
        title = clean(getattr(card.select_one(".card-header"), "text", ""))
        paras = []
        for p in card.select(".card-body p"):
            if p.find("p"):
                continue  # wrapper paragraph; its children are handled on their own
            t = clean(p.get_text(" "))
            if t and t not in paras:
                paras.append(t)
        if not title or not paras:
            continue
        if title.lower() == "profile":
            rec["bio"] = paras
        else:
            rec["sections"].append({"title": title, "paragraphs": paras})
    return rec


def parse_generic(soup, url):
    rec = json.loads(json.dumps(EMPTY))
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        t.decompose()
    title = clean(soup.title.get_text()) if soup.title else ""
    rec["name"] = clean(re.split(r"[|,\u2013\u2014-]", title)[0])
    rec["links"], rec["contact"] = page_links(soup, url)
    main = soup.find("main") or soup.body or soup
    paras = [clean(p.get_text(" ")) for p in main.find_all("p")]
    rec["bio"] = [p for p in paras if len(p) > 160][:5]
    return rec


def read_profile(url):
    soup = fetch(url)
    rec = parse_ahduni(soup, url) if "ahduni.edu.in" in url else parse_generic(soup, url)
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    text = re.sub(r"\n\s*\n+", "\n", (soup.find("main") or soup.body or soup).get_text("\n"))
    rec["sources"].append(url)
    return rec, text


def csv_row(email):
    path = os.environ.get("FACULTY_CSV", r"D:\fun projects\university_faculty_directory.csv")
    if not Path(path).exists():
        sys.exit(f"Could not find the faculty list at {path}. Set FACULTY_CSV in .env.")
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Email") or "").strip().lower() == email.lower():
                return row
    sys.exit(f"{email} is not in {path}.")


def orcid_works(orcid_url):
    """Publications from the professor's own ORCID record.

    Only used when the profile page itself links the iD. ORCID is the list the professor keeps;
    author-matching services such as OpenAlex mixed in other people with the same name.
    """
    m = re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dxX]", orcid_url or "")
    if not m:
        return []
    try:
        r = requests.get(f"https://pub.orcid.org/v3.0/{m.group(0)}/works", timeout=40,
                         headers={"Accept": "application/json"})
        groups = r.json().get("group", [])
    except Exception as e:  # network trouble should not stop a page being built
        print(f"  ! ORCID lookup failed: {e}")
        return []
    pubs = []
    for g in groups:
        w = (g.get("work-summary") or [{}])[0]
        title = clean(((w.get("title") or {}).get("title") or {}).get("value"))
        if not title:
            continue
        doi = next((x.get("external-id-value") for x in ((w.get("external-ids") or {}).get("external-id") or [])
                    if x.get("external-id-type") == "doi"), "")
        pubs.append({"title": title, "authors": "", "venue": clean((w.get("journal-title") or {}).get("value")),
                     "year": ((w.get("publication-date") or {}).get("year") or {}).get("value") or "",
                     "url": f"https://doi.org/{doi}" if doi else ""})
    return sorted(pubs, key=lambda x: str(x["year"]), reverse=True)


DEGREE = re.compile(r"^\s*(ph\.?\s?d|d\.?phil|m\.?phil|m\.?sc|m\.?a\b|m\.?s\b|mba|mbbs|md\b|m\.?tech|b\.?tech|b\.?sc|b\.?a\b|llm|llb|j\.?d\b|pgdm|post-?graduate|postdoctoral|bachelor|master|doctor)", re.I)


def from_csv_designation(rec, designation):
    """The faculty list packs role, degrees and links into one cell, separated by semicolons."""
    parts = [clean(x) for x in designation.split(";") if clean(x)]
    if not parts:
        return
    rec["role"] = re.sub(r",?\s*(Ashoka|Ahmedabad) University$", "", parts[0]).strip()
    for part in parts[1:]:
        if part.lower().startswith("http"):
            low = part.lower()
            key = ("scholar" if "scholar.google" in low else "orcid" if "orcid.org" in low
                   else "linkedin" if "linkedin.com" in low else "website")
            rec["links"][key] = rec["links"][key] or part
        elif DEGREE.match(part):
            rec["education"].append({"degree": part, "org": "", "year": ""})


# ---------- optional AI step: messy text -> structured fields ----------

AI_RULES = """You turn text about ONE academic into JSON for a profile page.
Rules:
- Use only facts stated in the text. Never guess, infer, embellish or add outside knowledge.
- If something is not stated, return an empty string or an empty list.
- Copy names, titles, organisations and dates exactly as written.
- "tagline" must be one sentence taken from the text, shortened if needed, under 30 words.
- "bio" is 2 to 4 paragraphs taken from the text, trimmed but not reworded into new claims.
Return JSON only, with exactly these keys:
{"name":"","role":"","department":"","university":"","location":"","tagline":"","bio":[""],"interests":[""],
 "positions":[{"title":"","org":"","start":"","end":"","note":""}],
 "education":[{"degree":"","org":"","year":""}],
 "awards":[{"title":"","by":"","year":""}],
 "teaching":[""],
 "publications":[{"title":"","authors":"","venue":"","year":"","url":""}]}"""


def pick_free_model(key):
    if os.environ.get("OPENROUTER_MODEL"):
        return os.environ["OPENROUTER_MODEL"]
    r = requests.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=40)
    free = [m for m in r.json().get("data", [])
            if m.get("id", "").endswith(":free") and (m.get("context_length") or 0) >= 16000]
    if not free:
        raise RuntimeError("No free model is listed right now. Set OPENROUTER_MODEL in .env.")
    for want in ("llama-3.3-70b", "gemini", "deepseek", "qwen", "mistral", "llama"):
        for m in free:
            if want in m["id"]:
                return m["id"]
    return free[0]["id"]


def ai_extract(text):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        model = pick_free_model(key)
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=120,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": model, "temperature": 0,
                                "messages": [{"role": "system", "content": AI_RULES},
                                             {"role": "user", "content": text[:14000]}]})
        body = r.json()
        if "choices" not in body:
            raise RuntimeError(str(body.get("error") or body)[:300])
        content = body["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}")
        print(f"  AI step used {model}")
        return json.loads(content[start:end + 1])
    except Exception as e:
        print(f"  ! AI step skipped: {e}")
        return None


def merge_ai(rec, ai, source_text):
    """Take AI fields only where the page reader found nothing, and only when the source backs them up."""
    src = set(tokens(source_text))
    dropped = 0
    for key in ("name", "role", "department", "university", "location"):
        if not rec[key] and clean(ai.get(key)) and grounded(ai[key], src, 1.0):
            rec[key] = clean(ai[key])
    tag = clean(ai.get("tagline"))
    if tag and grounded(tag, src, 0.85):
        rec["tagline"] = tag
    for key in ("bio", "interests", "teaching"):
        got = [clean(x) for x in (ai.get(key) or []) if isinstance(x, str) and clean(x)]
        kept = [x for x in got if grounded(x, src, 0.85)]
        dropped += len(got) - len(kept)
        if key == "interests":
            kept = kept[:8]  # a short list reads as a focus; twelve reads as a keyword dump
        if kept and not rec[key]:
            rec[key] = kept
    for key in ("positions", "education", "awards", "publications"):
        got = [x for x in (ai.get(key) or []) if isinstance(x, dict)]
        kept = []
        for item in got:
            item = {k: clean(str(v)) for k, v in item.items() if v not in (None, "")}
            years = re.findall(r"\b(?:19|20)\d{2}\b", " ".join(item.values()))
            if item and grounded(" ".join(item.values()), src) and all(y in source_text for y in years):
                kept.append(item)
        dropped += len(got) - len(kept)
        thin = key == "education" and all(not e.get("org") for e in rec[key])
        if key == "publications":  # the same paper often appears twice, once from the CV and once from Scholar
            seen, unique = set(), []
            for item in kept:
                k = re.sub(r"[^a-z0-9]", "", item.get("title", "").lower())[:60]
                if k and k not in seen:
                    seen.add(k)
                    unique.append(item)
            kept = sorted(unique, key=lambda x: str(x.get("year", "")), reverse=True)
        if kept and (not rec[key] or thin):
            rec[key] = kept
    if dropped:
        print(f"  ! dropped {dropped} AI item(s) that the source text did not support")
    return rec


# ---------- add ----------

def from_text(rec, text):
    """Pick out what needs no AI from pasted information: email, phone, links, and a name on the first line."""
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    if m and not rec["contact"]["email"]:
        rec["contact"]["email"] = m.group(0)
    # A phone number must be labelled or start with "+". Bare digit runs are usually DOIs or page numbers.
    m = (re.search(r"(?:phone|tel|telephone|mobile|mob)\b\W{0,3}(\+?\d[\d ()-]{8,16}\d)", text, re.I)
         or re.search(r"(?<![\w./])(\+\d[\d ()-]{8,16}\d)(?![\w.])", text))
    if m and not rec["contact"]["phone"]:
        rec["contact"]["phone"] = clean(m.group(1))
    for u in re.findall(r"(?:https?://|www\.)[^\s<>\"')\]]+", text):
        u = u.rstrip(".,;")
        full = u if u.startswith("http") else "https://" + u
        low = full.lower()
        key = ("scholar" if "scholar.google" in low and "user=" in low else "orcid" if "orcid.org/" in low
               else "linkedin" if re.search(r"linkedin\.com/(in|pub)/", low) else "")
        if key and not rec["links"][key]:
            rec["links"][key] = full
    cites, h = re.search(r"Citations\s+(\d[\d,]*)", text), re.search(r"h-index\s+(\d+)", text)
    if cites and h:  # the numbers at the top of a pasted Google Scholar page
        rec["metrics"] = {"citations": cites.group(1).replace(",", ""), "h_index": h.group(1)}
    first = next((clean(x) for x in text.splitlines() if clean(x)), "")
    if not rec["name"] and 3 < len(first) <= 60 and "@" not in first and "http" not in first.lower():
        rec["name"] = re.sub(r"^(prof(essor)?\.?|dr\.?)\s+", "", first, flags=re.I)


DOMAINS = {"ashoka.edu.in": "Ashoka University", "ahduni.edu.in": "Ahmedabad University", "flame.edu.in": "FLAME University"}


def known_university(rec):
    """When the pasted text never names the university, take it from the to-do list or the email address."""
    email = rec["contact"]["email"].lower()
    path = ROOT / "queue.csv"
    if path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if (email and row.get("Email", "").lower() == email) or row.get("Name", "").lower() == rec["name"].lower():
                    return clean(row.get("University"))
    return DOMAINS.get(email.split("@")[-1], "")


def plain_bio(text):
    """Fallback profile text when the AI step gave none: real prose paragraphs only, no contact or link lines."""
    paras = [clean(p) for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if len(p) > 160 and "http" not in p.lower() and "@" not in p and p.count(":") <= 2][:4]


def file_text(path):
    """Text of a .txt file, or of a PDF such as LinkedIn's 'Save to PDF' export."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def import_json(path):
    """Take a ready-made JSON file as one professor."""
    p = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not clean(p.get("name")):
        sys.exit(f"{path}: needs a \"name\".")
    p["slug"] = p.get("slug") or slugify(p["name"])
    DATA.mkdir(exist_ok=True)
    (DATA / f"{p['slug']}.json").write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  imported data/{p['slug']}.json")
    return p["slug"]


def cmd_go(a):
    """The daily routine: everything in inbox/ becomes a page, then the site is published."""
    inbox, done = ROOT / "inbox", ROOT / "inbox" / "done"
    done.mkdir(parents=True, exist_ok=True)
    stems = sorted({f.stem for f in inbox.iterdir() if f.is_file() and f.suffix.lower() in (".txt", ".pdf", ".json")})
    if not stems:
        print("  inbox/ is empty. Put a .txt and/or .pdf file per professor in it, named like parag-patel.txt")
    for stem in stems:
        print(f"- {stem}")
        if (inbox / f"{stem}.json").exists():
            import_json(inbox / f"{stem}.json")
        else:
            # parag-patel.txt (university page) and parag-patel.pdf (LinkedIn export) are read together.
            parts = [x for x in (inbox / f"{stem}.txt", inbox / f"{stem}.pdf") if x.exists()]
            RAW.mkdir(exist_ok=True)
            combined = RAW / f"_{stem}.txt"
            combined.write_text("\n\n".join(file_text(x) for x in parts), encoding="utf-8")
            photo = next((str(inbox / f"{stem}{e}") for e in (".jpg", ".jpeg", ".png", ".webp")
                          if (inbox / f"{stem}{e}").exists()), None)
            # With a .txt the name is its first line; with only a PDF the file name is the name.
            name = None if (inbox / f"{stem}.txt").exists() else stem.replace("-", " ").replace("_", " ").title()
            cmd_add(argparse.Namespace(url=None, email=None, text=str(combined), name=name, role=None, university=None,
                                       slug=None, photo=photo, no_photo=False, no_ai=False))
            combined.unlink()
        for g in inbox.glob(stem + ".*"):
            shutil.move(str(g), str(done / g.name))
    if not a.no_deploy:
        cmd_deploy(a)
    else:
        cmd_build(a)

def cmd_add(a):
    load_env()
    rec, text = json.loads(json.dumps(EMPTY)), ""
    url = a.url
    if a.email:
        row = csv_row(a.email)
        url = url or (row.get("Profile_URL") or "").replace("\n", "").replace(" ", "")
        rec["name"], rec["university"] = clean(row["Name"]), clean(row["University"])
        from_csv_designation(rec, row["Designation_Profession"])
        rec["department"] = clean(row.get("Department_School"))
        rec["contact"]["email"] = a.email
        text = "\n".join(f"{k}: {v}" for k, v in row.items() if v)
    if url:
        try:
            page, page_text = read_profile(url)
            for k, v in page.items():
                if isinstance(v, dict):
                    rec[k] = {kk: vv or rec[k].get(kk, "") for kk, vv in v.items()}
                elif v:
                    rec[k] = v
            text += "\n" + page_text
        except Blocked as e:
            print(f"  ! {e}\n    Open the page in your browser, copy all the text into a file, and add --text file.txt")
            rec["links"]["profile"] = url
    if a.text:
        extra = Path(a.text).read_text(encoding="utf-8-sig", errors="ignore")
        # Copying from a web page can glue words together ("ImmunologyCancer"); put the space back.
        extra = re.sub(r"([a-z]{4,})([A-Z][a-z]{4,})", r"\1 \2", extra)
        text += "\n" + extra
        from_text(rec, extra)
        if not a.photo:  # a picture saved next to the text file with the same name
            a.photo = next((str(Path(a.text).with_suffix(e)) for e in (".jpg", ".jpeg", ".png", ".webp")
                            if Path(a.text).with_suffix(e).exists()), None)
    for field in ("name", "role", "university"):
        if getattr(a, field):
            rec[field] = getattr(a, field)
    if not a.no_ai and text.strip():
        ai = ai_extract(text)
        if ai:
            rec = merge_ai(rec, ai, text)
    if not rec["bio"]:
        rec["bio"] = plain_bio(text)
    if not rec["university"]:
        rec["university"] = known_university(rec)
    # A bare title with no organisation and no dates only repeats the headline, or is a stale label from Scholar.
    rec["positions"] = [x for x in rec["positions"] if clean(x.get("org")) or clean(x.get("start"))]
    # Something with no year and no journal is not a publication yet (a manuscript, a project title).
    unpublished = re.compile(r"manuscript|in preparation|work in progress", re.I)
    rec["publications"] = [x for x in rec["publications"]
                           if clean(x.get("year")) or (clean(x.get("venue")) and not unpublished.search(x["venue"]))]
    if not rec["name"]:
        sys.exit("No name found. Pass --name \"Full Name\".")
    rec["slug"] = a.slug or slugify(rec["name"])
    if rec["links"]["orcid"] and not rec["publications"]:
        rec["publications"] = orcid_works(rec["links"]["orcid"])
    src = a.photo or rec["photo"]
    rec["photo"] = ""
    if src and not a.no_photo:
        try:
            PHOTOS.mkdir(exist_ok=True)
            if Path(src).exists():
                ext = Path(src).suffix.lower()
                shutil.copyfile(src, PHOTOS / f"{rec['slug']}{ext}")
            else:
                img = requests.get(src, headers=UA, timeout=45)
                img.raise_for_status()
                ext = ".png" if src.lower().split("?")[0].endswith(".png") else ".jpg"
                (PHOTOS / f"{rec['slug']}{ext}").write_bytes(img.content)
            rec["photo"] = f"/photos/{rec['slug']}{ext}"
        except Exception as e:
            print(f"  ! photo not saved: {e}")
    DATA.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)
    (RAW / f"{rec['slug']}.txt").write_text(text, encoding="utf-8")
    (DATA / f"{rec['slug']}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved data/{rec['slug']}.json  ({len(rec['bio'])} bio paragraphs, {len(rec['interests'])} interests, "
          f"{len(rec['publications'])} publications)")
    cmd_build(a)
    print(f"  Check site/{rec['slug']}/index.html against the real profile before you send the link.")
    return rec["slug"]


# ---------- build ----------

def cmd_build(a):
    SITE.mkdir(exist_ok=True)
    people = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(DATA.glob("*.json"))]
    keep = {p["slug"] for p in people} | {"assets", "photos"}
    for d in SITE.iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name not in keep:
            shutil.rmtree(d)  # a professor whose data file was removed
    for p in people:
        merged = json.loads(json.dumps(EMPTY))
        merged.update(p)
        for k in ("contact", "links"):
            merged[k] = {**EMPTY[k], **(p.get(k) or {})}
        out = SITE / p["slug"]
        out.mkdir(exist_ok=True)
        custom = CUSTOM / f"{p['slug']}.html"  # a hand-made page for this professor wins over the template
        if custom.exists():
            shutil.copyfile(custom, out / "index.html")
        else:
            (out / "index.html").write_text(render(merged), encoding="utf-8")
    shutil.copytree(ASSETS, SITE / "assets", dirs_exist_ok=True)
    if PHOTOS.exists():
        shutil.copytree(PHOTOS, SITE / "photos", dirs_exist_ok=True)
    (SITE / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (SITE / "vercel.json").write_text(json.dumps({"headers": [{"source": "/(.*)", "headers": [
        {"key": "X-Robots-Tag", "value": "noindex, nofollow"}]}]}, indent=2), encoding="utf-8")
    (SITE / "index.html").write_text(
        '<!DOCTYPE html><html lang="en"><meta charset="utf-8"><meta name="robots" content="noindex">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Faculty page demos</title>'
        '<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600&family=Spectral:wght@300;400&display=swap" rel="stylesheet">'
        '<link href="/assets/site.css" rel="stylesheet"><main class="hero wrap"><p class="label label--lg">Faculty page demos</p>'
        '<h1 style="font-size:clamp(40px,6vw,76px)">Each page here was made for one person.</h1>'
        f'<div class="hero__roles"><p class="hero__dept">If you were sent a link, it goes straight to yours. Made by <a href="{MAKER_URL}">{MAKER_NAME}</a>.</p></div>'
        '</main></html>', encoding="utf-8")
    write_links(people)
    print(f"  built {len(people)} page(s) into site/")


def site_url():
    f = ROOT / ".site_url"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def write_links(people):
    base = site_url() or "https://YOUR-SITE.vercel.app"
    with open(ROOT / "links.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Name", "University", "Email", "Page link"])
        for p in people:
            w.writerow([p["name"], p.get("university", ""), (p.get("contact") or {}).get("email", ""), f"{base}/{p['slug']}"])


def cmd_list(a):
    base = site_url() or "(not deployed yet)"
    for f in sorted(DATA.glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        print(f"  {p['name']:<32} {base}/{p['slug']}")


def cmd_deploy(a):
    load_env()
    cmd_build(a)
    project = os.environ.get("VERCEL_PROJECT", "faculty-pages")
    if not (SITE / ".vercel").exists():
        subprocess.run(f"npx --yes vercel link --yes --project {project}", cwd=SITE, shell=True, check=True)
    # Vercel now and then answers "Not authorized" for a moment and then works. Try up to three times.
    import time
    for attempt in range(3):
        out = subprocess.run("npx --yes vercel deploy --prod --yes", cwd=SITE, shell=True, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        log = out.stdout + out.stderr
        m = re.search(r"Aliased\s+(https://\S+)", log) or re.search(r'"productionUrl":\s*"(https://[^"]+)"', log)
        if out.returncode == 0 and m:
            break
        if attempt < 2:
            print(f"  publish attempt {attempt + 1} failed, trying again")
            time.sleep(6)
    else:
        hint = ("\nThe page is saved on this computer. Vercel is refusing the login. Open a terminal in this folder, run "
                "'npx vercel login', then click Make page again or run 'python profpages.py deploy'."
                if "not authorized" in log.lower() else "\nThe page is saved on this computer. Run 'python profpages.py deploy' to try again.")
        sys.exit("Publishing failed after three tries:\n" + log[-900:] + hint)
    (ROOT / ".site_url").write_text(m.group(1), encoding="utf-8")
    write_links([json.loads(f.read_text(encoding="utf-8")) for f in sorted(DATA.glob("*.json"))])
    print(f"  live at {m.group(1)}  (links are in links.csv)")
    git_sync()


def git_sync():
    """Keep a copy of the tool and every professor's data on GitHub. A failure here never blocks publishing."""
    if not (ROOT / ".git").exists():
        return
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    git("add", "-A")
    changes = git("status", "--porcelain").stdout.splitlines()
    if not changes:
        return
    # Name the professor in the commit, so the history reads as a log of the work: "Add page for ...".
    added, updated = [], []
    for line in changes:
        code, path = line[:2], line[3:].strip().strip('"')
        if path.startswith("data/") and path.endswith(".json") and (ROOT / path).exists():
            name = json.loads((ROOT / path).read_text(encoding="utf-8")).get("name") or Path(path).stem
            (added if "A" in code else updated).append(name)
    if added:
        message = "Add page for " + ", ".join(added)
    elif updated:
        message = "Update page for " + ", ".join(updated)
    else:
        message = "Update the page maker"
    git("commit", "-m", message)
    push = git("push")
    print("  saved to GitHub" if push.returncode == 0 else "  ! could not push to GitHub: " + (push.stderr.strip().splitlines() or ["unknown reason"])[-1])


def cmd_app(a):
    """The one-place page maker: a small page on this computer with a paste box and a button."""
    import base64
    import contextlib
    import io
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    load_env()
    port = 8765

    def queue():
        made = {json.loads(f.read_text(encoding="utf-8")).get("contact", {}).get("email", "").lower(): 1 for f in DATA.glob("*.json")}
        slugs = {f.stem for f in DATA.glob("*.json")}
        path = ROOT / "queue.csv"
        if not path.exists():
            return []
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [{"name": r["Name"], "url": r.get("Profile URL", ""),
                     "done": r.get("Email", "").lower() in made or slugify(r["Name"]) in slugs} for r in csv.DictReader(f)]

    def make(d):
        text = (d.get("text") or "").strip()
        if len(text) < 40:
            return {"ok": False, "error": "Paste the professor's information first."}
        RAW.mkdir(exist_ok=True)
        tf = RAW / "_paste.txt"
        tf.write_text(text, encoding="utf-8")
        photo = None
        if d.get("photo"):
            ext = Path(d.get("photoName") or "x.jpg").suffix.lower() or ".jpg"
            pf = RAW / f"_paste{ext}"
            pf.write_bytes(base64.b64decode(d["photo"].split(",", 1)[-1]))
            photo = str(pf)
        # Each page is made by a fresh run of this script, so a window left open for days still uses the
        # newest template and rules on disk instead of whatever it loaded when it started.
        me = [sys.executable, str(ROOT / "profpages.py")]
        add = me + ["add", "--text", str(tf)] + (["--photo", photo] if photo else []) + (["--name", d["name"]] if d.get("name") else [])
        log = ""
        for cmd in (add, me + ["deploy"]):
            run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
            log += run.stdout + run.stderr
            if run.returncode != 0:
                return {"ok": False, "error": (run.stderr or run.stdout).strip().splitlines()[-1] if (run.stderr or run.stdout).strip() else "It stopped without a message.", "log": log}
        found_slug = re.search(r"saved data/([\w-]+)\.json", log)
        if not found_slug:
            return {"ok": False, "error": "The page was not saved.", "log": log}
        slug = found_slug.group(1)
        log = io.StringIO(log)
        rec = json.loads((DATA / f"{slug}.json").read_text(encoding="utf-8"))
        found = (f"Found: {len(rec['bio'])} profile paragraphs, {len(rec['positions'])} roles, {len(rec['education'])} qualifications, "
                 f"{len(rec['publications'])} publications, {len(rec['awards'])} awards, photo {'yes' if rec['photo'] else 'no'}.")
        return {"ok": True, "url": f"{site_url()}/{slug}", "name": rec["name"], "email": rec["contact"]["email"],
                "found": found, "log": log.getvalue()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body, ctype="application/json; charset=utf-8", code=200):
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.reply((ROOT / "app" / "maker.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/queue":
                self.reply(queue())
            else:
                self.reply({"error": "not found"}, code=404)

        def do_POST(self):
            if self.path != "/make":
                return self.reply({"error": "not found"}, code=404)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.reply(make(json.loads(body.decode("utf-8"))))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Page maker is open at http://127.0.0.1:{port}\nKeep this window open while you work. Close it to stop.")
    if not a.no_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # names with accents on a Windows console
    ap = argparse.ArgumentParser(description="Faculty demo pages")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="read one professor and build their page")
    add.add_argument("url", nargs="?", help="profile page address")
    add.add_argument("--email", help="look the professor up in the faculty CSV")
    add.add_argument("--text", help="file of pasted text (LinkedIn, or a page that blocks robots)")
    add.add_argument("--name"), add.add_argument("--role"), add.add_argument("--university"), add.add_argument("--slug")
    add.add_argument("--photo", help="picture file to use")
    add.add_argument("--no-photo", action="store_true", help="use initials instead of a picture")
    add.add_argument("--no-ai", action="store_true", help="skip the OpenRouter step")
    add.set_defaults(fn=cmd_add)
    go = sub.add_parser("go", help="turn every file in inbox/ into a page and publish")
    go.add_argument("--no-deploy", action="store_true", help="build only, do not publish")
    go.set_defaults(fn=cmd_go)
    app = sub.add_parser("app", help="open the paste-and-click page maker in your browser")
    app.add_argument("--no-browser", action="store_true")
    app.set_defaults(fn=cmd_app)
    for name, fn in (("build", cmd_build), ("deploy", cmd_deploy), ("list", cmd_list)):
        sub.add_parser(name).set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
