"""ARCEN — data format tools (Part 3 wrapped): json, jsonl, yaml, toml, csv."""

from __future__ import annotations

import csv
import io
import json
import tomllib
from typing import Any

import yaml

from pydantic import BaseModel, Field

from .registry import BaseTool


class DataJson(BaseTool):
    name = "data.json"
    description = "Parse a JSON document, or stringify a value with json.dumps."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str | None = Field(default=None, description="JSON text to parse")
        value: Any = Field(default=None, description="value to stringify")
        mode: str = Field(default="parse", description="parse | stringify")
        pretty: bool = Field(default=False, description="indent=2 when stringifying")

    def _run(self, a: "DataJson.Args") -> Any:
        if a.mode == "parse":
            if a.text is None:
                raise ValueError("mode=parse requires text")
            return {"parsed": json.loads(a.text)}
        return {"text": json.dumps(a.value, indent=2 if a.pretty else None, ensure_ascii=False)}


class DataJsonl(BaseTool):
    name = "data.jsonl"
    description = "Parse NDJSON (one JSON object per line) into a list."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="NDJSON text")

    def _run(self, a: "DataJsonl.Args") -> dict:
        items = [json.loads(line) for line in a.text.splitlines() if line.strip()]
        return {"items": items, "count": len(items)}


class DataYaml(BaseTool):
    name = "data.yaml"
    description = "Parse a YAML document (safe loader)."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="YAML text")

    def _run(self, a: "DataYaml.Args") -> dict:
        return {"parsed": yaml.safe_load(a.text)}


class DataToml(BaseTool):
    name = "data.toml"
    description = "Parse a TOML document."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="TOML text")

    def _run(self, a: "DataToml.Args") -> dict:
        return {"parsed": tomllib.loads(a.text)}


class DataCsv(BaseTool):
    name = "data.csv"
    description = "Parse CSV text into a list of row dicts (header row required)."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="CSV text, first row = header")
        delimiter: str = Field(default=",", description="field delimiter")

    def _run(self, a: "DataCsv.Args") -> dict:
        reader = csv.DictReader(io.StringIO(a.text), delimiter=a.delimiter)
        rows = list(reader)
        return {"rows": rows, "count": len(rows), "columns": reader.fieldnames}
