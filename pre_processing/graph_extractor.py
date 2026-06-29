import json
import os
import re

from dotenv import load_dotenv

load_dotenv(r".env")


ARTICLE_NUMBER = r"\d+(?:[.-]\d+)*"
ORDINAL_SUFFIX = r"(?:cı|ci|cu|cü)"
CONNECTOR = r"(?:və ya|və|habelə)"
RANGE_DASH = r"[-–—]"


def normalize_reference_text(text):
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def reference_key(reference_number):
    return tuple(int(part) for part in re.split(r"[.-]", reference_number) if part)


def build_reference_lookup(all_nodes):
    lookup = {}
    for node_id, data in all_nodes.items():
        lookup.setdefault(data["number"], []).append(node_id)
    return lookup


def resolve_reference_number(reference_number, reference_lookup):
    node_ids = reference_lookup.get(reference_number)
    return node_ids[0] if node_ids else None


def expand_reference_range(start_number, end_number, sorted_reference_numbers):
    start_key = reference_key(start_number)
    end_key = reference_key(end_number)
    return [
        candidate
        for candidate in sorted_reference_numbers
        if start_key <= reference_key(candidate) <= end_key
    ]


def split_reference_body(body):
    parts = re.split(r"\s*,\s*|\s+(?:və ya|və|habelə)\s+", body)
    return [part.strip() for part in parts if part.strip()]


def extract_references_from_text(full_text, reference_lookup, sorted_reference_numbers):
    normalized_text = normalize_reference_text(full_text)
    list_item = rf"(?:{ARTICLE_NUMBER}(?:\s*{RANGE_DASH}\s*{ARTICLE_NUMBER})?)"
    range_item = rf"{ARTICLE_NUMBER}\s*{RANGE_DASH}\s*{ARTICLE_NUMBER}"

    reference_group_patterns = [
        # E. Mixed lists
        re.compile(
            rf"(?P<body>(?=.*{range_item})(?=.*{ARTICLE_NUMBER})[\d.\-,\s]+)\s*-\s*{ORDINAL_SUFFIX}\s+maddə\w*",
            re.IGNORECASE,
        ),
        # D. Pure ranges
        re.compile(
            rf"(?P<body>{range_item}(?:\s*,\s*{range_item})*)\s*-\s*{ORDINAL_SUFFIX}\s+maddə\w*",
            re.IGNORECASE,
        ),
        # C. Simple list with 3+ references
        re.compile(
            rf"(?P<body>{list_item}(?:\s*,\s*{list_item})*(?:\s*,?\s*{CONNECTOR}\s*{list_item}))\s*-\s*{ORDINAL_SUFFIX}\s+maddə\w*",
            re.IGNORECASE,
        ),
        # B. Simple list with exactly 2 references
        re.compile(
            rf"(?P<ref1>{list_item})\s*{CONNECTOR}\s*(?P<ref2>{list_item})\s*-\s*{ORDINAL_SUFFIX}\s+maddə\w*",
            re.IGNORECASE,
        ),
        # A. Single reference: one Maddə or MaddəSection only, including numbered articles
        # like 195-1 and nested sections like 171-1.2.3 or 99-1.1.
        re.compile(
            rf"(?P<ref>{ARTICLE_NUMBER})\s*-\s*{ORDINAL_SUFFIX}\s+maddə\w*",
            re.IGNORECASE,
        ),
    ]

    matches = []
    occupied_spans = []
    for pattern in reference_group_patterns:
        for match in pattern.finditer(normalized_text):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied_spans):
                continue
            occupied_spans.append(span)
            matches.append(match)

    references = []
    seen_references = set()
    for match in matches:
        if "body" in match.groupdict():
            tokens = split_reference_body(match.group("body"))
        elif "ref1" in match.groupdict():
            tokens = [match.group("ref1"), match.group("ref2")]
        else:
            tokens = [match.group("ref")]

        for token in tokens:
            if not token:
                continue

            # Exact lookup first keeps single references like 171-1.2.3 from being
            # mistaken for ranges just because they contain hyphens.
            if token in reference_lookup:
                candidate_numbers = [token]
            elif re.fullmatch(range_item, token):
                start_number, end_number = re.split(r"\s*[-–—]\s*", token, maxsplit=1)
                candidate_numbers = expand_reference_range(start_number, end_number, sorted_reference_numbers)
            else:
                candidate_numbers = [token]

            for candidate_number in candidate_numbers:
                target_id = resolve_reference_number(candidate_number, reference_lookup)
                if target_id and target_id not in seen_references:
                    references.append(target_id)
                    seen_references.add(target_id)

    return references


