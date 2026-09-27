"""ARCEN — text tools (Part 3 wrapped)."""

from __future__ import annotations

import hashlib
import textwrap

from pydantic import BaseModel, Field

from .registry import BaseTool


class TextCount(BaseTool):
    name = "text.count"
    description = "Count characters, words, and lines of a text."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="input text")

    def _run(self, a: "TextCount.Args") -> dict:
        return {
            "chars": len(a.text),
            "words": len(a.text.split()),
            "lines": len(a.text.splitlines()),
        }


class TextHash(BaseTool):
    name = "text.hash"
    description = "Hash text with sha256 (or md5/sha1)."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="input text")
        algo: str = Field(default="sha256", description="sha256 | sha1 | md5")

    def _run(self, a: "TextHash.Args") -> dict:
        h = hashlib.new(a.algo, a.text.encode("utf-8"))
        return {"algo": a.algo, "digest": h.hexdigest()}


class TextReplace(BaseTool):
    name = "text.replace"
    description = "Exact-string replace in a text; reports how many replacements."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="input text")
        find: str = Field(description="exact string to find")
        replace: str = Field(description="replacement")

    def _run(self, a: "TextReplace.Args") -> dict:
        n = a.text.count(a.find)
        return {"text": a.text.replace(a.find, a.replace), "replacements": n}


class TextSlice(BaseTool):
    name = "text.slice"
    description = "Slice a text by line range [start, end)."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="input text")
        start: int = Field(default=0, ge=0, description="first line (0-based)")
        end: int | None = Field(default=None, description="one past last line")

    def _run(self, a: "TextSlice.Args") -> dict:
        lines = a.text.splitlines()
        picked = lines[a.start : a.end] if a.end is not None else lines[a.start :]
        return {"content": "\n".join(picked), "total_lines": len(lines)}


class TextWrap(BaseTool):
    name = "text.wrap"
    description = "Wrap text at a width, preserving existing newlines."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        text: str = Field(description="input text")
        width: int = Field(default=80, ge=10, description="max line width")

    def _run(self, a: "TextWrap.Args") -> dict:
        wrapped = "\n".join(
            textwrap.fill(line, width=a.width) or "" for line in a.text.splitlines()
        )
        return {"text": wrapped, "width": a.width}
