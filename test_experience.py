import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent.experience import check_level

CASES = [
    ("ICT Intern", "Final year students welcome", True),
    ("IT Support Officer", "Minimum 1 year experience in IT support", True),
    ("IT Support Officer", "At least 2 years of experience required", True),
    ("IT Support Officer", "2-3 years experience", True),
    ("IT Support Officer", "3 years experience in helpdesk", False),
    ("ICT Officer", "Minimum of three years working experience", False),
    ("Senior Software Developer", "Build apps", False),
    ("Data Analyst", "5+ years of experience in analytics", False),
    ("Graduate Trainee ICT", "Must have 3 years experience", False),
    ("Web Developer", "We are a company with 10 years in business. No experience needed", True),
    ("IT Officer", "18 months experience", True),
    ("Network Admin", "Mid-level role, 4 years experience", False),
    ("IT Support", "Must be 18 years of age", True),
    ("Helpdesk", "Experience: 6 months", True),
    ("IT Technician", "Requirements:\n- Diploma in IT\n- 1 year of relevant experience", True),
    ("IT Technician", "Requirements:\n- Diploma in IT\n- 4 years of relevant experience", False),
    ("ICT Intern", "Open to graduates with 0-1 years experience", True),
    ("Systems Administrator", "Minimum 2.5 years experience", False),
    ("Business Analyst", "Experience of at least 5 years in a similar role", False),
]

if __name__ == "__main__":
    bad = 0
    for t, d, exp in CASES:
        ok, why = check_level({"title": t, "description": d}, 2)
        if ok != exp:
            bad += 1
        print("OK " if ok == exp else "BAD", t, "|", d[:45], "->", ok, why)
    print("failures:", bad)
    sys.exit(1 if bad else 0)
