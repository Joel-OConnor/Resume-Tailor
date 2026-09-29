<!--
  RESUME FORMAT CONTRACT — this exact structure renders into:
    resume.docx / resume.pdf                    single column, parser-safe, designed → send anywhere
    resume-polished.docx / resume-polished.pdf  the two-column version, only with --layout polished

  Syntax:
    # Full Name                     the name (one, first line)
    lines until the first blank     header lines — a target title, then the contact line
    a header line with any "|"      treated as contact details (the rail in the two-column
                                    version), so keep pipes out of the target-title line
    ## Section                      section heading (Summary, Skills, Experience, Education, …)
    ### Entry Title                 a role, degree, project, or certification
    ### **Title** – Company         bold only the job title (or degree); the company stays regular
    a plain line right after ###    the dates/location line (italic)
    **Label:** a, b, c              a skills line: bold label + comma-separated items
    - bullet  (or * bullet)         a bullet point, on one line however long it runs. Don't
                                    wrap it: a wrapped line becomes a separate paragraph
    - **Lead-in:** text             a bullet with a bold lead-in (both layouts keep the glyph)
    *Tech Stack — a, b, c*          a plain line after the bullets: an italic note, no bullet glyph
    a line ending in "\"            a hard line break (prose lines are otherwise joined)
    --- or ___ or ***               a horizontal rule; dropped on export, so use it only as a
                                    working marker you do not want to appear
    **bold**  *italic*  _italic_    inline emphasis; ***both*** is bold + italic. It nests,
    ***both***                      and \* \_ \\ print that character literally. Works
                                    everywhere except `##` section headings.

  Rules:
    - Single column, standard headings, no tables/images/columns of your own.
    - Contact details on ONE line separated by " | ". Real text, no icons.
    - In the two-column version, Skills / Education / Certifications go in the left rail; keep
      those entries short so they don't wrap badly in a 2.42in column.
    - Order everything most-relevant-first. The top third of page one is what gets read.

  This file is a valid example — copy it and fill in real data. Comments are stripped on export.
-->

# Jordan Rivera
Senior Backend Engineer
jordan.rivera@email.com | (415) 555-0132 | Austin, TX | linkedin.com/in/jordanrivera | github.com/jrivera

## Summary
Senior backend engineer with 8 years building high-throughput payment and data services.
Specializes in Python and Go on AWS, scaling systems to millions of daily transactions and
mentoring teams toward faster, safer delivery.

## Skills
**Languages:** Python, Go, SQL, TypeScript
**Cloud & Infra:** AWS (ECS, Lambda, RDS), Kubernetes, Terraform, Docker
**Data:** PostgreSQL, Redis, Kafka, DynamoDB
**Practices:** CI/CD (GitHub Actions), Observability, Test-Driven Development

## Experience

### **Senior Backend Engineer** – Northwind Payments
Austin, TX | Mar 2021 – Present
- **Settlement Throughput:** Redesigned the settlement pipeline to process 4M+ daily transactions, cutting end-to-end latency 38% (820ms → 510ms).
- **Service Decomposition:** Led migration from a monolith to 6 Go microservices, reducing deploy time from 2 days to under 1 hour.
- **Release Safety:** Introduced automated load testing that caught 3 severe regressions before release, avoiding an estimated $200k in incident costs.
- **Mentorship:** Mentored 4 engineers; two were promoted within a year.
*Tech Stack — Go, Python, PostgreSQL, Kafka, AWS (ECS, Lambda, RDS), Terraform, GitHub Actions*

### **Backend Engineer** – Cedar Analytics
Remote | Jun 2018 – Feb 2021
- **Event Pipeline:** Built a Kafka-based event pipeline ingesting 500M events/day with 99.98% delivery reliability.
- **Cost Reduction:** Cut monthly AWS spend 22% (~$14k/mo) by right-sizing services and adding autoscaling.
- **Public API:** Shipped the public REST API used by 40+ enterprise customers.
*Tech Stack — Python, Kafka, DynamoDB, AWS (Lambda, RDS), Docker*

## Education

### **B.S. Computer Science** – University of Texas at Austin
Austin, TX | 2016

## Certifications
- AWS Certified Solutions Architect – Associate — Amazon — 2022
