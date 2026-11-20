from io import BytesIO

from werkzeug.datastructures import FileStorage

from app.modules.questions import importer


def test_structured_csv_maps_questions_and_answer_keys():
    raw = (
        "Question,Option A,Option B,Option C,Option D,Correct Answer,Marks,Topic\n"
        '"What is 2 + 2?",3,4,5,6,B,2,Arithmetic\n'
        '"What is the capital of France?",Berlin,Paris,Rome,Madrid,B,1,Geography\n'
    ).encode("utf-8")
    headers, rows = importer._read_csv(raw)
    mapping = importer._detect_mapping(headers)
    extracted = importer.extract_structured(headers, rows, mapping)

    assert extracted["needs_mapping"] is False
    assert len(extracted["questions"]) == 2
    assert extracted["questions"][0]["correct_index"] == 1
    assert extracted["questions"][0]["marks"] == 2
    assert extracted["questions"][1]["topic"] == "Geography"


def test_unstructured_text_flags_unknown_answer_instead_of_inventing_it():
    source = """1. Which planet is known as the Red Planet?
A) Earth
B) Mars
C) Venus
D) Jupiter

2. Which statement is correct?
A) The Sun is a star
B) The Sun is a planet
"""
    extracted = importer.extract_unstructured(source)

    assert len(extracted["questions"]) == 2
    assert extracted["questions"][0]["correct_index"] is None
    assert any("Correct answer was not identified" in w for w in extracted["questions"][0]["warnings"])


def test_import_source_is_scoped_to_uploading_user(app):
    class User:
        id = 19
        institution_id = 42

    with app.app_context():
        source = FileStorage(
            stream=BytesIO(b"Question,Option A,Option B,Correct Answer\nWhat is 2 + 2?,3,4,B\n"),
            filename="sample.csv",
            content_type="text/csv",
        )
        preview = importer.create_import(User(), source)
        path, filename = importer.get_source(User.institution_id, User.id, preview["token"])
        assert path.is_file()
        assert filename == "sample.csv"
        try:
            importer.get_source(User.institution_id, 99, preview["token"])
            assert False, "A different user must not read this upload"
        except Exception as exc:
            assert getattr(exc, "code", None) == "IMPORT_NOT_FOUND"
