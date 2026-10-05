import json
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.resume.skills import SkillLexicon, get_lexicon


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("reactjs", "react"),
        ("React.js", "react"),
        ("REACT", "react"),
        ("postgres", "postgresql"),
        ("PostgreSQL", "postgresql"),
        ("Node JS", "node.js"),
        ("nodejs", "node.js"),
        ("golang", "go"),
        ("K8s", "kubernetes"),
        ("scikit learn", "scikit-learn"),
        ("ROS2", "ros 2"),
        ("Python3", "python"),
        ("  C++ ", "c++"),
        ("c#", "c#"),
        ("OOPS", "object-oriented programming"),
    ],
)
def test_aliases_normalise_to_canonical(raw: str, canonical: str) -> None:
    assert get_lexicon().normalize(raw) == canonical


def test_c_family_kept_distinct() -> None:
    lexicon = get_lexicon()
    assert {lexicon.normalize(s) for s in ["C", "C++", "C#"]} == {"c", "c++", "c#"}


def test_unknown_skill_is_lowercased_and_collapsed() -> None:
    assert get_lexicon().normalize("  Dynamic   Time Warping ") == "dynamic time warping"
    assert not get_lexicon().is_known("dynamic time warping")


def test_normalize_all_dedupes_preserving_order() -> None:
    assert get_lexicon().normalize_all(["ReactJS", "postgres", "React", "", "Postgres"]) == [
        "react",
        "postgresql",
    ]


def test_ambiguous_words_are_not_aliases() -> None:
    lexicon = get_lexicon()
    assert lexicon.normalize("cv") == "cv"  # "CV" usually means resume, not computer vision
    assert lexicon.normalize("next") == "next"


def test_alias_file_has_no_conflicts() -> None:
    """Every alias maps to exactly one canonical skill."""
    data = json.loads((Path(get_settings().data_dir) / "skills_aliases.json").read_text())
    lexicon = SkillLexicon(data)
    for canonical, aliases in data.items():
        for alias in aliases:
            assert lexicon.normalize(alias) == canonical, (alias, canonical)
