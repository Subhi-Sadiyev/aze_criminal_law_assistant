import re
import json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(r".env")

def extract_graph(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    nodes = []
    edges = []
    
    current_hisse = None
    current_bolme = None
    current_fasil = None
    current_madde = None
    
    # Regex patterns
    hisse_pattern = re.compile(r'^.*HİSSƏ$', re.IGNORECASE)
    bolme_pattern = re.compile(r'^.*BÖLMƏ$', re.IGNORECASE)
    fasil_pattern = re.compile(r'^(\d+)-(?:cı|ci|cu|cü) fəsil$', re.IGNORECASE)
    madde_pattern = re.compile(r'^Maddə\s+(\d+)\.?\s*(.*)$', re.IGNORECASE)
    section_pattern = re.compile(r'^(\d+(?:[\.\-]\d+)+)\.\s*(.*)$')
    # Reference pattern: e.g., "6.1-ci maddəsində" or "12-ci maddəsinə", including plural forms and various ordinal suffixes
    ref_pattern = re.compile(r'(\d+(?:[\.\-]\d+)*)-(?:cı|ci|cu|cü)\s+maddə\w*', re.IGNORECASE)

    all_maddes = {} # To store madde content for reference extraction later

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for HİSSƏ
        if hisse_pattern.match(line):
            current_hisse = line
            nodes.append({"id": current_hisse, "type": "HİSSƏ", "text": current_hisse})
            current_bolme = None
            current_fasil = None
            current_madde = None
            continue

        # Check for BÖLMƏ
        if bolme_pattern.match(line):
            current_bolme = line
            nodes.append({"id": current_bolme, "type": "BÖLMƏ", "text": current_bolme})
            if current_hisse:
                edges.append({"source": current_bolme, "target": current_hisse, "relation": "part_of"})
            current_fasil = None
            current_madde = None
            continue

        # Check for fəsil
        fasil_match = fasil_pattern.match(line)
        if fasil_match:
            current_fasil = line
            nodes.append({"id": current_fasil, "type": "fəsil", "text": current_fasil})
            if current_bolme:
                edges.append({"source": current_fasil, "target": current_bolme, "relation": "part_of"})
            current_madde = None
            continue

        # Check for Maddə
        madde_match = madde_pattern.match(line)
        if madde_match:
            madde_num = madde_match.group(1)
            madde_title = madde_match.group(2)
            current_madde = f"Maddə {madde_num}"
            
            nodes.append({
                "id": current_madde, 
                "type": "Maddə", 
                "text": f"{current_madde}. {madde_title}",
                "number": madde_num
            })
            
            if current_fasil:
                edges.append({"source": current_madde, "target": current_fasil, "relation": "part_of"})
            
            all_maddes[current_madde] = {"content": [line], "number": madde_num}
            current_section = None
            continue

        # Check for Section within Maddə
        section_match = section_pattern.match(line)
        if section_match and current_madde:
            section_num = section_match.group(1)
            section_text = section_match.group(2)
            current_section = f"{current_madde} Section {section_num}"
            
            nodes.append({
                "id": current_section,
                "type": "MaddəSection",
                "text": f"{section_num}. {section_text}",
                "number": section_num
            })
            edges.append({"source": current_section, "target": current_madde, "relation": "part_of"})
            all_maddes[current_section] = {"content": [line], "number": section_num}
            continue

        # If we are inside a Maddə or Section, collect its content
        if current_madde:
            target_id = current_section if current_section else current_madde
            all_maddes[target_id]["content"].append(line)

    # Finalize Maddə contents and extract references
    for node_id, data in all_maddes.items():
        full_text = " ".join(data["content"])
        # Update node with full text if needed (optional, but good for completeness)
        for node in nodes:
            if node["id"] == node_id:
                node["text"] = full_text
                break
        
        # Extract references to other Maddəs or Sections
        refs = ref_pattern.findall(full_text)
        for ref_num in refs:
            # Try to find a section first, then the madde itself
            target_id = None
            # Check if it's a section (e.g., 6.1)
            if "." in ref_num:
                potential_section = f"Maddə {ref_num.split('.')[0]} Section {ref_num}"
                if potential_section in all_maddes:
                    target_id = potential_section
            
            # If not a section or section not found, check for the madde (e.g., 6)
            if not target_id:
                potential_madde = f"Maddə {ref_num.split('.')[0]}"
                if potential_madde in all_maddes:
                    target_id = potential_madde
            
            if target_id:
                edges.append({"source": node_id, "target": target_id, "relation": "references"})

    # Post-process nodes to add 'title' based on parent text
    node_map = {node["id"]: node for node in nodes}
    for node in nodes:
        if node["type"] == "MaddəSection":
            parent_id = None
            # Find the Maddə this section belongs to
            for edge in edges:
                if edge["source"] == node["id"] and edge["relation"] == "part_of":
                    parent_id = edge["target"]
                    break
            if parent_id and parent_id in node_map:
                node["title"] = node_map[parent_id].get("text", "")

        elif node["type"] == "Maddə":
            parent_id = None
            for edge in edges:
                if edge["source"] == node["id"] and edge["relation"] == "part_of":
                    parent_id = edge["target"]
                    break
            if parent_id and parent_id in node_map:
                node["title"] = node_map[parent_id].get("text", "")

        elif node["type"] == "fəsil":
            parent_id = None
            for edge in edges:
                if edge["source"] == node["id"] and edge["relation"] == "part_of":
                    parent_id = edge["target"]
                    break
            if parent_id and parent_id in node_map:
                node["title"] = node_map[parent_id].get("text", "")

        elif node["type"] == "BÖLMƏ":
            parent_id = None
            for edge in edges:
                if edge["source"] == node["id"] and edge["relation"] == "part_of":
                    parent_id = edge["target"]
                    break
            if parent_id and parent_id in node_map:
                node["title"] = node_map[parent_id].get("text", "")

        elif node["type"] == "HİSSƏ":
            # HİSSƏ is top level, no title
            pass

    graph = {
        "nodes": nodes,
        "edges": edges
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(graph, f, ensure_ascii=False, indent=4)

    print(f"Graph extracted and saved to {output_path}")

if __name__ == "__main__":
    input_file = os.environ["INPUT_FILE_PATH"]
    output_file = os.environ["OUTPUT_FILE_PATH"]
    extract_graph(input_file, output_file)
