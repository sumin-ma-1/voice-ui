# perception/ui_filter.py

def filter_elements(elements):

    useful = []

    for e in elements:

        name = (e.get("name") or "").strip().lower()
        is_icon = e.get("is_icon", False)

        # keep icons even if no text
        if not name and not is_icon:
            continue

        useful.append({
            "name": name,
            "type": (e.get("control_type") or "").lower(),
            "parent_name": (e.get("parent_name") or "").lower(),
            "parent_type": (e.get("parent_type") or "").lower(),
            "bbox": e.get("bbox"),
            "center": e.get("center"),
            "is_icon": is_icon
        })

    return useful