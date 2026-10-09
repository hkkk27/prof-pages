"""Where a career has been: find the cities named in a professor's education and roles.

Each entry is (pattern, place name, latitude, longitude). Specific institutions come before bare city names,
and ambiguous names (a bare "Cambridge", "York" inside "New York") are left out on purpose: a missing pin is
better than a wrong one.
"""
import re

PLACES = [
    # India
    (r"Ashoka University|Sonipat|Sonepat", "Sonipat", 28.95, 77.10),
    (r"Ahmedabad|Gujarat University|H\.? ?L\.? ?(College|Institute) of Commerce|\bIIM-?A\b|Amrut Mody", "Ahmedabad", 23.03, 72.58),
    (r"Gandhinagar|GIFT City", "Gandhinagar", 23.22, 72.65),
    (r"\bFLAME\b|\bPune\b|Fergusson|IISER Pune|Symbiosis", "Pune", 18.52, 73.86),
    (r"IIT Bombay|\bTIFR\b|Tata Institute of (Fundamental|Social)|\bMumbai\b|\bBombay\b", "Mumbai", 19.08, 72.88),
    (r"\bDelhi\b|Jawaharlal Nehru University|\bJNU\b|Jamia Millia|\bAIIMS\b|All India Institute of Medical Sciences", "New Delhi", 28.61, 77.21),
    (r"National Brain Research Centre|Manesar|Gurgaon|Gurugram", "Gurugram", 28.46, 77.03),
    (r"Kolkata|Calcutta|Jadavpur|Presidency (College|University)|Indian Institute of Chemical Biology", "Kolkata", 22.57, 88.36),
    (r"\bIISc\b|Indian Institute of Science\b|NIMHANS|\bNCBS\b|Bangalore|Bengaluru|CHRIST \(|Christ University|Vidyashilp|Azim Premji University", "Bengaluru", 12.97, 77.59),
    (r"IIT Madras|\bChennai\b|\bMadras\b", "Chennai", 13.08, 80.27),
    (r"Hyderabad|\bCCMB\b", "Hyderabad", 17.39, 78.49),
    (r"IIT Kanpur|\bKanpur\b", "Kanpur", 26.45, 80.33),
    (r"Kharagpur", "Kharagpur", 22.35, 87.32),
    (r"Varanasi|Banaras|\bBHU\b", "Varanasi", 25.32, 82.99),
    (r"Hubballi|Hubli|KLE Tech", "Hubballi", 15.36, 75.12),
    (r"Rajkot|Atmiya", "Rajkot", 22.30, 70.80),
    (r"\bJaipur\b", "Jaipur", 26.91, 75.79),
    (r"\bLucknow\b", "Lucknow", 26.85, 80.95),
    (r"Chandigarh|Panjab University|Mohali", "Chandigarh", 30.73, 76.78),
    (r"Guwahati", "Guwahati", 26.14, 91.74),
    (r"Bhubaneswar", "Bhubaneswar", 20.30, 85.82),
    (r"Thiruvananthapuram|Trivandrum", "Thiruvananthapuram", 8.52, 76.94),
    (r"\bKochi\b|\bCochin\b", "Kochi", 9.93, 76.27),
    (r"Srinagar", "Srinagar", 34.08, 74.80),
    (r"Aligarh", "Aligarh", 27.90, 78.09),
    (r"Roorkee", "Roorkee", 29.87, 77.89),
    (r"\bManipal\b", "Manipal", 13.35, 74.79),
    # United Kingdom and Europe
    (r"University of Cambridge|Cambridge University|Cambridge,? (UK|United Kingdom|England)|Cambridge Judge|Pembroke College", "Cambridge", 52.21, 0.12),
    (r"Imperial College|London School|University College London|\bUCL\b|King'?s College London|\bSOAS\b|London Business School|\bLondon\b", "London", 51.51, -0.13),
    (r"University of Oxford|Oxford University|\bOxford\b", "Oxford", 51.75, -1.26),
    (r"Edinburgh", "Edinburgh", 55.95, -3.19),
    (r"\bManchester\b", "Manchester", 53.48, -2.24),
    (r"University of York\b", "York", 53.96, -1.08),
    (r"\bWarwick\b", "Coventry", 52.41, -1.51),
    (r"\bSussex\b", "Brighton", 50.82, -0.14),
    (r"\bESSEC\b|\bParis\b|Sorbonne|Sciences Po", "Paris", 48.86, 2.35),
    (r"ETH Z|\bZurich\b|Zürich", "Zurich", 47.37, 8.54),
    (r"\bBerlin\b|Humboldt", "Berlin", 52.52, 13.40),
    (r"\bMunich\b|München", "Munich", 48.14, 11.58),
    (r"Heidelberg", "Heidelberg", 49.40, 8.67),
    (r"\bGeneva\b", "Geneva", 46.20, 6.14),
    (r"Amsterdam", "Amsterdam", 52.37, 4.90),
    (r"\bLeiden\b", "Leiden", 52.16, 4.49),
    (r"Copenhagen", "Copenhagen", 55.68, 12.57),
    (r"Stockholm|Karolinska", "Stockholm", 59.33, 18.07),
    (r"\bVienna\b", "Vienna", 48.21, 16.37),
    (r"Barcelona", "Barcelona", 41.39, 2.17),
    (r"\bDublin\b", "Dublin", 53.35, -6.26),
    # North America
    (r"\bHarvard\b|\bMIT\b|Massachusetts Institute of Technology|\bBoston\b", "Boston", 42.36, -71.06),
    (r"Stony Brook", "Stony Brook", 40.91, -73.12),
    # NYU's campuses abroad are not in New York
    (r"Columbia University|\bNYU\b(?![ -]?(Shanghai|Abu Dhabi))|New York(?! University[ -]?(Shanghai|Abu Dhabi))", "New York", 40.71, -74.01),
    (r"\bYale\b", "New Haven", 41.31, -72.92),
    (r"Princeton", "Princeton", 40.35, -74.66),
    (r"University of Pennsylvania|\bUPenn\b|Wharton|Philadelphia", "Philadelphia", 39.95, -75.17),
    (r"Johns Hopkins|Baltimore", "Baltimore", 39.29, -76.61),
    (r"University of Maryland", "College Park", 38.99, -76.94),
    (r"\bCornell\b", "Ithaca", 42.44, -76.50),
    (r"Illinois Chicago|University of Chicago|\bChicago\b|Northwestern University", "Chicago", 41.88, -87.63),
    (r"University of Michigan|Ann Arbor", "Ann Arbor", 42.28, -83.74),
    (r"University of Wisconsin|Madison, W", "Madison", 43.07, -89.40),
    (r"University of Minnesota|Minneapolis", "Minneapolis", 44.98, -93.27),
    (r"Nebraska", "Lincoln", 40.81, -96.70),
    (r"MD Anderson|\bHouston\b|Rice University|Baylor College", "Houston", 29.76, -95.37),
    (r"Texas at Dallas|\bDallas\b", "Dallas", 32.78, -96.80),
    (r"Texas at Austin|\bAustin, T", "Austin", 30.27, -97.74),
    (r"Georgia Tech|\bEmory\b|\bAtlanta\b", "Atlanta", 33.75, -84.39),
    (r"Duke University", "Durham", 35.99, -78.90),
    (r"California Institute of Technology|\bCaltech\b|Pasadena", "Pasadena", 34.15, -118.14),
    (r"\bUCLA\b|Los Angeles", "Los Angeles", 34.05, -118.24),
    (r"\bStanford\b", "Stanford", 37.43, -122.17),
    (r"Berkeley", "Berkeley", 37.87, -122.27),
    (r"\bUCSF\b|San Francisco", "San Francisco", 37.77, -122.42),
    (r"Scripps Research Institute, Florida|Scripps Florida|Jupiter, F", "Jupiter, Florida", 26.93, -80.09),
    (r"\bUCSD\b|San Diego|La Jolla", "San Diego", 32.72, -117.16),
    (r"University of Washington|\bSeattle\b", "Seattle", 47.61, -122.33),
    (r"\bMcGill\b|Montr[eé]al", "Montreal", 45.50, -73.57),
    (r"\bToronto\b", "Toronto", 43.65, -79.38),
    (r"British Columbia|Vancouver", "Vancouver", 49.28, -123.12),
    (r"West Indies|St\.? Augustine", "St. Augustine", 10.64, -61.40),
    # Asia Pacific and the Gulf
    (r"National University of Singapore|\bNUS\b|\bSingapore\b|Nanyang", "Singapore", 1.35, 103.82),
    (r"Hong Kong", "Hong Kong", 22.32, 114.17),
    (r"\bTokyo\b", "Tokyo", 35.68, 139.69),
    (r"Beijing|Peking|Tsinghua", "Beijing", 39.90, 116.41),
    (r"Shanghai|Fudan", "Shanghai", 31.23, 121.47),
    (r"\bSeoul\b", "Seoul", 37.57, 126.98),
    (r"\bSydney\b", "Sydney", -33.87, 151.21),
    (r"Melbourne", "Melbourne", -37.81, 144.96),
    (r"Abu Dhabi", "Abu Dhabi", 24.45, 54.38),
    (r"\bDubai\b", "Dubai", 25.20, 55.27),
    (r"Sharjah", "Sharjah", 25.35, 55.42),
    (r"Bahrain", "Bahrain", 26.07, 50.56),
]


def find_places(p):
    """Home (the current university's city) plus up to six other cities from education, roles and profile text."""
    home_text = f"{p.get('university', '')} {p.get('location', '')}"
    home = next(((n, la, lo) for pat, n, la, lo in PLACES if re.search(pat, home_text, re.I)), None)
    if not home:
        return None
    parts = [f"{e.get('degree', '')} {e.get('org', '')}" for e in p.get("education", [])]
    parts += [f"{x.get('title', '')} {x.get('org', '')} {x.get('note', '')}" for x in p.get("positions", [])]
    parts += list(p.get("bio", []))
    text = "\n".join(parts)
    found = []
    for pat, n, la, lo in PLACES:
        m = re.search(pat, text)
        if m and n != home[0]:
            found.append((m.start(), n, la, lo))
    others = [{"name": n, "lat": la, "lon": lo} for _, n, la, lo in sorted(found)[:6]]
    return {"home": {"name": home[0], "lat": home[1], "lon": home[2]}, "others": others}
