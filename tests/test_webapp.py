import json

from fastapi.testclient import TestClient

from reproseed.webapp import app


client = TestClient(app)


def notebook_bytes() -> bytes:
    return json.dumps(
        {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": 1,
                    "metadata": {},
                    "outputs": [],
                    "source": ["import random\n", "value = random.random()\n"],
                }
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    ).encode()


def test_home_and_health_endpoints() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "ReproSeed" in response.text
    assert client.get("/health").json()["status"] == "ok"


def test_notebook_upload_returns_explainable_report() -> None:
    response = client.post(
        "/api/analyze/notebook",
        files={"file": ("study.ipynb", notebook_bytes(), "application/x-ipynb+json")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "study.ipynb"
    assert payload["score"] < 100
    assert "RANDOM_SEED_MISSING" in {item["code"] for item in payload["findings"]}
    assert set(payload["generated_files"]) == {"Dockerfile", "environment.yml"}


def test_notebook_upload_validates_extension_and_json() -> None:
    wrong_extension = client.post(
        "/api/analyze/notebook", files={"file": ("study.txt", b"{}", "text/plain")}
    )
    invalid_json = client.post(
        "/api/analyze/notebook", files={"file": ("study.ipynb", b"not-json", "application/json")}
    )

    assert wrong_extension.status_code == 422
    assert invalid_json.status_code == 422

