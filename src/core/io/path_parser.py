import re
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple

class PathParser:
    def __init__(self, source_root: str, pattern: Optional[str] = None):
        self.source_root = Path(source_root)
        self.pattern = re.compile(pattern) if pattern else None

    @staticmethod
    def split_location_tag(location_tag: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Split a combined location tag into province/city/park levels.

        Rules:
          - 3+ segments separated by '_': level1, level2, level3=remaining joined
          - 2 segments: level1, level2, None
          - 1 segment: None, None, level3
        """
        if not location_tag:
            return None, None, None
        parts = [p.strip() for p in location_tag.split("_") if p.strip()]
        if len(parts) >= 3:
            return parts[0], parts[1], "_".join(parts[2:])
        if len(parts) == 2:
            return parts[0], parts[1], None
        return None, None, parts[0]

    @staticmethod
    def parse_folder_name(folder: str):
        """
        Returns (date_start, date_end, location_part) or (None, None, folder)
        date_end is only set if range pattern matches.
        """
        # Pattern 1: Range yyyyMMdd-yyyyMMdd{location}
        match_range_full = re.match(r'^(\d{8})-(\d{8})[_\s-]*(.+)$', folder)
        if match_range_full:
            return match_range_full.group(1), match_range_full.group(2), match_range_full.group(3)

        # Pattern 2: Range yyyyMMdd-dd{location}
        match_range_short = re.match(r'^(\d{8})-(\d{2})[_\s-]*(.+)$', folder)
        if match_range_short:
            start = match_range_short.group(1)
            # Construct end date: same year/month prefix + day
            end = start[:6] + match_range_short.group(2)
            return start, end, match_range_short.group(3)

        # Pattern 3: Standard Single Date yyyyMMdd_Location
        match_single = re.match(r'^(\d{8})[_\s-]*(.+)$', folder)
        if match_single:
            return match_single.group(1), None, match_single.group(2)

        # Pattern 4: Date only
        if folder.isdigit() and len(folder) == 8:
             return folder, None, None

        return None, None, folder

    def parse(self, file_path: str) -> Dict[str, Optional[str]]:
        """
        Parse metadata from file path.
        Returns dict with keys: 'captured_date', 'location_tag', 'source_structure',
        'location_level1', 'location_level2', 'location_level3'.
        """
        abs_path = Path(file_path)
        try:
            rel_path = abs_path.relative_to(self.source_root)
        except ValueError:
            rel_path = abs_path

        result = {
            'captured_date': datetime.now().strftime("%Y%m%d"),
            'location_tag': 'Unknown',
            'source_structure': str(rel_path.parent).replace('\\', '/'),
            'location_level1': None,
            'location_level2': None,
            'location_level3': None,
        }

        parts = rel_path.parts
        if len(parts) <= 1:
            # File is in root
            return result

        folder_parts = parts[:-1] # Exclude filename
        locations = []
        found_date = None

        # Iterate all folders
        for i, folder in enumerate(folder_parts):
            is_last_folder = (i == len(folder_parts) - 1)

            # Logic for Last Folder: Try Regex First if configured
            matched_regex = False
            if is_last_folder and self.pattern:
                match = self.pattern.search(folder) # Search inside the folder name string ONLY
                if match:
                    groups = match.groupdict()
                    if 'date' in groups:
                        found_date = groups['date']
                    if 'location' in groups:
                        # Clean up location from regex
                        loc = groups['location']
                        loc = loc.rstrip('/\\_ ')
                        locations.append(loc)
                    matched_regex = True

            # Standard Logic (Parents OR Last Folder if regex failed)
            if not matched_regex:
                d_start, _, loc_part = self.parse_folder_name(folder)

                if d_start:
                    found_date = d_start
                    if loc_part: locations.append(loc_part)
                else:
                    # No date found, entire folder is location
                    # Skip pure numeric folders (likely year directories like "2025")
                    if folder.isdigit() and len(folder) >= 4:
                        # Skip year directories, but keep if it's a meaningful 8-digit date
                        if len(folder) != 8:
                            continue
                    locations.append(folder)

        if found_date:
            result['captured_date'] = found_date

        if locations:
            # Clean up and join
            clean_locs = [loc.strip('_ ') for loc in locations if loc]
            location_tag = '_'.join(clean_locs)
            result['location_tag'] = location_tag
            l1, l2, l3 = self.split_location_tag(location_tag)
            result['location_level1'] = l1
            result['location_level2'] = l2
            result['location_level3'] = l3

        return result