def extract_graph(input_path, output_path):
    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    nodes = []
    edges = []

    current_hisse = None
    current_bolme = None
    current_fasil = None
    current_madde = None
    current_section = None

    hisse_pattern = re.compile(r"^.*HİSSƏ$", re.IGNORECASE)
    bolme_pattern = re.compile(r"^.*BÖLMƏ$", re.IGNORECASE)
    fasil_pattern = re.compile(rf"^(\d+)-(?:{ORDINAL_SUFFIX}) fəsil$", re.IGNORECASE)
    madde_pattern = re.compile(rf"^Maddə\s+({ARTICLE_NUMBER})\.?\s*(.*)$", re.IGNORECASE)
    section_pattern = re.compile(rf"^({ARTICLE_NUMBER})\.\s*(.*)$")

    all_maddes = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if hisse_pattern.match(line):
            current_hisse = line
            nodes.append({"id": current_hisse, "type": "HİSSƏ", "text": current_hisse})
            current_bolme = None
            current_fasil = None
            current_madde = None
            current_section = None
            continue

        if bolme_pattern.match(line):
            current_bolme = line
            nodes.append({"id": current_bolme, "type": "BÖLMƏ", "text": current_bolme})
            if current_hisse:
                edges.append({"source": current_bolme, "target": current_hisse, "relation": "part_of"})
            current_fasil = None
            current_madde = None
            current_section = None
            continue

        fasil_match = fasil_pattern.match(line)
        if fasil_match:
            current_fasil = line
            nodes.append({"id": current_fasil, "type": "fəsil", "text": current_fasil})
            if current_bolme:
                edges.append({"source": current_fasil, "target": current_bolme, "relation": "part_of"})
            current_madde = None
            current_section = None
            continue

        madde_match = madde_pattern.match(line)
        if madde_match:
            madde_num = madde_match.group(1)
            madde_title = madde_match.group(2)
            current_madde = f"Maddə {madde_num}"
            current_section = None

            nodes.append(
                {
                    "id": current_madde,
                    "type": "Maddə",
                    "text": f"{current_madde}. {madde_title}",
                    "number": madde_num,
                }
            )

            if current_fasil:
                edges.append({"source": current_madde, "target": current_fasil, "relation": "part_of"})

            all_maddes[current_madde] = {"content": [line], "number": madde_num}
            continue

        section_match = section_pattern.match(line)
        if section_match and current_madde:
            section_num = section_match.group(1)
            section_text = section_match.group(2)
            current_section = f"{current_madde} Section {section_num}"

            nodes.append(
                {
                    "id": current_section,
                    "type": "MaddəSection",
                    "text": f"{section_num}. {section_text}",
                    "number": section_num,
                }
            )
            edges.append({"source": current_section, "target": current_madde, "relation": "part_of"})
            all_maddes[current_section] = {"content": [line], "number": section_num}
            continue

        if current_madde:
            target_id = current_section if current_section else current_madde
            all_maddes[target_id]["content"].append(line)

    reference_lookup = build_reference_lookup(all_maddes)
    sorted_reference_numbers = sorted(reference_lookup.keys(), key=reference_key)

    for node_id, data in all_maddes.items():
        full_text = " ".join(data["content"])
        for node in nodes:
            if node["id"] == node_id:
                node["text"] = full_text
                break

        refs = extract_references_from_text(full_text, reference_lookup, sorted_reference_numbers)
        seen_refs = set()
        for target_id in refs:
            if target_id and target_id != node_id and target_id not in seen_refs:
                edges.append({"source": node_id, "target": target_id, "relation": "references"})
                seen_refs.add(target_id)

    node_map = {node["id"]: node for node in nodes}
    for node in nodes:
        if node["type"] in {"MaddəSection", "Maddə", "fəsil", "BÖLMƏ"}:
            parent_id = None
            for edge in edges:
                if edge["source"] == node["id"] and edge["relation"] == "part_of":
                    parent_id = edge["target"]
                    break
            if parent_id and parent_id in node_map:
                node["title"] = node_map[parent_id].get("text", "")

    graph = {"nodes": nodes, "edges": edges}

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=4)

    print(f"Graph extracted and saved to {output_path}")


if __name__ == "__main__":
    input_file = os.environ["INPUT_FILE_PATH"]
    output_file = os.environ["OUTPUT_FILE_PATH"]
    extract_graph(input_file, output_file)
