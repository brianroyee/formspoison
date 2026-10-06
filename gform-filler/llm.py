import csv
import gc
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from llama_cpp import Llama
except Exception:  # pragma: no cover
    Llama = None


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:csv|CSV)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _build_prompt(questions: Sequence[Dict[str, object]], row_count: int) -> str:
    header_line = ",".join(q["title"] for q in questions)
    schema_blocks = []
    for q in questions:
        title = str(q["title"])  # noqa: F841
        qtype = int(q["type"])
        required = bool(q.get("required", False))
        options = q.get("options") or []
        block = f"{title} | type={qtype} | required={required}"
        if options:
            block += f" | options={options}"
        schema_blocks.append(block)

    rules = '''
Indian names, plausible Indian college names, +91 phone numbers.
Emails as firstname.lastname@college.edu.
Radio/dropdown columns: pick exactly one value character-for-character from options.
Checkbox columns: pick 1-3 values, comma-separated inside a single quoted field.
Free-text name+contact fields: "Person Name - 9XXXXXXXXX".
No blank required fields.
Output header row + N data rows, nothing else.
'''.strip()

    return (
        "You generate realistic synthetic data for testing form-filling software.\n"
        "You output ONLY valid CSV. No explanations, no markdown fences, no commentary.\n"
        "Every value must conform to the type and constraints given in the schema.\n"
        "Never invent extra columns. Never omit required columns.\n\n"
        f"Header: {header_line}\n\n"
        f"Schema:\n" + "\n".join(schema_blocks) + "\n\nRules:\n" + rules + f"\n\nGenerate exactly {row_count} data rows, with the header row first."
    )


def _validate_row(row: Sequence[str], questions: Sequence[Dict[str, object]], expected_headers: Sequence[str]) -> bool:
    if len(row) != len(expected_headers):
        return False

    for idx, question in enumerate(questions):
        value = row[idx].strip()
        qtype = int(question.get("type", -1))
        options = [str(opt).strip() for opt in question.get("options", []) if opt is not None]
        if qtype in {2, 3}:
            if value not in options:
                return False
        elif qtype == 4:
            tokens = [token.strip() for token in re.split(r"[;,]", value) if token.strip()]
            if not tokens:
                if question.get("required"):
                    return False
                continue
            if any(token not in options for token in tokens):
                return False
    return True


def _parse_and_validate(csv_text: str, expected_headers: Sequence[str], questions: Sequence[Dict[str, object]]) -> List[List[str]]:
    cleaned = _strip_fences(csv_text)
    reader = csv.reader(cleaned.splitlines())
    rows = list(reader)
    if not rows:
        return []

    header_index = None
    normalized_expected = [normalize_header(h) for h in expected_headers]
    for idx, row in enumerate(rows):
        if not row:
            continue
        normalized_row = [normalize_header(cell) for cell in row]
        if len(normalized_row) != len(expected_headers):
            continue
        if normalized_row == normalized_expected:
            header_index = idx
            break

    if header_index is None:
        return []

    valid_rows: List[List[str]] = []
    for row in rows[header_index + 1:]:
        if not row:
            continue
        if not _validate_row(row, questions, expected_headers):
            continue
        valid_rows.append(row)
    return valid_rows


def _fallback_demo_row(question: Dict[str, object], index: int) -> str:
    title = str(question.get("title", "Question"))
    qtype = int(question.get("type", -1))
    options = [str(opt).strip() for opt in (question.get("options") or []) if str(opt).strip()]

    lower = title.lower()
    if any(token in lower for token in ["email", "mail"]):
        return f"student{index + 1}@example.edu"
    if any(token in lower for token in ["phone", "contact", "mobile", "number"]):
        return f"9{index + 1:08d}"
    if any(token in lower for token in ["name", "person", "student"]):
        return f"Student {index + 1}"
    if any(token in lower for token in ["state", "district", "home"]):
        return "Kerala" if index % 2 == 0 else "Tamil Nadu"
    if any(token in lower for token in ["college", "institution", "school"]):
        return "NIT Calicut" if index % 2 == 0 else "IIT Madras"
    if any(token in lower for token in ["department", "branch", "specialisation", "specialization"]):
        return "Computer Science"
    if any(token in lower for token in ["month", "joining", "available"]):
        return "October"
    if any(token in lower for token in ["year", "study"]):
        return "1st"
    if qtype in {2, 3, 5} and options:
        return options[0]
    if qtype == 4 and options:
        return ", ".join(options[:2])
    if qtype == 1:
        return f"Sample response for {title}"
    return f"Auto {index + 1}"


def _fallback_generate_csv(questions: Sequence[Dict[str, object]], row_count: int, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    headers = [str(q["title"]) for q in questions]
    rows: List[List[str]] = []
    for i in range(max(1, row_count)):
        row = [_fallback_demo_row(question, i) for question in questions]
        rows.append(row)

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)

    return output_path


def generate_demo_csv(questions: Sequence[Dict[str, object]], row_count: int, output_path: str = "./responses/_generated.csv") -> str:
    """Generate demo CSV data with a local GGUF model when available, otherwise use a deterministic fallback."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    expected_headers = [str(q["title"]) for q in questions]
    prompt = _build_prompt(questions, row_count)

    model_candidates = [
        os.environ.get("GFORM_LLM_PATH", "./models/ailo-152m-v2-q4_k_m.gguf"),
        "./models/ailo-152m-v2-q4_k_m.gguf",
        "./models/qwen2.5-0.5b-instruct-q4_k_m.gguf",
    ]
    model_path = None
    for candidate in model_candidates:
        if os.path.exists(candidate):
            model_path = candidate
            break

    if model_path is None or Llama is None:
        return _fallback_generate_csv(questions, row_count, output_path)

    llm = Llama(model_path=model_path, n_ctx=4096, n_batch=256, verbose=False, n_gpu_layers=0)
    attempts = 0
    survivors: List[List[str]] = []
    temperature = 0.7
    try:
        while attempts < 3 and not survivors:
            attempts += 1
            response = llm(prompt, max_tokens=2048, temperature=temperature, stop=["\n\n"], echo=False)
            text = response["choices"][0]["text"] if isinstance(response, dict) and "choices" in response else str(response)
            survivors = _parse_and_validate(text, expected_headers, questions)
            if survivors:
                break
            temperature = 0.9
    finally:
        del llm
        gc.collect()

    if not survivors:
        return _fallback_generate_csv(questions, row_count, output_path)

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(expected_headers)
        writer.writerows(survivors)

    return output_path
