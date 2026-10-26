"""One response shape for the whole API.

Success: {"data": ...}
Error:   {"error": {"code": "SOME_CODE", "message": "Human readable text", "details": {...}}}
"""
from flask import jsonify


def ok(data=None, status: int = 200):
    return jsonify({"data": data}), status


def fail(code: str, message: str, status: int = 400, details=None):
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    return jsonify({"error": body}), status
