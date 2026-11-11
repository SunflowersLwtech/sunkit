#!/usr/bin/env python3
"""
Quick validation script for skills - minimal version
"""

import sys
import os
import re
from pathlib import Path

# PyYAML is not installed on every machine this runs from, and a validator that
# cannot start is indistinguishable from a skill that passes. Fall back to a
# top-level-key parse, which is all this script inspects.
try:
    import yaml
except ModuleNotFoundError:
    yaml = None


def _parse_frontmatter(text):
    """Return a dict of top-level keys. Nested blocks collapse to a marker."""
    if yaml is not None:
        return yaml.safe_load(text)
    data, current, block = {}, None, None   # block: key whose value is a YAML block scalar (>- | etc.)
    for line in text.split("\n"):
        if block is not None and line[:1] in (" ", "\t"):
            data[block] = (data[block] + " " + line.strip()).strip()   # folded: join continuation lines
            continue
        block = None
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t" and ":" in line:
            key, _, value = line.partition(":")
            current = key.strip()
            v = value.strip()
            if v in (">", ">-", ">+", "|", "|-", "|+"):      # block scalar indicator, not content
                data[current] = ""; block = current; continue
            data[current] = v.strip("\"'") or {}
        elif current is not None and isinstance(data.get(current), dict):
            k, _, v = line.strip().partition(":")
            data[current][k.strip()] = v.strip().strip("\"'")
    return data

def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)

    # Check SKILL.md exists
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False, "SKILL.md not found"

    # Read and validate frontmatter
    content = skill_md.read_text()
    if not content.startswith('---'):
        return False, "No YAML frontmatter found"

    # Extract frontmatter
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format"

    frontmatter_text = match.group(1)

    # Parse YAML frontmatter
    try:
        frontmatter = _parse_frontmatter(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary"
    except Exception as e:
        return False, f"Invalid YAML in frontmatter: {e}"

    # Every frontmatter value must be JSON-serializable: agent runtimes
    # (some harnesses) json.dumps the parsed frontmatter, and
    # yaml.safe_load turns unquoted scalars like `2026-09-22` into
    # datetime.date, which makes the whole skill unloadable.
    def _jsonable(v, path="frontmatter"):
        if v is None or isinstance(v, (str, int, float, bool)):
            return None
        if isinstance(v, dict):
            for k, vv in v.items():
                if not isinstance(k, str):
                    return f"{path}: non-string key {k!r} ({type(k).__name__}) — quote it"
                r = _jsonable(vv, f"{path}.{k}")
                if r:
                    return r
            return None
        if isinstance(v, (list, tuple)):
            for i, vv in enumerate(v):
                r = _jsonable(vv, f"{path}[{i}]")
                if r:
                    return r
            return None
        return f"{path}: {type(v).__name__} value {v!r} is not JSON-serializable — quote it"

    if yaml is not None:
        bad = _jsonable(frontmatter)
        if bad:
            return False, f"Non-JSON frontmatter value: {bad}"
    else:
        # fallback parser keeps raw strings; spot-check the common offender
        for line in frontmatter_text.split("\n"):
            m = re.search(r":\s*(\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?)\s*$", line)
            if m:
                return False, (f"Unquoted date-like scalar '{m.group(1)}' parses as a "
                               f"date object, not a string — quote it")

    # Define allowed properties
    ALLOWED_PROPERTIES = {'name', 'description', 'license', 'allowed-tools', 'metadata', 'compatibility',
                          'disable-model-invocation',   # documented Claude Code key (2026-09-17)
                          # rest of the frontmatter table at code.claude.com/docs/en/skills (read 2026-09-26)
                          'user-invocable', 'when_to_use', 'argument-hint', 'arguments',
                          'disallowed-tools', 'model', 'effort', 'context', 'agent', 'background',
                          'hooks', 'paths', 'shell'}

    # Check for unexpected properties (excluding nested keys under metadata)
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected_keys:
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )

    # Check required fields
    if 'name' not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if 'description' not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    # Extract name for validation
    name = frontmatter.get('name', '')
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if name:
        # Check naming convention (kebab-case: lowercase with hyphens)
        if not re.match(r'^[a-z0-9-]+$', name):
            return False, f"Name '{name}' should be kebab-case (lowercase letters, digits, and hyphens only)"
        if name.startswith('-') or name.endswith('-') or '--' in name:
            return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
        # Check name length (max 64 characters per spec)
        if len(name) > 64:
            return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."

    # Extract and validate description
    description = frontmatter.get('description', '')
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if description:
        # Check for angle brackets
        if '<' in description or '>' in description:
            return False, "Description cannot contain angle brackets (< or >)"
        # Check description length (max 1024 characters per spec)
        if len(description) > 1024:
            return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters."

    # Validate compatibility field if present (optional)
    compatibility = frontmatter.get('compatibility', '')
    if compatibility:
        if not isinstance(compatibility, str):
            return False, f"Compatibility must be a string, got {type(compatibility).__name__}"
        if len(compatibility) > 500:
            return False, f"Compatibility is too long ({len(compatibility)} characters). Maximum is 500 characters."

    return True, "Skill is valid!"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)
    
    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)