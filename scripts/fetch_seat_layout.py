from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SEAT_PAGE_URL = "https://www.vlaamsparlement.be/nl/volksvertegenwoordigers/wie-zit-waar-het-vlaams-parlement"
OUTPUT_PATH = ROOT_DIR / "data" / "reference" / "seat_layout.json"


def extract_balanced_json_blob(text: str, key: str) -> dict:
    needle = f'"{key}":'
    start = text.index(needle) + len(needle)
    brace_start = text.index("{", start)
    depth = 0
    end = None
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    return json.loads(text[brace_start:end])


def parse_path_points(path_d: str) -> list[tuple[float, float]]:
    tokens = re.findall(r"[A-Za-z]|-?\d+(?:\.\d+)?", path_d)
    points: list[tuple[float, float]] = []
    index = 0
    command = None
    current_x = 0.0
    current_y = 0.0
    start_x = 0.0
    start_y = 0.0

    def take_numbers(count: int) -> list[float]:
        nonlocal index
        values = [float(tokens[index + offset]) for offset in range(count)]
        index += count
        return values

    while index < len(tokens):
        token = tokens[index]
        if re.fullmatch(r"[A-Za-z]", token):
            command = token
            index += 1
        if command is None:
            break

        if command in {"M", "L"}:
            x, y = take_numbers(2)
            current_x, current_y = x, y
            if command == "M":
                start_x, start_y = current_x, current_y
                command = "L"
            points.append((current_x, current_y))
        elif command in {"m", "l"}:
            dx, dy = take_numbers(2)
            current_x += dx
            current_y += dy
            if command == "m":
                start_x, start_y = current_x, current_y
                command = "l"
            points.append((current_x, current_y))
        elif command == "H":
            x = take_numbers(1)[0]
            current_x = x
            points.append((current_x, current_y))
        elif command == "h":
            current_x += take_numbers(1)[0]
            points.append((current_x, current_y))
        elif command == "V":
            y = take_numbers(1)[0]
            current_y = y
            points.append((current_x, current_y))
        elif command == "v":
            current_y += take_numbers(1)[0]
            points.append((current_x, current_y))
        elif command == "C":
            x1, y1, x2, y2, x, y = take_numbers(6)
            points.extend([(x1, y1), (x2, y2), (x, y)])
            current_x, current_y = x, y
        elif command == "c":
            dx1, dy1, dx2, dy2, dx, dy = take_numbers(6)
            points.extend(
                [
                    (current_x + dx1, current_y + dy1),
                    (current_x + dx2, current_y + dy2),
                    (current_x + dx, current_y + dy),
                ]
            )
            current_x += dx
            current_y += dy
        elif command == "S":
            x2, y2, x, y = take_numbers(4)
            points.extend([(x2, y2), (x, y)])
            current_x, current_y = x, y
        elif command == "s":
            dx2, dy2, dx, dy = take_numbers(4)
            points.extend([(current_x + dx2, current_y + dy2), (current_x + dx, current_y + dy)])
            current_x += dx
            current_y += dy
        elif command == "Q":
            x1, y1, x, y = take_numbers(4)
            points.extend([(x1, y1), (x, y)])
            current_x, current_y = x, y
        elif command == "q":
            dx1, dy1, dx, dy = take_numbers(4)
            points.extend([(current_x + dx1, current_y + dy1), (current_x + dx, current_y + dy)])
            current_x += dx
            current_y += dy
        elif command == "T":
            x, y = take_numbers(2)
            current_x, current_y = x, y
            points.append((current_x, current_y))
        elif command == "t":
            dx, dy = take_numbers(2)
            current_x += dx
            current_y += dy
            points.append((current_x, current_y))
        elif command in {"A", "a"}:
            values = take_numbers(7)
            if command == "A":
                current_x, current_y = values[5], values[6]
            else:
                current_x += values[5]
                current_y += values[6]
            points.append((current_x, current_y))
        elif command in {"Z", "z"}:
            current_x, current_y = start_x, start_y
            points.append((current_x, current_y))
        else:
            break

    return points


def seat_center_coordinates(path_d: str) -> tuple[float, float] | None:
    points = parse_path_points(path_d)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def main() -> None:
    response = requests.get(SEAT_PAGE_URL, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = extract_balanced_json_blob(response.text, "seat_distribution")

    representatives = payload["representatives"]
    seat_paths = json.loads(payload["seats"])

    rows = []
    for seat_entry in seat_paths:
        seat_id, path_d = next(iter(seat_entry.items()))
        seat_number = int(seat_id)
        coordinates = seat_center_coordinates(path_d)
        if not coordinates:
            continue
        x, y = coordinates
        representative = representatives.get(seat_id, {})
        link = representative.get("link", {})
        rows.append(
            {
                "seat_number": seat_number,
                "x": round(x, 3),
                "y": round(y, 3),
                "member_label": link.get("label"),
                "member_url": link.get("url"),
                "faction_id": representative.get("factionId"),
                "faction_name": representative.get("factionName"),
                "faction_color": representative.get("factionColor"),
            }
        )

    rows.sort(key=lambda item: item["seat_number"])
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} seats to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
