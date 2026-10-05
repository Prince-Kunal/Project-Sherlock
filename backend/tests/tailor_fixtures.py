"""A small, hand-written master resume and plans for the Phase 4 tailoring tests (fictional person)."""

from app.schemas.resume import Basics, Bullet, Education, Experience, Link, MasterResume, Project
from app.schemas.tailor import Rephrasing, TailorPlan

JD = (
    "Backend Engineering Intern. You will build services in Python on PostgreSQL. Redis is a must, "
    "and Kubernetes experience is required. Docker is nice to have."
)


def master() -> MasterResume:
    return MasterResume(
        basics=Basics(
            name="Asha Verma",
            email="asha.verma@example.com",
            phone="+91 98765 43210",
            location="Bengaluru",
            links=[Link(label="GitHub", url="https://github.com/ashaverma")],
        ),
        summary="Computer science student who builds backend services in Python.",
        education=[
            Education(
                id="edu1",
                institution="Example Institute of Technology",
                degree="B.Tech",
                field="Computer Science",
                start="2023-08",
                end="2027-05",
                gpa="8.9",
                bullets=[
                    Bullet(
                        id="edu1-b1",
                        text="Coursework: Operating Systems, DBMS, Computer Networks",
                        skills=["operating systems", "dbms"],
                    )
                ],
            )
        ],
        experience=[
            Experience(
                id="exp1",
                org="Example Payments",
                role="Backend Intern",
                location="Bengaluru",
                start="2025-05",
                end="2025-07",
                bullets=[
                    Bullet(
                        id="exp1-b1",
                        text="Built REST APIs in Python and Flask backed by postgres for merchant onboarding",
                        skills=["python", "flask", "postgresql", "rest api"],
                        pinned=True,
                    ),
                    Bullet(
                        id="exp1-b2",
                        text="Made the search API faster with Redis caching, cutting p95 latency by 30%",
                        skills=["redis", "rest api"],
                    ),
                    Bullet(
                        id="exp1-b3",
                        text="Wrote unit tests and raised coverage from 55% to 80% before go-live",
                        skills=["python"],
                    ),
                ],
            )
        ],
        projects=[
            Project(
                id="proj1",
                name="Campus Ride Share",
                tech=["React", "Node.js", "MongoDB"],
                bullets=[
                    Bullet(
                        id="proj1-b1",
                        text="Built a ride-matching app used by 300 students in its first month",
                        skills=["react", "node.js", "mongodb"],
                    ),
                    Bullet(
                        id="proj1-b2",
                        text="Designed the matching service with geohash bucketing",
                        skills=["node.js"],
                    ),
                ],
            ),
            Project(
                id="proj2",
                name="Log Summarizer",
                link="github.com/ashaverma/logsum",
                tech=["Python", "Docker"],
                bullets=[
                    Bullet(
                        id="proj2-b1",
                        text="Containerised a log summarisation pipeline with Docker",
                        skills=["docker", "python"],
                    )
                ],
            ),
        ],
        skills={
            "Languages": ["Python", "JavaScript", "SQL"],
            "Backend": ["Flask", "Node.js", "postgres", "Redis"],
            "Tools": ["Docker", "Git"],
        },
        achievements=[Bullet(id="ach1", text="Finalist, Smart India Hackathon 2024")],
    )


def valid_plan(**overrides: object) -> TailorPlan:
    data: dict[str, object] = {
        "section_order": ["education", "experience", "projects", "skills"],
        # exp1-b3 ranks above exp1-b2 (reordered); proj2 outranks proj1; proj1-b2 and ach1 are left out.
        "selected_bullet_ids": ["exp1-b1", "exp1-b3", "proj2-b1", "exp1-b2", "proj1-b1", "edu1-b1"],
        "rephrasings": [
            Rephrasing(
                bullet_id="exp1-b2", text="Cut p95 latency of the search REST API by 30% with Redis caching"
            )
        ],
        "skills_to_show": ["Python", "postgres", "Redis", "Flask", "Docker", "SQL", "Git"],
        "summary": None,
        "jd_keywords": ["Python", "PostgreSQL", "Redis", "Kubernetes"],
    }
    data.update(overrides)
    return TailorPlan.model_validate(data)
