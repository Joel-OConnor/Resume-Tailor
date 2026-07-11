<!--
  RESUME FORMAT CONTRACT — tools/build.py renders this exact structure into an ATS-safe .docx + .pdf.
  Keep to it so exports come out clean. (Everything inside this comment is stripped on export.)

    # Full Name                     → the name (one, first line)
    lines until the first "## "     → header lines: an optional title, then the contact line
    ## Section                      → a section heading (Summary, Skills, Experience, Education, …)
    ### Entry Title                 → a role/degree/project title (bold)
    a plain line right after ###    → the dates/location line (italic)
    **Label:** a, b, c              → a skills line: bold label + normal items
    - bullet                        → a bullet point
    **bold** inline                 → bold text within any line

  Rules: single column, standard headings, no tables/images/columns. Contact on ONE line, separated
  by " | ". Use real text (no icons). This file is a valid example — copy it and fill in real data.
-->

# Jordan Rivera
Senior Backend Engineer
jordan.rivera@email.com | (415) 555-0132 | Austin, TX | linkedin.com/in/jordanrivera | github.com/jrivera

## Summary
Senior backend engineer with 8 years building high-throughput payment and data services. Specializes
in Python and Go on AWS, scaling systems to millions of daily transactions and mentoring teams toward
faster, safer delivery.

## Skills
**Languages:** Python, Go, SQL, TypeScript
**Cloud & Infra:** AWS (ECS, Lambda, RDS), Kubernetes, Terraform, Docker
**Data:** PostgreSQL, Redis, Kafka, DynamoDB
**Practices:** CI/CD (GitHub Actions), observability, test-driven development, on-call leadership

## Experience

### Senior Backend Engineer, Northwind Payments — Austin, TX
Mar 2021 – Present
- Redesigned the settlement pipeline to process 4M+ daily transactions, cutting end-to-end latency 38% (820ms → 510ms).
- Led migration from a monolith to 6 Go microservices, reducing deploy time from 2 days to under 1 hour.
- Introduced automated load testing that caught 3 severe regressions before release, avoiding an estimated $200k in incident costs.
- Mentored 4 engineers; two were promoted within a year.

### Backend Engineer, Cedar Analytics — Remote
Jun 2018 – Feb 2021
- Built a Kafka-based event pipeline ingesting 500M events/day with 99.98% delivery reliability.
- Cut monthly AWS spend 22% (~$14k/mo) by right-sizing services and adding autoscaling.
- Shipped the public REST API used by 40+ enterprise customers.

## Education

### B.S. Computer Science, University of Texas at Austin — Austin, TX
2016

## Certifications
- AWS Certified Solutions Architect – Associate — Amazon — 2022
