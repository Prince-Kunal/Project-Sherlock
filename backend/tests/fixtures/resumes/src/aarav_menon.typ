// Fictional fixture resume. Deliberately ATS-unfriendly in the ways real student resumes often are:
// icon glyphs, links hidden behind words, right-aligned dates, a two-column skills table, creative headings.
#set page(paper: "a4", margin: (x: 0.55in, y: 0.45in))
#set text(font: "New Computer Modern", size: 9.5pt)
#set par(spacing: 0.5em, leading: 0.45em)
#let sec(title) = block(above: 0.7em, below: 0.35em)[#text(size: 11pt, weight: "bold", title) #v(-0.7em) #line(length: 100%, stroke: 0.4pt)]
#let row(left, right) = grid(columns: (1fr, auto), left, right)

#align(center)[
  #text(size: 17pt, weight: "bold")[AARAV MENON] \
  ☎ +91 90000 11111 #h(0.6em) ✉ aarav.menon\@example.com #h(0.6em)
  #link("https://www.linkedin.com/in/aarav-menon-dev")[LinkedIn] #h(0.6em)
  #link("https://github.com/aaravmenon")[GitHub] #h(0.6em)
  #link("https://leetcode.com/u/aaravm")[LeetCode]
]

#sec[Professional Summary]
Information Technology undergraduate with strong foundations in data structures, algorithms and full-stack web development. Enjoys building fast, reliable software and learning new tools.

#sec[Education]
#row[*Example College of Engineering, Chennai*][*2024 – 2028*]
#row[B.Tech in Information Technology][*CGPA:* 9.12]
*Coursework:* Data Structures, OOP, DBMS, Operating Systems, Computer Networks
#row[*Example Online Degree Programme*][*Ongoing*]
#row[B.S. in Programming and Data Science][Diploma in Programming — *CGPA:* 8.8]
#row[*Example Junior College, Bengaluru*][*2024*]
Class XII (PUC) – *97.1%*

#sec[Projects]
#row[*InkTrace – Handwriting Coach for Children*][_February 2026_]
#text(size: 8.5pt)[*Tech Stack:* Python, Flask, JavaScript, NumPy, ESP32]
- Built an IoT pen using an ESP32 that streams motion-sensor data to a laptop over Wi-Fi.
- Recognised handwritten letters with Dynamic Time Warping and k-nearest neighbours at 91% accuracy on 2,400 samples.
- Developed a *Flask backend* and web dashboard showing real-time predictions to teachers.

#row[*QuickNote – Collaborative Markdown Editor*][_May 2026_]
#text(size: 8.5pt)[*Tech Stack:* C++, Crow, React, WebSockets]
- Built a web text editor with a C++ backend and React frontend supporting live collaboration for 10 users.
- Implemented autocomplete with a Trie ranked by a max-heap, returning suggestions in under 5 ms.
- Added undo/redo using two stacks and a REST API for saving documents.

#row[*Pantry Pal – Meal Planner*][_October 2025_]
#text(size: 8.5pt)[*Tech Stack:* Node.js, Express, PostgreSQL, Vercel]
- Built and deployed a recipe search app with prefix search, cuisine filters and saved recipes.
- Designed the PostgreSQL schema and an admin dashboard for moderating 300+ community recipes.

#sec[Technical Skills]
#table(columns: (auto, 1fr, auto, 1fr), stroke: none, inset: 2pt,
  [*Languages:*], [C, C++, Java, Python], [*Web:*], [HTML, CSS, JavaScript, React],
  [*Database:*], [PostgreSQL], [*Tools:*], [Git, GitHub, NumPy, Pandas],
)

#sec[Experience]
#row[*Example Tech Academy – Virtual Internship, AI Agents*][_June 2026 – Present_]
- Building an AI agent that shortlists internship postings and drafts application notes, as part of an 8-week programme.
- Attend weekly instructor-led sessions on LLM tooling and evaluation.

#sec[Certifications & Achievements]
- Solved 250+ data structures and algorithms problems on LeetCode and HackerRank.
- Completed a cloud engineering certificate on an online learning platform.
- Secured 2nd place at a national engineering design fair (2026) for InkTrace.

#sec[Leadership & Extracurricular]
- Deputy Head, Competitive Programming Wing of the college computer society; run monthly contests for juniors.
- Grade 7 certificate in classical guitar; teach beginners on weekends.
